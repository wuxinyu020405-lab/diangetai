# -*- coding: utf-8 -*-
"""验证 pywebview 的 get_cookies 是否真能读到浏览器里的 Cookie。
用一个会设置 Cookie 的页面（先访问 bilibili 主站拿 buvid 等基础 Cookie）。"""
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import browserlogin

samples = []


def on_poll(ck):
    samples.append((round(time.time() % 100, 1), len(ck), list(ck.keys())[:6]))
    return None


print("访问 www.bilibili.com（会自动下发 buvid3 等 Cookie...）")
browserlogin._open_login_window(
    "https://www.bilibili.com/",
    "Cookie 验证",
    on_poll,
    timeout_sec=10,
)

print("\n═══ 各次轮询读到的 Cookie 数量 ═══")
for t, n, names in samples:
    print(f"  +{t}s: {n} 个  {names}")

mx = max((n for _, n, _ in samples), default=0)
print(f"\n最多读到 {mx} 个 Cookie")
print("结论:", "✅ get_cookies 正常工作" if mx > 0 else "❌ 读不到 Cookie（需排查）")
