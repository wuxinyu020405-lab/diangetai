# -*- coding: utf-8 -*-
"""R-18 界面字号档位自测：逐档截图 + 断言字号真的变。"""
import os, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "点歌台拆分"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
import qtapp


class FakeRoot:
    def after(self, m, fn): return {"cancelled": False}
    def after_cancel(self, h): pass


class FakeApp:
    def __init__(self, cfg=None):
        self.config = dict(cfg or {"room_id": "1968146663", "ui_theme": "light"})
        self.root = FakeRoot()
        self.logs = []
    def get_volume(self): return 0.8
    def log(self, m): self.logs.append(str(m))
    def __getattr__(self, n): return lambda *a, **k: None


fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not ok:
        fails.append(name)


def label_px(win, text):
    for lb in win.findChildren(QLabel):
        try:
            if lb.text() == text:
                f = lb.font()
                return f.pixelSize() if f.pixelSize() > 0 else int(round(f.pointSizeF() * 96 / 72))
        except Exception:
            pass
    return None


def build(cfg):
    win = qtapp.MainWindow()
    fake = FakeApp(cfg)
    qtapp.build(fake, win)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)  # 不弹到用户屏幕上
    win.show()
    for _ in range(4):
        qtapp_app.processEvents()
        time.sleep(0.08)
    return win, fake


qtapp_app = qtapp.make_app()

win, fake = build({"room_id": "1968146663", "ui_theme": "light"})
check("标题栏有字号按钮", getattr(win, "btn_scale", None) is not None)
check("有选档位的菜单入口", hasattr(win, "show_scale_menu"))
check("默认档位是标准", qtapp.current_ui_scale_key() == "normal", qtapp.current_ui_scale_key())

p0 = label_px(win, "正在播放")
print("标准档「正在播放」字号 =", p0)
check("标准档字号正常", p0 and p0 > 8, p0)
win.grab().save("_scale_normal.png")

ratios = dict(qtapp._UI_SCALE_VALUE)
expect = {"small": round(p0 * ratios["small"]), "large": round(p0 * ratios["large"]),
          "xlarge": round(p0 * ratios["xlarge"])}
for key in ("small", "large", "xlarge"):
    win.set_ui_scale(key)
    for _ in range(2):
        qtapp_app.processEvents()
    px = label_px(win, "正在播放")
    print("档位 %s -> 字号 %s（期望 %s）" % (key, px, expect[key]))
    check("档位 %s 字号真的变了" % key, px == expect[key], px)
    check("档位 %s 写进配置" % key, fake.config.get("ui_scale") == key, fake.config.get("ui_scale"))
    win.grab().save("_scale_%s.png" % key)

# 来回切不能越滚越大
win.set_ui_scale("normal")
qtapp_app.processEvents()
check("切回标准 = 原字号", label_px(win, "正在播放") == p0, label_px(win, "正在播放"))
for _ in range(4):
    win.set_ui_scale("xlarge")
    win.set_ui_scale("normal")
qtapp_app.processEvents()
check("来回切 4 次不累加", label_px(win, "正在播放") == p0, label_px(win, "正在播放"))

# 按钮提示随档位变
win.set_ui_scale("large")
qtapp_app.processEvents()
tip = win.btn_scale.toolTip() if win.btn_scale else ""
check("按钮提示显示当前档位", "大" in tip, tip)
win.close()
qtapp_app.processEvents()

# 模拟重启：配置里存 large，重建后应直接是大号
win2, _fake2 = build({"room_id": "1968146663", "ui_theme": "light", "ui_scale": "large"})
px2 = label_px(win2, "正在播放")
print("重启后「正在播放」字号 =", px2, "（标准是", p0, "）")
check("重启后按记忆还原档位", qtapp.current_ui_scale_key() == "large",
      qtapp.current_ui_scale_key())
check("重启后字号确实是大的", px2 == round(p0 * ratios["large"]), px2)
win2.grab().save("_scale_restart_large.png")
win2.close()
qtapp_app.processEvents()

print("RESULT", "FAIL " + str(fails) if fails else "PASS 全部通过")
sys.exit(1 if fails else 0)
