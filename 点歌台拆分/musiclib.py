"""
音乐库：QQ音乐取址与音质枚举探测、本地缓存文件管理、搜索/URL 解析
"""

import inspect
import os
import pygame
import settings
import state
import ply                     # 原 L1：qqmusic_api→jsonpath_ng→ply 传递依赖
import jsonpath_ng             # 原 L2：同上
import jsonpath_ng.ext         # 原 L3：同上

try:
    import jsonpath_ng.ply_tables
except Exception:
    pass

# ================= 动态探测 qqmusic_api 音质枚举与模型 =================
SongFileInfo = None

SongFileType = None

for _mod_name in ("qqmusic_api.modules.song", "qqmusic_api.models.song", "qqmusic_api.song", "qqmusic_api"):
    try:
        _mod = __import__(_mod_name, fromlist=["SongFileInfo", "SongFileType"])
        if SongFileInfo is None and hasattr(_mod, "SongFileInfo"):
            SongFileInfo = getattr(_mod, "SongFileInfo")
        if SongFileType is None and hasattr(_mod, "SongFileType"):
            SongFileType = getattr(_mod, "SongFileType")
    except Exception:
        pass

if SongFileType is None and SongFileInfo is not None:
    try:
        for _p in inspect.signature(SongFileInfo).parameters.values():
            if _p.default is not inspect.Parameter.empty and hasattr(_p.default, "__class__") and "FileType" in _p.default.__class__.__name__:
                SongFileType = _p.default.__class__
                break
    except Exception:
        pass

# ================= 工具与核心逻辑 =================
def clean_cache_if_needed():
    try:
        if not os.path.exists(settings.CACHE_DIR):
            return
        max_files = state.style_config.get("max_cache_files", 100)
        max_size_mb = state.style_config.get("max_cache_size_mb", 500)
        files = []
        total_size = 0
        for f in os.listdir(settings.CACHE_DIR):
            full_path = os.path.join(settings.CACHE_DIR, f)
            if os.path.isfile(full_path):
                stat = os.stat(full_path)
                files.append({"path": full_path, "mtime": stat.st_mtime, "size": stat.st_size})
                total_size += stat.st_size
        total_size_mb = total_size / (1024 * 1024)
        if len(files) > max_files or total_size_mb > max_size_mb:
            files.sort(key=lambda x: x["mtime"])
            while files and (len(files) > max_files or total_size_mb > max_size_mb):
                oldest = files.pop(0)
                try:
                    os.remove(oldest["path"])
                    total_size_mb -= oldest["size"] / (1024 * 1024)
                    print(f"🗑️ 缓存空间清理，已删除旧歌曲文件: {os.path.basename(oldest['path'])}")
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

    except Exception as e:
        print("缓存管理异常:", e)

def resolve_song_file_type(client, candidate_names):
    global SongFileType
    if SongFileType is None and hasattr(client, "song"):
        try:
            sig = inspect.signature(client.song.get_song_urls)
            for p in sig.parameters.values():
                if p.default is not inspect.Parameter.empty and hasattr(p.default, "__class__") and "FileType" in p.default.__class__.__name__:
                    SongFileType = p.default.__class__
                    break
        except Exception as e:
            print(f"[WARN] 异常已捕获: {e}")

    if SongFileType is None: return None
    members = {k.upper(): getattr(SongFileType, k) for k in dir(SongFileType) if not k.startswith("_")}
    for name in candidate_names:
        key = name.upper()
        if key in members: return members[key]
        key_no_underscore = key.replace("_", "")
        for mk, mv in members.items():
            if mk.replace("_", "") == key_no_underscore: return mv
    return None

async def request_song_url_with_type(client, song_mid, file_type_enum, credential):
    if SongFileInfo is not None:
        req_item = None
        if file_type_enum is not None:
            for field_name in ("file_type", "type", "quality"):
                try:
                    req_item = SongFileInfo(mid=song_mid, **{field_name: file_type_enum})
                    break
                except TypeError: continue
            if req_item is None:
                try: req_item = SongFileInfo(song_mid, file_type_enum)
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

        if req_item is None: req_item = SongFileInfo(mid=song_mid)

        if file_type_enum is not None:
            try:
                sig = inspect.signature(client.song.get_song_urls)
                if "file_type" in sig.parameters:
                    return await client.song.get_song_urls([req_item], file_type=file_type_enum, credential=credential)
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

        return await client.song.get_song_urls([req_item], credential=credential)
    else:
        if file_type_enum is not None:
            for kw in ("file_type", "type", "quality"):
                try:
                    return await client.song.get_song_urls([song_mid], **{kw: file_type_enum}, credential=credential)
                except TypeError: continue
        return await client.song.get_song_urls([song_mid], credential=credential)

