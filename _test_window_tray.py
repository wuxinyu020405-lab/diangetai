# -*- coding: utf-8 -*-
"""R-26 三项修复的针对性回归。

① 托盘：pystray 的 ChangeWindowMessageFilterEx 补丁生效，托盘能真起来
② 降级路径：Qt 窗口补齐 iconify/withdraw/deiconify 等 tk 名字
③ 默认窗口：居中 + 高度=最小高度；切页动画已关闭

用法: ./.venv\Scripts\python.exe -X utf8 _test_window_tray.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  [" + str(extra) + "]"))


# ═════════ ① 托盘补丁 ═════════
print("── ① 托盘 ──")


class _FakeApp:
    """tray.Tray 只用到 app.log。"""
    def __init__(self):
        self.logs = []

    def log(self, m):
        self.logs.append(str(m))


import tray as tray_mod

# R-28：托盘判定改为"真注册进 Shell 才算起"（NIM_ADD 返回值说话）。
# 沙箱/受限环境下 NIM_ADD 被 UIPI 拒（WinError 5）→ start() 必须 False 并记
# 原因；真桌面成功 → start()=True 且 _added_ok。老代码不看返回值一律 True，
# 正是"窗口藏了+托盘没有+进程还在"幽灵状态的源头。两种环境都按上面的断言走。
app_fake = _FakeApp()
t = tray_mod.Tray(app_fake)
started = t.start()
logs = "\n".join(app_fake.logs)
if started:
    ck("成功路径：NIM_ADD 真注册后才放行（_added_ok）",
       getattr(t, "_added_ok", False) is True, logs)
else:
    ck("失败路径：日志写明托盘未就绪原因", "托盘未就绪" in logs, logs)
    ck("失败路径：icon 已回收（不留幽灵线程对象）", t.icon is None)
time.sleep(0.5)
t.stop()

# ═════════ ② Qt 窗口 tk 兼容方法 ═════════
print("── ② 降级路径 ──")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import qtapp

need = ["iconify", "withdraw", "deiconify", "lift", "focus_force",
        "wm_attributes", "attributes", "protocol", "state"]
missing = [n for n in need if not hasattr(qtapp.MainWindow, n)]
ck("Qt 窗口补齐了 tk 名字", not missing, missing)

qapp = qtapp.make_app()
win = qtapp.MainWindow()
for name in ("iconify", "withdraw", "deiconify", "lift", "focus_force"):
    try:
        getattr(win, name)()
        ck("调用 %s() 不抛异常" % name, True)
    except Exception as e:
        ck("调用 %s() 不抛异常" % name, False, "%s: %s" % (type(e).__name__, e))
win.show()

# ═════════ ③ 默认窗口 ═════════
print("── ③ 默认窗口 ──")
ms = win.minimumSize()
ck("窗口高度 = 最小高度", win.height() == ms.height(),
   (win.height(), ms.height()))
ck("窗口宽度 = 最小宽度", win.width() == ms.width(), (win.width(), ms.width()))

qtapp._center_window(win)
qapp.processEvents()
scr = qapp.primaryScreen().availableGeometry()
fg = win.frameGeometry()
dx = abs(fg.center().x() - scr.center().x())
dy = abs(fg.center().y() - scr.center().y())
ck("窗口水平居中（偏差<40px）", dx < 40, dx)
ck("窗口垂直居中（偏差<40px）", dy < 40, dy)

# 动画开关
try:
    enabled = win.stackedWidget.isAnimationEnabled()
except Exception:
    enabled = None
ck("切页动画已关闭", enabled is False, enabled)

win.close()
bad = [n for n, okk in RESULTS if not okk]
print("\n结论: %s R-26 回归 %d/%d" % ("✅" if not bad else "❌",
                                     len(RESULTS) - len(bad), len(RESULTS)))
for n in bad:
    print("  失败:", n)
# Qt 窗口/托盘的析构在无显示环境下可能段错误（0xC0000005），结论已打印，
# 直接硬退，免得退出码被误读成"测试失败"。
sys.stdout.flush()
os._exit(0 if not bad else 1)
