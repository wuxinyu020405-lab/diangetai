# -*- coding: utf-8 -*-
"""用 WebView2 官方 API 设置代理：在 before_show / initialized 事件里改 CoreWebView2Options。

pywebview 的做法：window.events.before_show 能拿到 native 窗口，
但 CoreWebView2 需要已初始化。更可靠的是用 CoreWebView2Environment 参数，
pywebview 6.x 支持通过 webview.settings 或环境变量传 browser args。
这里测试：直接用 WinForms 层的 WebView2 控件设置 proxy。
"""
import os
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROXY = "127.0.0.1:7993"

import browserlogin

wv = browserlogin._get_webview()
out = {}


def build():
    w = wv.create_window("proxy2", "https://www.bilibili.com/", width=900, height=650)

    def on_shown():
        """窗口显示后，尝试通过 native 拿到 WebView2 控件并设代理。
        ⚠️ 必须在 UI 线程 —— 用 window.native 的方式不可行，
        改试 pywebview 暴露的 webview.Invoke。"""
        pass

    def poll():
        time.sleep(10)
        try:
            out["loc"] = w.evaluate_js("location.href")[:60]
            out["body"] = w.evaluate_js("(document.body ? document.body.innerText : '').slice(0,100)")[:100]
            ck = w.get_cookies()
            out["cookies"] = len(ck) if ck else 0
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

print("═══ 结果 ═══")
for k in sorted(out):
    print(f"  {k}: {out[k]}")

# 关键对照：用系统 curl（走代理）能否访问 bilibili
import subprocess
r = subprocess.run(["curl", "-s", "-m", "10", "-x", "http://127.0.0.1:7993",
                    "-o", "/dev/null", "-w", "%{http_code}", "https://www.bilibili.com/"],
                   capture_output=True, text=True)
print(f"\n对照：curl 走代理访问 bilibili = {r.stdout}")
