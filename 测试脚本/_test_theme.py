# -*- coding: utf-8 -*-
"""R-16 深色模式自测：起真窗口，浅/深各截一张真屏图 + 断言。"""
import os, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "点歌台拆分"))

from PySide6.QtCore import Qt
from PIL import Image, ImageGrab
import qtapp, state, version


class FakeRoot:
    def __init__(self):
        self.cbs = []

    def after(self, ms, fn):
        try:
            fn()
        except Exception:
            pass
        return {"cancelled": False}

    def after_cancel(self, h):
        pass


class FakeApp:
    def __init__(self):
        self.config = {"room_id": "1968146663", "bili_cookie": "", "qqmusic_path": "",
                       "local_songs_dir": "", "audio_quality": "flac"}
        self.root = FakeRoot()
        self.logs = []

    def get_volume(self):
        return 0.8

    def log(self, m):
        self.logs.append(str(m))

    def __getattr__(self, n):
        return lambda *a, **k: None


fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not ok:
        fails.append(name)


def mean_lum(img):
    img = img.convert("L").resize((80, 60))
    px = list(img.getdata())
    return sum(px) / float(len(px))


def shot(win, path):
    """用控件自己渲染出的位图截图（R-17 之后窗口不透明，和真屏一致）。
    这样不抢用户屏幕，也不怕别的窗口挡在前面。"""
    pm = win.grab()
    pm.save(path)
    return Image.open(path).convert("RGB")


def main():
    app = qtapp.make_app()
    win = qtapp.MainWindow()
    fake = FakeApp()
    qtapp.build(fake, win)

    check("标题栏有明暗切换按钮", getattr(win, "btn_theme", None) is not None)

    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)  # 不弹到用户屏幕上
    win.show()
    win.move(40, 40)
    app.processEvents()
    time.sleep(0.8)
    app.processEvents()

    for name in ("light", "dark"):
        qtapp.apply_theme(name)
        for _ in range(5):
            app.processEvents()
            time.sleep(0.12)
        img = shot(win, "_qt_theme_%s.png" % name)
        L = mean_lum(img)
        print("theme=%s 偏好=%s 实际=%s 平均亮度=%.0f  %s"
              % (name, qtapp.current_theme_name(),
                 "深色" if qtapp.isDarkTheme() else "浅色", L, path_of(name)))
        if name == "light":
            check("浅色整体是亮的", L > 170, "亮度 %.0f" % L)
        if name == "dark":
            check("深色整体是暗的", L < 120, "亮度 %.0f" % L)

    # 点按钮：浅 -> 深，并记住
    qtapp.apply_theme("light")
    app.processEvents()
    win.toggle_theme()
    app.processEvents()
    check("点一下从浅色切到深色", qtapp.current_theme_name() == "dark",
          qtapp.current_theme_name())
    check("偏好写进 config['ui_theme']", fake.config.get("ui_theme") == "dark",
          fake.config.get("ui_theme"))
    tip = win.btn_theme.toolTip() if win.btn_theme else ""
    check("按钮提示显示当前是深色", "深色" in tip, tip)

    win.toggle_theme()
    app.processEvents()
    check("再点一下回浅色", qtapp.current_theme_name() == "light",
          qtapp.current_theme_name())

    # 跟随系统：偏好记成 auto，而不是被系统解析出的明暗
    win.set_theme("auto")
    app.processEvents()
    check("能选回「跟随系统」", qtapp.current_theme_name() == "auto",
          qtapp.current_theme_name())
    check("跟随系统也写进配置", fake.config.get("ui_theme") == "auto",
          fake.config.get("ui_theme"))
    check("右键菜单可用", hasattr(win, "show_theme_menu"))

    # 模拟重启：先归 auto，再按配置还原成深色
    fake.config["ui_theme"] = "dark"
    qtapp.apply_theme("auto")
    app.processEvents()
    qtapp.apply_theme(fake.config.get("ui_theme") or "auto")
    app.processEvents()
    check("重启后照上次选择还原", qtapp.current_theme_name() == "dark",
          qtapp.current_theme_name())

    # 深色下逐页截图（看有没有白底黑字 / 黑底黑字）
    for k, p in fake.pages.items():
        win.switchTo(p)
        app.processEvents()
        time.sleep(0.4)
        shot(win, "_qt_dark_page_%s.png" % k)
        print("dark page", k, "ok")

    qtapp.apply_theme("light")
    app.processEvents()
    check("深色回浅色不崩", qtapp.current_theme_name() == "light",
          qtapp.current_theme_name())

    win.close()
    app.processEvents()
    print("SHOTS", ", ".join(sorted(f for f in os.listdir(HERE) if f.startswith("_qt_theme")
                                    or f.startswith("_qt_dark_page"))))
    if fails:
        print("RESULT FAIL", len(fails), fails)
        return 1
    print("RESULT PASS 全部通过")
    return 0


def path_of(name):
    return "_qt_theme_%s.png" % name


if __name__ == "__main__":
    sys.exit(main())