def detect_ext_from_url(play_url, default_ext=".mp3"):
    if not play_url: return default_ext
    path_part = play_url.split("?", 1)[0].lower()
    for ext in (".flac", ".m4a", ".ogg", ".mp3", ".wav", ".ape"):
        if path_part.endswith(ext): return ext
    return default_ext

def find_cached_file_for_tier(song_mid, tier_key):
    if not song_mid: return None
    for ext in (".flac", ".mp3", ".m4a", ".ogg", ".wav"):
        candidate = os.path.join(settings.CACHE_DIR, f"{song_mid}_{tier_key}{ext}")
        if os.path.exists(candidate):
            if os.path.getsize(candidate) > 100 * 1024: return candidate
            else:
                try: os.remove(candidate)
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

    if tier_key == "mp3_128":
        legacy = os.path.join(settings.CACHE_DIR, f"{song_mid}.mp3")
        if os.path.exists(legacy):
            if os.path.getsize(legacy) > 100 * 1024: return legacy
            else:
                try: os.remove(legacy)
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

    return None

# ==================== 本地缓存检查与损坏文件清理 ====================
def check_local_song_exists(download_dir: str, title: str, artist: str, min_size_kb: int = 100) -> tuple:
    """检查本地是否已有该歌曲，且文件完整可播放。返回: (是否存在可用文件, 文件路径)"""
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
    safe_artist = "".join(c for c in artist if c not in r'\/:*?"<>|').strip()

    # 尝试精确匹配 "歌名 - 歌手.ext"
    for ext in [".flac", ".mp3", ".ogg", ".m4a", ".wav"]:
        filename = f"{safe_title} - {safe_artist}{ext}"
        filepath = os.path.join(download_dir, filename)
        if os.path.exists(filepath):
            size_kb = os.path.getsize(filepath) / 1024
            if size_kb >= min_size_kb:
                # 尝试用 pygame 验证文件可读性
                try:
                    if pygame.mixer.get_init():
                        pygame.mixer.music.load(filepath)
                        print(f"[INFO] 本地缓存命中: {os.path.basename(filepath)} ({size_kb:.1f}MB)")
                        return True, filepath
                except Exception as e:
                    print(f"[WARN] 本地文件无法加载({type(e).__name__})，判定为损坏: {filepath}")
                    try:
                        os.remove(filepath)
                        print(f"[INFO] 已删除损坏文件: {os.path.basename(filepath)}")
                    except Exception as e2:
                        print(f"[WARN] 删除损坏文件失败: {e2}")
                    continue

    # 模糊匹配：在目录中查找包含歌名关键词的文件
    if os.path.isdir(download_dir):
        for f in os.listdir(download_dir):
            filepath = os.path.join(download_dir, f)
            if not os.path.isfile(filepath):
                continue
            # 检查文件大小
            size_kb = os.path.getsize(filepath) / 1024
            if size_kb < min_size_kb:
                # 文件过小，判定为残片，删除
                try:
                    os.remove(filepath)
                    print(f"[INFO] 删除残片({size_kb:.1f}KB): {f}")
                except Exception as e:
                    print(f"[WARN] 删除残片失败: {e}")
                continue
            # 模糊匹配文件名（检查歌名关键词是否出现在文件名中）
            if title and title in f:
                try:
                    if pygame.mixer.get_init():
                        pygame.mixer.music.load(filepath)
                        print(f"[INFO] 本地缓存命中(模糊匹配): {os.path.basename(filepath)} ({size_kb:.1f}MB)")
                        return True, filepath
                except Exception:
                    try:
                        os.remove(filepath)
                        print(f"[INFO] 已删除损坏文件: {os.path.basename(filepath)}")
                    except Exception:
                        pass
                    continue

    return False, None

def clean_corrupted_files(download_dir: str, min_size_kb: int = 100) -> int:
    """扫描下载目录，删除所有损坏/不完整的音频文件。返回: 删除的文件数量"""
    if not os.path.isdir(download_dir):
        return 0

    valid_exts = {".flac", ".mp3", ".ogg", ".m4a", ".wav"}
    removed_count = 0

    for item in os.listdir(download_dir):
        filepath = os.path.join(download_dir, item)
        if not os.path.isfile(filepath):
            continue
        if os.path.splitext(item)[1].lower() not in valid_exts:
            continue

        size_kb = os.path.getsize(filepath) / 1024

        # 过小的文件直接删除
        if size_kb < min_size_kb:
            try:
                os.remove(filepath)
                print(f"[CLEAN] 删除残片({size_kb:.1f}KB): {item}")
                removed_count += 1
            except Exception as e:
                print(f"[WARN] 删除失败: {item} - {e}")
            continue

        # 尝试加载验证
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.load(filepath)
        except Exception:
            try:
                os.remove(filepath)
                print(f"[CLEAN] 删除损坏文件: {item}")
                removed_count += 1
            except Exception as e:
                print(f"[WARN] 删除失败: {item} - {e}")

    if removed_count > 0:
        print(f"[INFO] 批量清理完成，共删除 {removed_count} 个损坏文件")
    return removed_count

