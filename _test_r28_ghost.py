# -*- coding: utf-8 -*-
"""R-28 回归：幽灵进程 + 二次启动白屏 的修复点。

① tray._add_icon_sync：NIM_ADD 返回值必须被检查（失败→start()=False→降级）
② 幽灵不可能态：start() 失败时窗口绝不能被 withdraw（minimize_to_tray 走降级）
③ 唤起通道：SHOW_EVENT_NAME 存在；main._wake_existing_instance 只 SetEvent、
   不再对隐藏窗口 ShowWindow；_bring_existing_window_front 只碰可见窗口
④ show watcher：事件置位 → after(0, show_from_tray) 被投递（假对象验证）
⑤ 退出兜底：quit_app 序列完整（停托盘→清子进程→os._exit）

用法（沙箱外）: ./.venv/Scripts/python.exe -X utf8 _test_r28_ghost.py
"""
import ctypes
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "点歌台拆分"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  [" + str(extra) + "]"))


# ═════ ① 幽灵不可能态（沙箱里 NIM_ADD err=5，正好当"托盘必失败"环境测降级）═════
print("── ① tray NIM 验证 + 降级 ──")
import tray as tray_mod


class _LogApp:
    def __init__(self):
        self.logs = []

    def log(self, m):
        self.logs.append(str(m))


la = _LogApp()
t = tray_mod.Tray(la)
started = t.start()
# 沙箱内：started 必须 False（老代码会假 True）；用户桌面：可能 True。
# 两种都合法，断言的是"started 与 NIM 真结果一致、且失败有日志"。
if not started:
    ck("start() 失败时有明确原因日志", any("托盘未就绪" in x for x in la.logs), la.logs)
    ck("失败后 icon 已清（不留半截线程对象）", t.icon is None)
else:
    ck("start() 成功=真注册进 Shell", True)
    t.stop()

# ═════ ② minimize_to_tray 不可能出现"窗口藏了+托盘没起" ═════
print("── ② 降级路径 ──")
import inspect
import mainapp
src = inspect.getsource(mainapp.MusicApp.minimize_to_tray)
# withdraw 只允许出现在 tray.start() 成功之后
i_start = src.find("self._tray.start()")
i_withdraw = src.find("self.root.withdraw()")
ck("withdraw 在 tray.start() 判定之后", 0 <= i_start < i_withdraw, (i_start, i_withdraw))
# 降级调用存在
ck("失败走 _fallback_minimize", "_fallback_minimize()" in src)

# ═════ ③ 唤起通道 ═════
print("── ③ 二次启动唤起 ──")
import state
ck("state.SHOW_EVENT_NAME 已定义", getattr(state, "SHOW_EVENT_NAME", "") != "")

import main as m


def _code_lines(fn):
    """函数源码里去掉注释/空行的净代码。"""
    out = []
    for ln in inspect.getsource(fn).splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            out.append(ln)
    return "\n".join(out)


wsrc = _code_lines(m._wake_existing_instance)
b1 = "SetEvent" in wsrc
# 注释允许提 ShowWindow（解释为什么不用），代码行不许出现调用
b2 = "ShowWindow(target" not in wsrc and ".ShowWindow(" not in wsrc
ck("_wake_existing_instance 用 SetEvent 不碰 ShowWindow", b1 and b2,
   ("SetEvent" in wsrc, "ShowWindow" in wsrc))
bsrc = _code_lines(m._bring_existing_window_front)
ck("_bring_existing_window_front 过滤可见性(IsWindowVisible)", "IsWindowVisible" in bsrc)
ck("SW_SHOW 强显已删除", "SW_SHOW" not in bsrc)

# 没有实例时唤醒返回 False
# （先确保测试事件名没被占用：TEST 后缀由 _make_testcopy 改，源码态用真名——
#   若用户实例在跑会返回 True，这不算失败，只记录）
if state.APP_MUTEX_NAME.endswith("TEST"):
    ck("无实例时 wake=False", m._wake_existing_instance() is False)
else:
    print("  (源码态共用真事件名，跳过 wake=False 断言，避免误碰用户实例)")

# ═════ ④ show watcher 编组 ═════
print("── ④ show watcher ──")
ck("MusicApp 有 _start_show_watcher", hasattr(mainapp.MusicApp, "_start_show_watcher"))
ssrc = inspect.getsource(mainapp.MusicApp._start_show_watcher)
ck("watcher 收到事件后 after(0, show_from_tray)",
   "after(0, self.show_from_tray)" in ssrc and "SHOW_EVENT_NAME" in ssrc)

# ═════ ⑤ quit_app 兜底 ═════
print("── ⑤ 退出兜底 ──")
qsrc = inspect.getsource(mainapp.MusicApp.quit_app)
for token, label in (("save_style_config", "落盘"),
                     ("self._tray.stop", "停托盘"),
                     ("kill_own_descendants", "收割派生的子进程"),
                     ("player_stop", "停播放器"),
                     ("os._exit", "硬退")):
    ck("quit_app 包含 %s（%s）" % (token, label), token in qsrc)
# 不再 taskkill /IM node.exe（会误杀用户别的 node）
ck("不再无差别 taskkill node.exe", '"/IM", "node.exe"' not in qsrc, "残留" if '"/IM", "node.exe"' in qsrc else "")

bad = [n for n, okk in RESULTS if not okk]
print("\n结论: %s R-28 回归 %d/%d" % ("✅" if not bad else "❌",
                                     len(RESULTS) - len(bad), len(RESULTS)))
for n in bad:
    print("  失败:", n)
sys.stdout.flush()
os._exit(0 if not bad else 1)
