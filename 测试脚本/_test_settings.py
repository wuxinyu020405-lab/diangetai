# -*- coding: utf-8 -*-
"""R-19 设置项对照自测：逐项找控件 + 真实改一次看有没有写进配置。"""
import os, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "点歌台拆分"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSpinBox, QDialog
import qtapp
import fontlib


class FakeRoot:
    def after(self, m, fn):
        try:
            fn()
        except Exception:
            pass
        return {"cancelled": False}
    def after_cancel(self, h): pass


class FakeApp:
    def __init__(self):
        self.config = {"room_id": "1968146663", "ui_theme": "light"}
        self.root = FakeRoot()
        self.calls = []
    def get_volume(self): return 0.8
    def log(self, m): pass
    def update_mixed(self, k, v): self.calls.append(("mixed", k, v))
    def update_lyric(self, k, v): self.calls.append(("lyric", k, v))
    def update_playing(self, k, v): self.calls.append(("playing", k, v))
    def update_queue(self, k, v): self.calls.append(("queue", k, v))
    def update_lyric_align(self, _=None): pass
    def update_effect(self, _=None): pass
    def update_queue_align(self, _=None): pass
    def __getattr__(self, n): return lambda *a, **k: None


CHECKLIST = {
    "live": ["正在播放", "快速加歌", "点歌队列", "暂停播放", "切歌"],
    "audio": ["首选音质", "点歌音量", "点歌时暂停谁的 BGM", "客户端路径",
              "最多保留文件数", "最多占用 (MB)", "打开本地曲库文件夹"],
    "account": ["房间号", "登录 B站", "重连弹幕", "刷新状态", "扫码登录 QQ音乐",
                "启用发弹幕", "每分钟上限", "最小间隔（秒）", "刷新发送器", "测试发送"],
    "log": ["OBS 源"],
}

TAB_CHECKS = {
    "mixTab": ["正在播放", "实时歌词", "点歌列表", "滚动效果", "对齐",
               "上方已播行数", "下方未播行数", "歌词字号", "歌词颜色", "歌词加粗",
               "字号", "颜色", "显示图标", "显示文字前缀", "加粗",
               "最多显示条数（0=不限）", "单行最长字数（0=不限）", "显示序号",
               "显示请求者", "请求者分隔符", "字体"],
    "lyricTab": ["字体", "字号", "透明度系数（100=原样）", "行间距（%）", "歌词颜色",
                 "字体加粗", "对齐", "滚动效果", "上方已播行数", "下方未播行数",
                 "纯音乐提示"],
    "playingTab": ["字体", "颜色", "字号", "显示文字前缀", "加粗"],
    "queueTab": ["字体", "颜色", "字号", "对齐", "最多显示条数（0=不限）",
                 "单行最长字数", "显示序号", "显示请求者", "加粗", "请求者分隔符"],
}

fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not ok:
        fails.append(name)


def texts_in(container):
    out = set()
    for lb in container.findChildren(QLabel):
        try:
            if lb.text():
                out.add(lb.text())
        except Exception:
            pass
    for b in container.findChildren(QWidget):
        try:
            t = b.text()
            if isinstance(t, str) and t:
                out.add(t)
        except Exception:
            pass
    return out


def has_text(have, want):
    return any(want in t for t in have)


app = qtapp.make_app()
win = qtapp.MainWindow()
fake = FakeApp()
qtapp.build(fake, win)
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.show()
for _ in range(4):
    app.processEvents(); time.sleep(0.08)

pages = fake.pages
for route, labels in CHECKLIST.items():
    page = pages.get(route)
    if page is None:
        check("页面存在 " + route, False)
        continue
    have = texts_in(page)
    missing = [t for t in labels if not has_text(have, t)]
    check("页面 %s 设置齐全" % route, not missing,
          "缺：" + str(missing) if missing else "%d 项" % len(labels))

overlay = pages["overlay"]
tabs = {}
for w in overlay.findChildren(QWidget):
    obj = w.objectName() or ""
    if obj in TAB_CHECKS:
        tabs.setdefault(obj, w)
for obj, labels in TAB_CHECKS.items():
    tab = tabs.get(obj)
    if tab is None:
        check("子页签存在 " + obj, False)
        continue
    have = texts_in(tab)
    missing = [t for t in labels if not has_text(have, t)]
    check("子页签 %s 设置齐全" % obj, not missing,
          "缺：" + str(missing) if missing else "%d 项" % len(labels))

pickers = overlay.findChildren(qtapp._FontPicker)
check("字体选择器共 6 个（综合3+歌词1+播放1+列表1）", len(pickers) == 6, len(pickers))
by_tab = {}
for p in pickers:
    node = p
    while node is not None and (node.objectName() or "") not in TAB_CHECKS:
        node = node.parentWidget()
    if node is not None:
        by_tab.setdefault(node.objectName(), []).append(p)

expect = {"mixTab": [("mixed", "font_lyric"), ("mixed", "font_playing"), ("mixed", "font_queue")],
          "lyricTab": [("lyric", "font")],
          "playingTab": [("playing", "font")],
          "queueTab": [("queue", "font")]}
for tab_name, pairs in expect.items():
    got = by_tab.get(tab_name, [])
    check("子页签 %s 字体行数量" % tab_name, len(got) == len(pairs), len(got))
    for picker, (sect, key) in zip(got, pairs):
        fake.calls.clear()
        picker.combo.setCurrentText(fontlib.CURATED_FONTS[1][1])
        for _ in range(2):
            app.processEvents()
        hit = [c for c in fake.calls if c[0] == sect and c[1] == key]
        ok = bool(hit) and hit[-1][2] == "'SimHei', sans-serif"
        check("选字体写入 %s.%s" % (sect, key), ok, hit[-1] if hit else fake.calls)


class _FakeDialog(QDialog):
    text = "站酷快乐体"

    def __init__(self, *a, **k):
        super().__init__(k.get("parent"))
        self.textLayout = QVBoxLayout(self)

    def exec(self):
        for i in range(self.textLayout.count()):
            w = self.textLayout.itemAt(i).widget()
            if w is not None:
                w.setText(_FakeDialog.text)
        return 1


_real_dialog = qtapp.Dialog
qtapp.Dialog = _FakeDialog
try:
    p = by_tab["mixTab"][0]
    fake.calls.clear()
    p._ask_custom()
    for _ in range(2):
        app.processEvents()
    hit = [c for c in fake.calls if c[0] == "mixed" and c[1] == "font_lyric"]
    check("自定义字体写进 mixed.font_lyric", bool(hit), hit)
    check("自定义字体补了 sans-serif 兜底",
          bool(hit) and "sans-serif" in str(hit[-1][2]), hit[-1] if hit else "")
finally:
    qtapp.Dialog = _real_dialog

spin = None
for sp in tabs["lyricTab"].findChildren(QSpinBox):
    spin = spin or sp
fake.calls.clear()
if spin is not None:
    spin.setValue(3)
    app.processEvents()
hit = [c for c in fake.calls if c[0] == "lyric" and c[1] in ("lines_prev", "lines_next")]
check("改歌词行数写进配置", bool(hit), hit)

print("RESULT", "FAIL " + str(fails) if fails else "PASS 全部通过")
sys.exit(1 if fails else 0)
