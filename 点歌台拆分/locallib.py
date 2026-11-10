# -*- coding: utf-8 -*-
"""本地曲库（v1.2.8）：观众发「本地点歌 xxx」时，只在 my_songs/ 里按相似度找歌。

设计边界（用户 2026-11-10 拍板）：
  · 只做显式命令「本地点歌 xxx」，普通「点歌」不查本地库、行为完全不变；
  · 不要别名表、不读元数据——文件名主干就是歌名（中文/英文等文字命名）；
  · 按一定比例内的相似度取最高分；低于阈值、或与第二名过于接近（歧义）都不播；
  · 本模块只负责"找文件"，不碰播放队列、不碰弹幕；路径由 settings.LOCAL_SONGS_DIR 决定。

相似度用标准库 difflib.SequenceMatcher（曲库很小，零依赖足够）：
  归一化 = NFKC(全角转半角) → 去首尾空白 → 大小写折叠 → 压掉中间空白。
  最终分数 = 0.75 * 序列相似度 + 0.25 * 包含关系加成（子串/被包含）。
"""
import difflib
import os
import re
import unicodedata

# 可由 config.json 的 local_match_threshold 覆盖（0~1，默认 0.6）
DEFAULT_THRESHOLD = 0.60
# 第一名与第二名差距小于这个值 = 歧义，不播
DEFAULT_MARGIN = 0.05

VALID_EXTS = (".mp3", ".wav", ".flac", ".ogg")   # pygame 稳妥支持的格式
MIN_BYTES = 100 * 1024                            # <100KB 视为残片，忽略


def normalize(s):
    """归一化：NFKC → 去空白 → 小写折叠。仅用于比较，不改文件名。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\s+", "", s)
    return s.casefold()


def song_name_of(filename):
    """文件名主干当歌名：去扩展名。"""
    return os.path.splitext(filename)[0]


def list_songs(folder):
    """扫描文件夹，返回 [{"path", "name", "norm"}]。忽略小残片/不支持格式/子目录。
    不缓存：曲库小、每次点歌扫一次即可，用户丢文件进去立刻生效，无需重启。"""
    out = []
    try:
        if not os.path.isdir(folder):
            return out
        for fn in os.listdir(folder):
            full = os.path.join(folder, fn)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(fn)[1].lower() not in VALID_EXTS:
                continue
            try:
                if os.path.getsize(full) < MIN_BYTES:
                    continue
            except OSError:
                continue
            name = song_name_of(fn)
            out.append({"path": full, "name": name, "norm": normalize(name),
                        "ext": os.path.splitext(fn)[1].lower()})
    except OSError:
        pass
    return out


def _score(query_norm, song_norm):
    """包含关系优先：观众常只打半截歌名（「夏天」对「我们的夏天」），
    SequenceMatcher 会因长度差惩罚长歌名，导致短的《那年夏天》反而胜出。
    因此 query 是 song 的子串时直接给高分（0.9 基准 + 长度贴合微调），
    且包含者越短越优先，避免长名永远占优。"""
    seq = difflib.SequenceMatcher(None, query_norm, song_norm).ratio()
    if not query_norm or not song_norm:
        return seq
    if query_norm in song_norm:
        # 命中子串：0.90 起，按 query/歌名长度比再补 0~0.1。
        # 注意：两个歌名都含同一短词时（如「我们的夏天」vs「那年夏天」），
        # 二者得分天然接近，会由 find_best 的 margin 判为歧义 → 回弹幕让观众说全名，
        # 不会自作主张挑一首。这是刻意的：短词本来就不该自动决定播哪首。
        return 0.90 + 0.10 * (len(query_norm) / len(song_norm))
    if song_norm in query_norm:
        return 0.90 + 0.10 * (len(song_norm) / len(query_norm))
    return seq


def find_best(query, folder, threshold=DEFAULT_THRESHOLD, margin=DEFAULT_MARGIN):
    """返回 (结果字典, 原因)。没有可播结果时 result=None。

    result = {"path", "name", "score", "runner_up"}; reason 为
    empty_library / no_match / ambiguous / ok 之一，供上层写日志/回弹幕。
    """
    songs = list_songs(folder)
    if not songs:
        return None, "empty_library"

    q = normalize(query)
    if not q:
        return None, "no_match"

    scored = []
    for s in songs:
        sc = _score(q, s["norm"])
        scored.append((sc, s))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))

    top_score, top = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0

    if top_score < threshold:
        return None, "no_match"
    if (top_score - second) < margin:
        return None, "ambiguous"

    return ({"path": top["path"], "name": top["name"],
             "score": round(top_score, 4), "runner_up": round(second, 4)}, "ok")


def make_entry(result, requester, platform="local"):
    """构造 playlist 条目：带 file_path 供播放器直接播，其余字段沿用既有约定。"""
    return {
        "name": result["name"],
        "display_name": result["name"],
        "mid": None,
        "requester": requester,
        "file_path": result["path"],
        "source": platform,
    }


def folder_hint(folder):
    """给 GUI / 日志用的一句人话说明。"""
    return "把录好的歌（mp3/wav/flac/ogg，用中文或英文歌名命名）放进：%s" % folder


def _sniff_container(path):
    """按文件头判断真实容器，用来识破"改后缀"的文件。
    返回 'mp4' / 'flac' / 'ogg' / 'wav' / 'mp3' / 'id3' / None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
        return None
    if len(head) < 4:
        return None
    if head[:3] == b"ID3":
        return "id3"
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "mp3"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "mp4"          # 典型 m4a/mp4 音频，pygame 不稳/不支持
    return None


def check_playable(path):
    """入列前确认文件真能播。返回 (可播, 中文原因)。

    两类拦截：
      ① 改后缀：文件头是 mp4(ftyp) 却叫 .mp3 —— pygame 会报 corrupt mp3；
      ② 真加载失败：文件损坏/编码不支持 —— 用与播放完全相同的 pygame 接口试一次。
    pygame 未初始化等环境异常一律放行（宁可让它试播，也不要误杀正常文件）。
    """
    if not path or not os.path.isfile(path):
        return False, "文件不存在"
    if os.path.getsize(path) < MIN_BYTES:
        return False, "文件太小，可能没下载完整"

    ext = os.path.splitext(path)[1].lower()
    real = _sniff_container(path)
    if real == "mp4" and ext != ".m4a":
        return False, "这个文件其实是 m4a/mp4 格式，只是改成了 %s 后缀" % ext
    if ext == ".flac" and real not in ("flac", None):
        return False, "后缀是 flac，但内容不是 flac"
    if ext == ".ogg" and real not in ("ogg", None):
        return False, "后缀是 ogg，但内容不是 ogg"

    try:
        import pygame
        if not pygame.mixer.get_init():
            return True, ""            # 播放引擎还没初始化：放行，交给播放器试
        try:
            pygame.mixer.music.load(path)
        except Exception as e:
            msg = str(e).lower()
            if "mp3" in msg or "corrupt" in msg:
                return False, "文件损坏或格式不对，播不出来"
            return False, "播放引擎无法解码这个文件"
        return True, ""
    except Exception:
        return True, ""                # pygame 不可用属环境问题，不拦