def extract_song_info(search_res):
    if not search_res: return None, None, None, None
    try:
        songs = None
        if hasattr(search_res, 'song'):
            song_attr = search_res.song
            if isinstance(song_attr, list): songs = song_attr
            elif hasattr(song_attr, 'song'): songs = song_attr.song
            elif isinstance(song_attr, dict) and 'song' in song_attr: songs = song_attr['song']
        if not songs and hasattr(search_res, 'songs'): songs = search_res.songs
        if not songs or not isinstance(songs, list) or len(songs) == 0: return None, None, None, None
        first_song_obj = songs[0]
        mid = getattr(first_song_obj, 'mid', None)
        name = getattr(first_song_obj, 'name', None)
        singer_name = "未知歌手"
        singer_list = getattr(first_song_obj, 'singer', [])
        if singer_list: singer_name = getattr(singer_list[0], 'name', "未知歌手")
        return mid, name, singer_name, first_song_obj
    except Exception: return None, None, None, None

# ================= 下载失败归因（需求9：读 result 业务码 + 异常分类） =================
# 库官方文档（qqmusic_api/models/song.py UrlinfoItem.result）：
#   0=成功, 104003=无权限, 104004=VKey获取失败, 104013=播放设备受限
URL_RESULT_TEXT = {
    0: "成功",
    104003: "无该音质权限",
    104004: "VKey获取失败",
    104013: "播放设备受限",
}

try:
    from qqmusic_api.core import exceptions as qq_exc
except Exception:
    qq_exc = None


def url_result_text(code):
    return URL_RESULT_TEXT.get(code, f"未知业务码({code})")


def extract_url_detail(url_res, cdn=""):
    """解析 get_song_urls 响应，返回 dict：
    {url, result, result_text, filename, expiration}
    - 成功: url 为完整下载地址, result=0
    - 业务失败: url=None, result=业务码, result_text=中文含义
    - 结构异常: url=None, result=None, result_text 说明原因
    与原 extract_url 的区别：不再丢弃 result/expiration，失败可归因。"""
    detail = {"url": None, "result": None, "result_text": "", "filename": None, "expiration": None}
    if not url_res:
        detail["result_text"] = "响应为空"
        return detail
    try:
        detail["expiration"] = getattr(url_res, "expiration", None)
        data = getattr(url_res, "data", None)
        if not (isinstance(data, list) and data):
            detail["result_text"] = "响应无 data 列表"
            return detail
        info = data[0]
        detail["filename"] = getattr(info, "filename", None)
        code = getattr(info, "result", None)
        detail["result"] = code
        if code is not None and code != 0:
            detail["result_text"] = url_result_text(code)
            return detail
        purl = getattr(info, "purl", None) or ""
        if not purl:
            detail["result_text"] = "purl 为空(result=0)"
            return detail
        if purl.startswith("http"):
            detail["url"] = purl
        elif cdn:
            detail["url"] = f"{cdn.rstrip('/')}/{purl.lstrip('/')}"
        else:
            detail["result_text"] = "purl 为相对路径但无 CDN 前缀"
    except Exception as e:
        detail["result_text"] = f"解析异常 {type(e).__name__}: {e}"
    return detail


def classify_api_exception(exc):
    """把 qqmusic_api 异常分类为处置动作。返回 (action, 中文描述)。
    action: quota=触发风控配额(立即中止) / refresh_cred=凭证过期(续期后重试)
            skip=上游拒绝(不重试,跳档) / retry=网络问题(退避重试)
    分类顺序重要：Ratelimited/Credential 都继承 CgiApiException，必须先判子类。"""
    if qq_exc is not None:
        if isinstance(exc, qq_exc.RatelimitedError):
            return "quota", "触发服务端风控/配额限制"
        if isinstance(exc, (qq_exc.CredentialExpiredError, qq_exc.LoginAuthExpiredError)):
            return "refresh_cred", "登录凭证过期"
        if isinstance(exc, (qq_exc.TimeoutNetworkError, qq_exc.NetworkError)):
            return "retry", "网络超时/中断"
        if isinstance(exc, (qq_exc.ApiDataError, qq_exc.GlobalApiError, qq_exc.CgiApiException)):
            return "skip", "上游接口拒绝或数据异常"
    return "retry", f"未分类异常 {type(exc).__name__}"


async def try_refresh_credential(credential):
    """尝试用库自带能力续期凭证。成功返回新 Credential，失败返回 None。"""
    if credential is None:
        return None
    try:
        async with Client(credential=credential) as client:
            res = client.login.refresh_credential(credential)
            if inspect.isawaitable(res):
                res = await res
            return res
    except Exception:
        return None
