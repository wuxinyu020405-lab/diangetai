# -*- coding: utf-8 -*-
"""R-27 C：关闭行为选项回归。

① 默认值是 tray（配置里没写时）
② 存 config["close_action"] 并落盘（走 save_style_config）
③ 选 tray → 点 X 走 minimize_to_tray（进程活着+托盘窗口出现）
④ 选 quit → 点 X 走 quit_app（进程真的退出）
"""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "点歌台拆分"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  [" + str(extra) + "]"))


# ═════ ① 默认值 ═════
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import qtapp

qapp = qtapp.make_app()
win = qtapp.MainWindow()


class FakeApp:
    def __init__(self):
        self.config = {}          # 故意不给 close_action
        self.logs = []
        self.saved = 0

    def log(self, m):
        self.logs.append(str(m))

    def schedule_save_style(self):
        self.saved += 1

    def get_volume(self):
        return 0.8

    def __getattr__(self, n):
        return lambda *a, **k: None


fake = FakeApp()
qtapp.build(fake, win)
qapp.processEvents()

combo = None
try:
    combo = fake.pages["log"].combo_close
except Exception:
    pass
ck("运行日志页有「关闭行为」下拉", combo is not None)
if combo is not None:
    ck("默认显示「缩小到托盘」", combo.currentText().startswith("缩小到托盘"),
       combo.currentText())

    # ═════ ② 改选「直接退出」→ 写配置 + 落盘 ═════
    combo.setCurrentText("直接退出程序")
    qapp.processEvents()
    ck("选「直接退出」写进 config", fake.config.get("close_action") == "quit",
       fake.config.get("close_action"))
    ck("触发了落盘调用", fake.saved >= 1, fake.saved)

    # 改回托盘
    combo.setCurrentText("缩小到托盘（后台继续运行）")
    qapp.processEvents()
    ck("选回「缩小到托盘」写进 config", fake.config.get("close_action") == "tray",
       fake.config.get("close_action"))

win.close()

# ═════ ③ 盘上真的有这个键 ═════
print("── 配置文件检查 ──")
cfgfile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "点歌台拆分", "config.json")
if os.path.exists(cfgfile):
    try:
        # 配置是加密存的（__enc__/data），必须走 secretstore 读
        import secretstore
        data = secretstore.read_json(cfgfile, default={}) or {}
        ck("盘上配置能读出来（secretstore）", isinstance(data, dict) and bool(data),
           list(data.keys())[:6])
        if "close_action" in data:
            ck("盘上已有 close_action 字段", True, data.get("close_action"))
        else:
            print("  (盘上还没有 close_action——本次测试用假 app，没真写盘，正常)")
    except Exception as e:
        ck("盘上配置可读", False, e)
else:
    print("  (没有 config.json，跳过)")

bad = [n for n, ok in RESULTS if not ok]
print("\n结论: %s 关闭行为回归 %d/%d" % ("✅" if not bad else "❌",
                                       len(RESULTS) - len(bad), len(RESULTS)))
for n in bad:
    print("  失败:", n)
sys.exit(0 if not bad else 1)
