# -*- coding: utf-8 -*-
"""真控件冒烟：用真 customtkinter 复刻顶栏「版本 + 更新按钮」那一小段，
验证 updater 的显示/隐藏、文案、pack 顺序在真实控件上确实成立（不是只有假对象过）。

用法: ./.venv/Scripts/python.exe -X utf8 _test_upd_ui.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "点歌台拆分"))

import customtkinter as ctk      # noqa: E402
import ui_ctk                    # noqa: E402
import updater                   # noqa: E402
import version                   # noqa: E402

ACCENT = ui_ctk.ACCENT
_font = ui_ctk._font


class App:
    """只用界面回调用得到的那点东西（log/root/两个按钮）。"""

    def __init__(self, root):
        self.root = root
        self.logs = []

    def log(self, m):
        self.logs.append(str(m))


RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  [" + str(extra) + "]"))


root = ctk.CTk()
root.geometry("880x80+1600+1600")     # 屏幕外，跑完就销毁
ctk.set_appearance_mode("dark")

top = ctk.CTkFrame(root, corner_radius=0, height=64)
top.pack(fill="x")
top.pack_propagate(False)

# ── 与 ui_ctk.py 完全一致的一段（改了这里也要同步那边）──
upd_bar = ctk.CTkFrame(top, fg_color="transparent")
upd_bar.pack(side="right")
ctk.CTkLabel(upd_bar, text=version.DISPLAY, font=_font(11)).pack(side="left", padx=(0, 6))
app = App(root)
app.btn_check_update = ctk.CTkButton(
    upd_bar, text="检查更新", width=64, height=26, corner_radius=8,
    fg_color=("white", "#334155"), hover_color=ACCENT, font=_font(11),
    text_color=("#334155", "white"),
    command=lambda: None)
app.btn_check_update.pack(side="left")
app.btn_update_link = ctk.CTkButton(
    upd_bar, text="", width=104, height=26, corner_radius=8,
    fg_color=ACCENT, hover_color=("#1D4ED8", "#2563EB"), font=_font(11, True),
    text_color="white",
    command=lambda: updater.open_setup_download(app))
updater.register_update_link(app)
root.update()

print("═══ 顶栏更新按钮 · 真控件冒烟 ═══")
ck("初始：检查更新可见", app.btn_check_update.winfo_ismapped())
ck("初始：下载按钮不可见", not app.btn_update_link.winfo_ismapped())
w0 = upd_bar.winfo_reqwidth()

updater._set_latest("v1.2.9.3", "https://github.com/x/y/releases/tag/v1.2.9.3", [
    {"name": "diangetai-Setup-v1.2.9.3.exe", "browser_download_url": "https://x/setup.exe"}])
updater._show_link(app, "v1.2.9.3")
root.update()
ck("有新版：下载按钮可见", app.btn_update_link.winfo_ismapped())
ck("有新版：文案带版本号",
   app.btn_update_link.cget("text") == "⬆ 下载 v1.2.9.3", app.btn_update_link.cget("text"))
ck("有新版：检查更新让位", not app.btn_check_update.winfo_ismapped())
w1 = upd_bar.winfo_reqwidth()
# 实测（缩放 2.0）：检查更新占 109 逻辑 px，下载按钮占 150 逻辑 px → 多 41 逻辑 px；
# 顶栏原有内容约 814 逻辑 px，880 的窗口装得下。这里卡 100 物理 px（=50 逻辑）留余量。
ck("占位只多 %d 物理 px（≤100）" % (w1 - w0), w1 - w0 <= 100, (w0, w1))

# 点下去真的走 open_setup_download（不真开浏览器，只打桩 webbrowser）
opened = []
_saved = updater.webbrowser.open
updater.webbrowser.open = lambda url, **kw: (opened.append(url), True)[1]
try:
    app.btn_update_link.invoke()
finally:
    updater.webbrowser.open = _saved
root.update()
ck("点按钮 → 默认浏览器打开 setup 直链", opened == ["https://x/setup.exe"], opened)
ck("日志有交代", any("默认浏览器" in m for m in app.logs), app.logs[-1:])

updater._hide_link(app)
root.update()
ck("无新版后恢复：检查更新回来了", app.btn_check_update.winfo_ismapped())
ck("无新版后恢复：下载按钮消失", not app.btn_update_link.winfo_ismapped())

root.destroy()

bad = [n for n, ok in RESULTS if not ok]
print("\n═══ 结果: %d/%d 通过 ═══" % (len(RESULTS) - len(bad), len(RESULTS)))
if bad:
    for n in bad:
        print("  FAILED: " + n)
sys.exit(1 if bad else 0)
