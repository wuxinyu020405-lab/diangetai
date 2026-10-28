# -*- coding: utf-8 -*-
"""验证：给 WebView2 显式指定代理后，页面能否正常加载。
pywebview 支持通过环境变量或 CoreWebView2 参数设置代理。"""
import os
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 方案 A：给 WebView2 传命令行参数（pywebview 支持 additional args？）
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--proxy-server=http://127.0.0.1:7993;https://127.0.0.1:7993"
)

import browserlogin

wv = browserlogin._get_webview()
out = {}


def build():
    w = wv.create_window("proxy test", "https://www.bilibili.com/", width=900, height=650)

    def poll():
        time.sleep(10)
        try:
            out["loc"] = w.evaluate_js("location.href")[:60]
            out["body"] = w.evaluate_js("(document.body ? document.body.innerText : '').slice(0,120)")[:120]
            ck = w.get_cookies()
            out["cookies"] = len(ck) if ck else 0
            if ck:
                out["cookie_names"] = [str(x)[:35] for x in list(ck)[:5]]
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

print("═══ 带代理参数的结果 ═══")
for k in sorted(out):
    print(f"  {k}: {out[k]}")
ok = out.get("cookies", 0) > 0
print("\n结论:", "✅ 代理生效，Cookie 可读" if ok else "⚠ 仍需排查")
