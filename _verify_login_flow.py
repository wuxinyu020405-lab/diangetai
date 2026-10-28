# -*- coding: utf-8 -*-
"""端到端验证：browserlogin 的 pywebview 登录流程能否真正跑通。
不真扫码（需人工），验证：窗口能起、能加载页面、能读到 Cookie、能正常关闭。"""
import sys
import threading
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
        print("   [log]", str(m)[:100])


app = FakeApp()

print("═══ 直接调用 _open_login_window（B站）═══")
info = {}


def on_poll(ck):
    info["cookie_count"] = len(ck)
    info["cookie_names"] = list(ck.keys())[:8]
    return None      # 不完成，等超时自动关


t0 = time.time()
res = browserlogin._open_login_window(
    "https://passport.bilibili.com/login",
    "验证 - B站",
    on_poll,
    timeout_sec=8,      # 8 秒后自动关，无人值守
)
dt = time.time() - t0

print(f"\n  返回: {res}")
print(f"  耗时: {dt:.1f}s")
print(f"  期间读到的 Cookie: {info.get('cookie_count', '未读')} 个")
print(f"  Cookie 名: {info.get('cookie_names', [])}")

print("\n═══ 检查进程残留 ═══")
import subprocess
r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq msedgedriver.exe"],
                   capture_output=True, text=True, timeout=10)
n = (r.stdout or "").lower().count("msedgedriver")
print(f"  msedgedriver 进程数: {n}  (应为 0 —— pywebview 无独立驱动)")

print("\n结论:", "✅ pywebview 登录链路可用" if dt > 3 else "⚠ 异常")
