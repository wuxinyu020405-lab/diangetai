# -*- coding: utf-8 -*-
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "点歌台拆分"))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QPushButton
import qtapp


class FakeRoot:
    def after(self, m, fn): return {"cancelled": False}
    def after_cancel(self, h): pass


class FakeApp:
    def __init__(self):
        self.config = {"room_id": "1968146663", "ui_theme": "light"}
        self.root = FakeRoot()
        self.copied = []
    def get_volume(self): return 0.8
    def log(self, m): pass
    def copy_to_clipboard(self, text):
        self.copied.append(text)
    def __getattr__(self, n): return lambda *a, **k: None

app = qtapp.make_app()
win = qtapp.MainWindow()
fake = FakeApp()
qtapp.build(fake, win)
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.show()
for _ in range(3):
    app.processEvents(); time.sleep(0.1)
overlay = fake.pages["overlay"]
# 只认地址区那几个：tooltip 以「复制 」开头（页签标题也是 QPushButton，别混）
btns = [b for b in overlay.findChildren(QPushButton) if b.toolTip().startswith("复制 ")]
print("找到复制按钮:", [(b.text(), b.toolTip()) for b in btns])
ok = 0
for b in btns:
    fake.copied.clear()
    b.click()
    app.processEvents()
    ok += 1 if fake.copied else 0
    print(b.text(), "->", fake.copied)
print("复制按钮数量:", len(btns), "| 点得响的:", ok)
win.close(); app.processEvents()
