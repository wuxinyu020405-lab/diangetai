# -*- coding: utf-8 -*-
"""查页面加载失败原因：监听 WebView2 的导航事件，捕获错误码。"""
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

URI = "https://www.bilibili.com/"


def build():
    w = wv.create_window("err", URI, width=900, height=650)

    def poll():
        time.sleep(8)
        try:
            out["loc"] = w.evaluate_js("location.href")[:60]
            out["title"] = w.evaluate_js("document.title")[:40]
            out["body_head"] = w.evaluate_js("(document.body ? document.body.innerText : '').slice(0,200)")[:200]
        except Exception as e:
            out["err"] = str(e)[:120]
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=poll, daemon=True).start()


build()
try:
    wv.start(debug=False)
except Exception as e:
    out["start_err"] = str(e)[:100]

print("═══ 页面真实内容 ═══")
for k in sorted(out):
    print(f"  {k}: {out[k]}")
