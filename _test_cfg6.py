# -*- coding: utf-8 -*-
"""第6步单测A：merge_config 旧配置升级——新字段回落默认值，旧字段不丢。"""
import copy
import sys

sys.path.insert(0, "点歌台拆分")
import settings
import state

passed, failed = 0, 0


def case(name, cond, detail=""):
    global passed, failed
    passed += cond; failed += (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


DEFAULTS = copy.deepcopy(state.style_config)

print("═══ A. 无旧配置（全新安装）═══")
merged = settings.merge_config({}, copy.deepcopy(DEFAULTS))
case("lyric.opacity=1.0", merged["lyric"]["opacity"] == 1.0)
case("global.volume=1.0", merged["global"]["volume"] == 1.0)
case("mixed 新字段齐全", all(k in merged["mixed"] for k in
     ("show_prefix", "max_chars", "align", "lines_prev", "lines_next",
      "max_items", "show_index", "show_requester", "requester_sep")))
case("queue 新字段齐全", all(k in merged["queue"] for k in
     ("max_items", "show_index", "show_requester", "requester_sep")))

print("═══ B. 模拟用户现存旧配置（第6步前的 config.json 形态）═══")
old = copy.deepcopy(DEFAULTS)
for k in ("show_prefix", "max_chars", "align", "lines_prev", "lines_next",
          "max_items", "show_index", "show_requester", "requester_sep"):
    old["mixed"].pop(k, None)
old["lyric"].pop("opacity", None)
old["queue"].pop("max_items", None)
old.pop("global", None)
# 用户旧配置里真实存在过的自定义值必须保留
old["lyric"]["size"] = 40
old["mixed"]["color_lyric"] = "#123456"
old["audio_quality"] = "flac"
merged = settings.merge_config(old, copy.deepcopy(DEFAULTS))
case("旧字段保留 lyric.size=40", merged["lyric"]["size"] == 40)
case("旧字段保留 mixed.color_lyric", merged["mixed"]["color_lyric"] == "#123456")
case("新字段回落 opacity=1.0", merged["lyric"]["opacity"] == 1.0)
case("新字段回落 volume=1.0", merged["global"]["volume"] == 1.0)
case("mixed.max_chars 默认0(不截断)", merged["mixed"]["max_chars"] == 0)
case("mixed.align 默认center", merged["mixed"]["align"] == "center")

print("═══ C. 旧值半迁移（用户已手动存过部分新字段）═══")
old["lyric"]["opacity"] = 0.7
old["global"] = {"volume": 0.5}
merged = settings.merge_config(old, copy.deepcopy(DEFAULTS))
case("opacity=0.7 读回", merged["lyric"]["opacity"] == 0.7)
case("volume=0.5 读回", merged["global"]["volume"] == 0.5)

print("═══ D. 极端脏值容忍 ═══")
old2 = {"mixed": "not-a-dict", "lyric": None}
try:
    merged = settings.merge_config(old2, copy.deepcopy(DEFAULTS))
    case("脏段跳过不崩", merged["lyric"]["opacity"] == 1.0)
except Exception as e:
    case("脏段跳过不崩", False, str(e))

print(f"\n总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
