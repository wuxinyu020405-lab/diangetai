# -*- coding: utf-8 -*-
"""真控件冒烟（Qt 版，R-22）：在真 PySide6 窗口上验证更新入口的接线。

R-15 把界面换成 Qt 后，更新入口不再是顶栏「检查更新 / ⬆下载」抢同一个位置，
而是侧栏「关于」对话框里的两个按钮。旧的 customtkinter 冒烟脚本（复刻旧顶栏）
随 ui_ctk.py 一起作废，这里按新界面重写。

用法: ./.venv/Scripts/python.exe -X utf8 _test_upd_ui.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "点歌台拆分"))

from PySide6.QtCore import Qt          # noqa: E402
import qtapp                           # noqa: E402
import updater                         # noqa: E402
import version                         # noqa: E402


class FakeApp:
    """界面回调用得到的那点东西（config / log / 音量）。"""

    def __init__(self, root):
        self.root = root
        self.config = {"room_id": "1968146663", "ui_theme": "light"}
        self.logs = []

    def log(self, m):
        self.logs.append(str(m))

    def get_volume(self):
        return 0.8

    def schedule_save_style(self):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  [" + str(extra) + "]"))


app = qtapp.make_app()
win = qtapp.MainWindow()
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)   # 不弹到用户屏幕上
fake = FakeApp(win)
qtapp.build(fake, win)
app.processEvents()

print("═══ 更新入口 · 真控件冒烟（Qt）═══")

# ① 新界面没有顶栏那两个按钮；register_update_link 对 None 按钮必须是安全的空操作
ck("新界面顶栏没有更新按钮（两个都 None）",
   fake.btn_check_update is None and fake.btn_update_link is None)
ck("没有按钮时 register_update_link 不炸", updater._link.get("app") is fake)

# ② 「关于」：标题是版本号，两个按钮各就各位
dlg = qtapp.AboutDialog(win)
app.processEvents()
ck("「关于」标题带版本号", version.DISPLAY in dlg.titleLabel.text(), dlg.titleLabel.text())
ck("有「检查更新」按钮", dlg.yesButton.text() == "检查更新", dlg.yesButton.text())
ck("有「下载新版」按钮", dlg.dlButton.text() == "下载新版", dlg.dlButton.text())

# ③ 已经查到新版：再打开「关于」时内容里会说清楚
updater._set_latest("v1.2.9.3", "https://github.com/x/y/releases/tag/v1.2.9.3",
                    [{"name": "diangetai-Setup-v1.2.9.3.exe",
                      "browser_download_url": "https://x/setup.exe"}])
dlg._refresh()
app.processEvents()
ck("有新版时「关于」里提到版本号", "v1.2.9.3" in dlg.contentLabel.text(),
   dlg.contentLabel.text())

# ④ 点「下载新版」→ 走 updater.open_setup_download（打桩，不真开浏览器）
hits = []
opened = []
_orig_dl = updater.open_setup_download


def _fake_dl(app=None):
    hits.append(app)
    opened.append(updater.latest_info().get("setup_url"))
    return True


updater.open_setup_download = _fake_dl
try:
    dlg.dlButton.click()
    app.processEvents()
finally:
    updater.open_setup_download = _orig_dl
ck("点「下载新版」→ 调 open_setup_download", hits == [fake], hits)
ck("下载地址就是 Setup 直链", opened == ["https://x/setup.exe"], opened)

# ⑤ 点「检查更新」→ 走 manual_check
checks = []
_orig_chk = updater.manual_check
updater.manual_check = lambda app=None: checks.append(app)
try:
    dlg.yesButton.click()
    app.processEvents()
finally:
    updater.manual_check = _orig_chk
ck("点「检查更新」→ 调 manual_check", checks == [fake], checks)
dlg.deleteLater()

# ⑥ 没查到版本时打开「关于」：默认说明；这时点下载只写日志、不开浏览器
updater._latest.update({"tag": None, "release_url": "", "setup_url": "", "direct": False})
dlg2 = qtapp.AboutDialog(win)
app.processEvents()
ck("无新版时是默认说明", "点「检查更新」" in dlg2.contentLabel.text(),
   dlg2.contentLabel.text())
opened2 = []
_saved_web = updater.webbrowser.open
updater.webbrowser.open = lambda url, **kw: (opened2.append(url), True)[1]
try:
    dlg2.dlButton.click()
    app.processEvents()
finally:
    updater.webbrowser.open = _saved_web
ck("没版本信息就点下载：不开浏览器、只提示",
   opened2 == [] and any("还没有" in m for m in fake.logs), (opened2, fake.logs[-1:]))
dlg2.deleteLater()

win.deleteLater()
app.processEvents()

bad = [n for n, ok in RESULTS if not ok]
print("\n═══ 结果: %d/%d 通过 ═══" % (len(RESULTS) - len(bad), len(RESULTS)))
if bad:
    for n in bad:
        print("  FAILED: " + n)
sys.exit(1 if bad else 0)
