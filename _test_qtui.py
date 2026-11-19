# -*- coding: utf-8 -*-
"""R-15 界面冒烟：真建 Qt 窗口，逐页切换 + 截图。"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
from PySide6.QtWidgets import QApplication
import qtapp, state, version

class FakeRoot:
    def __init__(self): self.cbs = []
    def after(self, ms, fn):
        try: fn()
        except Exception: pass
        return {"cancelled": False}
    def after_cancel(self, h): pass

class FakeApp:
    def __init__(self):
        self.config = {"room_id": "1968146663", "bili_cookie": "", "qqmusic_path": "",
                       "local_songs_dir": "", "audio_quality": "flac"}
        self.root = FakeRoot()
        self.logs = []
    def get_volume(self): return 0.8
    def log(self, m): self.logs.append(str(m))
    def __getattr__(self, n): return lambda *a, **k: None

def main():
    app = qtapp.make_app()   # 走真实启动路径（会设主题色 #0067C0）
    win = qtapp.MainWindow()
    fake = FakeApp()
    qtapp.build(fake, win)
    win.show()
    try:
        win.navigationInterface.setExpandWidth(210)
        win.navigationInterface.expand(useAni=False)
    except Exception:
        pass
    win.move(20, 10)
    app.processEvents()
    pages = fake.pages
    for k, p in pages.items():
        win.switchTo(p)
        app.processEvents()
        print("page", k, "ok", p.objectName())
    # R-16：浅色 / 深色各截一张，确认整窗跟着变
    import qtapp as _q
    from PIL import ImageGrab
    win.switchTo(pages["live"])
    _q.apply_theme("light")
    app.processEvents()
    time.sleep(0.8)
    print("theme now =", _q.current_theme_name())
    win.grab().save("_qt_light.png")
    try:
        from qfluentwidgets import qconfig as _qc
        print("accent =", _qc.themeColor.name())
    except Exception:
        pass
    _q.apply_theme("dark")
    app.processEvents()
    time.sleep(0.8)
    print("theme now =", _q.current_theme_name())
    win.grab().save("_qt_dark.png")
    _q.apply_theme("light")
    app.processEvents()
    ImageGrab.grab().save("_qt_live.png")
    win.switchTo(pages["overlay"])
    app.processEvents()
    time.sleep(1.0)
    ImageGrab.grab().save("_qt_ui.png")
    print("SHOT_OK", version.DISPLAY)
    win.closeAll() if hasattr(win, "closeAll") else win.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
