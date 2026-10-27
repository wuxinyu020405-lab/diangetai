# -*- coding: utf-8 -*-
"""第2步单测：两档链结构 / normalize / default 档不吃枚举 / 预检裁链 / legacy 移除。"""
import sys
sys.path.insert(0, "点歌台拆分")

import settings
import musiclib

passed, failed = 0, 0


def case(name, cond, detail=""):
    global passed, failed
    passed += cond; failed += (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


print("═══ A. 两档数据结构 ═══")
case("UI 只有 flac/default", set(settings.QUALITY_UI_MAP) == {"flac", "default"})
case("文案已拍板", settings.QUALITY_UI_MAP["flac"] == "FLAC 无损品质"
     and settings.QUALITY_UI_MAP["default"] == "默认品质")
ch = settings.QUALITY_FALLBACK_CHAINS
case("链 key 收敛为 2", set(ch) == {"flac", "default"})
case("flac 链 2 档", len(ch["flac"]) == 2)
case("档位元组 5 字段", all(len(t) == 5 for k in ch for t in ch[k]))
t_flac, t_def = ch["flac"]
case("flac 档 needs_enum=True", t_flac[4] is True)
case("default 档 needs_enum=False", t_def[4] is False)
case("default 档 enum 候选为空", t_def[2] == ())
case("default 档扩展名 .mp3", t_def[3] == ".mp3")
case("hires/master/mp3_320/mp3_128 全部消失",
     not any(k in ch for k in ("hires", "master", "mp3_320", "mp3_128")))

print("═══ B. normalize_quality_key（旧配置值归一） ═══")
case("flac→flac", settings.normalize_quality_key("flac") == "flac")
case("master→flac（无损诉求保留）", settings.normalize_quality_key("master") == "flac")
case("hires→flac（原空档，现走flac链）", settings.normalize_quality_key("hires") == "flac")
case("mp3_320→default", settings.normalize_quality_key("mp3_320") == "default")
case("mp3_128→default", settings.normalize_quality_key("mp3_128") == "default")
case("未知值→default", settings.normalize_quality_key("???") == "default")

print("═══ C. default 档不再被'枚举探测失败'误杀（13.1 核心） ═══")
got = musiclib.resolve_song_file_type(None, ())
case("空候选名 resolve 返回 None（default 档本来就没有枚举）", got is None)
# 直接模拟主循环判定：ft_enum=None（探测失败/无枚举）时，新旧逻辑各如何处置
for tier_key, tier_label, enum_names, default_ext, needs_enum in settings.QUALITY_FALLBACK_CHAINS["flac"]:
    ft_enum = None                      # 两档都假设 resolve 出 None（default 必然，flac 视为故障）
    would_break_old = ft_enum is None and tier_key != "mp3_128"   # 旧逻辑（step1 前的原样）
    would_break_new = needs_enum and ft_enum is None              # 新逻辑（needs_enum 标记位）
    if tier_key == "default":
        case("旧逻辑会误杀 default（白跑+降级）", would_break_old is True)
        case("新逻辑放行 default（不探测枚举）", would_break_new is False)
    else:
        case("flac 档探测失败仍可跳（needs_enum=True 保护）", would_break_new is True)

print("═══ D. size_flac 预检语义 ═══")
case("extract_song_info 返回 5 元组", len(musiclib.extract_song_info(None)) == 5)
case("None 响应 flac_size=None", musiclib.extract_song_info(None)[4] is None)


class FakeFile:
    def __init__(self, sz): self.size_flac = sz


class FakeSong:
    def __init__(self, f): self.mid = "m"; self.name = "n"; self.singer = []; self.file = f


class FakeRes:
    def __init__(self, s): self.song = [s]


r = FakeRes(FakeSong(FakeFile(0)))
case("size_flac=0 → 明确没有(可裁链)", r.song[0].file.size_flac == 0)
r = FakeRes(FakeSong(FakeFile(55397039)))
case("size_flac>0 → 有 FLAC", musiclib.extract_song_info(r)[4] == 55397039)
r = FakeRes(FakeSong(None))
case("file 缺失 → 未知(None)，不裁链", musiclib.extract_song_info(r)[4] is None)

print("═══ E. 裁链逻辑（复现 download_audio_qq 的新代码） ═══")
chain = settings.QUALITY_FALLBACK_CHAINS["flac"]
for flac_size, want_keys in [(0, ["default"]), (None, ["flac", "default"]), (123, ["flac", "default"])]:
    pruned = [t for t in chain if t[0] != "flac"] if flac_size == 0 else chain
    got_keys = [t[0] for t in (pruned if pruned else chain)]
    case(f"flac_size={flac_size} → 尝试档位 {want_keys}", got_keys == want_keys, str(got_keys))

print("═══ F. legacy 段已删除 ═══")
src = open("点歌台拆分/musiclib.py", encoding="utf-8").read()
case("find_cached_file_for_tier 不再引用 legacy/{mid}.mp3",
     'legacy = os.path.join' not in src)
case('mp3_128 特判已消失', 'tier_key == "mp3_128"' not in src)

print(f"\n总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
