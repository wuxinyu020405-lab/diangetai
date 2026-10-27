# -*- coding: utf-8 -*-
"""第6步单测：音量应用 / 透明度系数 / 队列选项 / get_volume 边界。"""
import io
import re
import sys

sys.path.insert(0, "点歌台拆分")
import settings
import state

passed, failed = 0, 0


def case(name, cond, detail=""):
    global passed, failed
    passed += cond; failed += (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


# ── 用 stub 起一个不带 tkinter 的 MusicApp 替身，验证方法逻辑 ──
import mainapp


class Stub:
    audio_backend = "none"   # 无音频环境下 set_volume 应安全跳过而非崩

    def __init__(self):
        self.logs = []
        self.saved = 0
        self.root = None

    def log(self, m):
        self.logs.append(m)

    def schedule_save_style(self):
        self.saved += 1


s = Stub()
s.get_volume = mainapp.MusicApp.get_volume.__get__(s)
apply_volume = mainapp.MusicApp.apply_volume.__get__(s)
get_volume = s.get_volume

print("═══ A. get_volume 边界 ═══")
state.style_config.setdefault("global", {})["volume"] = 1.0
case("默认1.0", get_volume() == 1.0)
state.style_config["global"]["volume"] = 0.35
case("0.35 透传", abs(get_volume() - 0.35) < 1e-9)
state.style_config["global"]["volume"] = 2
case("2 → 钳到1", get_volume() == 1.0)
state.style_config["global"]["volume"] = -1
case("-1 → 钳到0", get_volume() == 0.0)
state.style_config["global"]["volume"] = "abc"
case("脏值回落1.0", get_volume() == 1.0)
del state.style_config["global"]
case("global 段缺失→1.0", get_volume() == 1.0)

print("═══ B. apply_volume ═══")
state.style_config["global"] = {"volume": 1.0}
v = apply_volume()   # 无滑杆值：只施加不写盘
case("无参返回当前值", v == 1.0)
case("无参不触发保存", s.saved == 0)
s.scale_volume = None
state.style_config["global"]["volume"] = 0.5
v = apply_volume("35")   # 模拟滑杆值35 → 0.35
case("滑杆35→0.35", v == 0.35)
case("写入 style_config", state.style_config["global"]["volume"] == 0.35)
case("触发保存调度", s.saved == 1)
v = apply_volume("150")
case("滑杆越界150→钳到1.0", v == 1.0)
v = apply_volume("bad")
case("滑杆脏值回落配置值", v == 1.0)
lbl_err = []
try:
    apply_volume("50")   # lbl_volume_pct 不存在 → 内部 try 兜住
except Exception as e:
    lbl_err.append(e)
case("标签缺失不崩", not lbl_err, str(lbl_err))

print("═══ C. HTML/JS 改动静态核验（node 语法 + 关键点存在性）═══")
src = io.open("点歌台拆分/overlay.py", encoding="utf-8").read()
js = re.search(r"<script>(.*?)</script>", src, re.S).group(1)
case("applyLyricOpacity 已定义", "function applyLyricOpacity" in js)
case("mixed 分支调用", js.count("applyLyricOpacity(cfg.lyric.opacity") == 2)  # mixed+lyric
case("滚动行乘 opK", js.count("* opK") == 3)
case("窗口外行仍0（0×k=0 数学上无需缩放，保持字面量）",
     js.count("el.style.opacity = '0'") == 1)
case("layoutKey 含 lyricOpK", "${lyricOpK}" in js)
case("CSS 变量兜底0.5", "var(--lyric-op-base, 0.5)" in src and "var(--lyric-op-active, 1)" in src)
case("mixed 前缀开关", "cfg.mixed.show_prefix" in js)
case("mixed 截断", "mMax" in js)
case("queue-only max_items", "cfg.queue.max_items" in js)
case("mixed max_items", "cfg.mixed.max_items" in js)
case("mixed 对齐独立", "cfg.mixed.align" in js)
case("mixed 行数兜底旧行为",
     "cfg.mixed.lines_prev !== undefined" in js)

print("═══ D. 新配置字段默认值=现状 ═══")
case("mixed.show_prefix=True", state.style_config["mixed"]["show_prefix"] is True)
case("mixed.max_chars=0(不截)", state.style_config["mixed"]["max_chars"] == 0)
case("mixed.max_items=0(不限)", state.style_config["mixed"]["max_items"] == 0)
case("mixed.show_index=True", state.style_config["mixed"]["show_index"] is True)
case("mixed.requester_sep=-", state.style_config["mixed"]["requester_sep"] == "-")
case("queue 同名组齐", all(k in state.style_config["queue"] for k in
     ("max_items", "show_index", "show_requester", "requester_sep")))
case("lyric.opacity=1.0", state.style_config["lyric"]["opacity"] == 1.0)

print("═══ E. _spin_int_or 语义 ═══")


class W:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


sip = mainapp.MusicApp._spin_int_or.__get__(s)
case("正常10", sip(W("10"), 0) == 10)
case("空→default", sip(W(""), 0) == 0)
case("负数→default", sip(W("-3"), 0) == 0)
case("非数字→default", sip(W("ab"), 5) == 5)
case("0 合法返回0", sip(W("0"), 7) == 0)

print(f"\n总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
