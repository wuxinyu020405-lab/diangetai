# -*- coding: utf-8 -*-
"""模拟主程序场景：Tk 主循环 + 后台线程跑 pywebview 登录，验证是否稳定。"""
import sys
import threading
import time
import tkinter as tk

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import browserlogin

root = tk.Tk()
root.withdraw()
logs = []


class FakeApp:
    def __init__(self):
        self.root = root

    def log(self, m):
        logs.append(str(m))
        print("   [log]", str(m)[:100])


app = FakeApp()

print("═══ Tk 主循环存在时，跑一次 pywebview 登录 ═══")
browserlogin.bilibili_auto_login(app)

# 让 Tk 跑一会儿（模拟真实主循环）
deadline = time.time() + 12
while time.time() < deadline:
    try:
        root.update()
    except Exception:
        break
    time.sleep(0.1)

print(f"\n日志 {len(logs)} 条")
print("═══ 关闭 Tk ═══")
try:
    root.destroy()
    print("   Tk 已销毁")
except Exception as e:
    print("   Tk 销毁异常:", e)

print("\n如果这行能打印，说明运行期没有问题")
print("（随后可能看到 pythonnet 退出时的 stderr，属已知问题）")
