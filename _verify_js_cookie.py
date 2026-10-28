# -*- coding: utf-8 -*-
"""替代方案验证：用 JS 读 Cookie（同源页面下 document.cookie 可用）。
注意 HttpOnly 的 Cookie（如 SESSDATA）JS 读不到 —— 这是关键限制，需评估。"""
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


def build():
    w = wv.create_window("js cookie", "https://www.bilibili.com/", width=1000, height=700)

    def poll():
        for i in range(10):
            time.sleep(1.5)
            try:
                loc = w.evaluate_js("location.href") or ""
                js = w.evaluate_js("document.cookie") or ""
                if "bilibili.com" in loc and js:
                    out["loc"] = str(loc)[:50]
                    out["js_len"] = len(js)
                    out["js_names"] = [x.split("=")[0].strip() for x in js.split(";")][:10]
                    out["has_SESSDATA"] = "SESSDATA" in js
                    break
            except Exception as e:
                out[f"e{i}"] = str(e)[:50]
                continue
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

print("═══ JS 读 Cookie 结果 ═══")
for k in sorted(out):
    print(f"  {k}: {out[k]}")

print("\n⚠ 关键：SESSDATA 是 HttpOnly，JS 读不到")
print("   若 has_SESSDATA=False，说明必须用 CookieManager API，JS 方案不可行")
