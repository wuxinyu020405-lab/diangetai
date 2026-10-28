# -*- coding: utf-8 -*-
"""通过 pywebview 的 evaluate_js（它会派发到 UI 线程）读取 CookieManager。

思路：evaluate_js 在 UI 线程执行，我们让它返回一个占位值；
真正的 Cookie 通过 pywebview 的 window.pywebview.api 回调回 Python。
但更简单：pywebview 有 window.events.loaded，且 evaluate_js 本身在 UI 线程，
因此可以在 evaluate_js 里执行 JS，JS 用 fetch 带 credentials 拿响应头？不行。

改用：WebView2 支持 document.cookie 读不到 HttpOnly，
但可以用 JS 触发一次「同源请求」，Cookie 会随请求发送 —— 我们看不到。

最终方案：用 pywebview 的 expose 机制，让 JS 侧通过 pywebview.api 反向调用，
在 Python 的 UI 线程回调里访问 CoreWebView2。
"""
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import browserlogin

wv = browserlogin._get_webview()
out = {}


class Api:
    """暴露给 JS，同时持有 window 引用，可在 UI 线程回调里访问 CoreWebView2。"""

    def __init__(self):
        self.window = None

    def ping(self):
        return "pong"


api = Api()


def build():
    w = wv.create_window("api", "https://www.bilibili.com/", width=1000, height=700,
                         js_api=api)
    api.window = w

    def poll():
        time.sleep(9)
        try:
            # evaluate_js 在 UI 线程执行；利用它调用 pywebview.api.ping 验证桥接
            r = w.evaluate_js("window.pywebview ? 'bridge_ok' : 'no_bridge'")
            out["bridge"] = r
            out["loc"] = str(w.evaluate_js("location.href"))[:50]
            # 关键实验：在 JS 里读不到 SESSDATA，但可以用 JS 触发下载？
            out["js_has_sessdata"] = "SESSDATA" in (w.evaluate_js("document.cookie") or "")

            # 尝试 pywebview 的 get_cookies 再来一次（这次页面已完全加载）
            ck = browserlogin._cookies_to_dict(w.get_cookies())
            out["get_cookies_count"] = len(ck)
            out["get_cookies_names"] = list(ck.keys())[:8]
        except Exception as e:
            out["err"] = str(e)[:140]
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=poll, daemon=True).start()


build()
try:
    wv.start(debug=False)
except Exception as e:
    print("start:", str(e)[:80])

print("═══ 结果 ═══")
for k in sorted(out):
    print(f"  {k}: {out[k]}")
