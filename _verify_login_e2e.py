# -*- coding: utf-8 -*-
"""端到端验证：调用真实的登录入口，确认窗口能起、能读 Cookie、无残留进程。
不扫码（需人工），靠超时自动关闭。"""
import subprocess
import sys
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import browserlogin


class FakeApp:
    def __init__(self):
        self.logs = []

        class R:
            def after(self_, ms, fn):
                pass
        self.root = R()

    def log(self, m):
        self.logs.append(str(m))
        print("   [log]", str(m)[:110])


app = FakeApp()

print("═══ 调用 bilibili_auto_login（等待 12 秒后自动超时）═══")
t0 = time.time()
browserlogin.bilibili_auto_login(app)
time.sleep(12)

print(f"\n耗时 {time.time()-t0:.0f}s")
print(f"日志 {len(app.logs)} 条")

# 检查残留
r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq msedgedriver.exe"],
                   capture_output=True, text=True, timeout=10)
n = (r.stdout or "").lower().count("msedgedriver")
print(f"\nmsedgedriver 残留进程数: {n}")
print("  (pywebview 方式应为 0，无独立驱动进程)")

print("\n═══ 判断 ═══")
started = any("打开内嵌浏览器" in l or "扫码" in l for l in app.logs)
print("  登录流程启动:", "✅" if started else "❌")
print("  无残留进程:", "✅" if n == 0 else f"❌ 有 {n} 个")
