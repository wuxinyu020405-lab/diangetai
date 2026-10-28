# -*- coding: utf-8 -*-
"""深入排查 get_cookies 为空：
  1. JS 层面 document.cookie 为何 SecurityError（可能页面是 iframe/特殊状态）
  2. WebView2 用户数据目录位置
  3. 用 CoreWebView2CookieManager 直接读
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

import browserlogin

wv = browserlogin._get_webview()
out = {}


def build():
    w = wv.create_window("diag", "https://www.bilibili.com/", width=900, height=650)

    def poll():
        time.sleep(9)
        try:
            out["url"] = str(w.get_current_url())[:50]
            # 1. JS 详细探测
            try:
                out["location_href"] = w.evaluate_js("location.href")[:70]
                out["cookie_js"] = w.evaluate_js("document.cookie")[:100]
                out["is_secure"] = w.evaluate_js("window.isSecureContext")
            except Exception as e:
                out["js_err"] = str(e)[:120]

            # 2. 直接访问底层 WebView2 的 CookieManager
            try:
                native = w.native
                out["native"] = type(native).__name__
                wv2 = getattr(native, "webview", None) or getattr(native, "WebView", None)
                if wv2 is not None:
                    core = wv2.CoreWebView2
                    mgr = core.CookieManager
                    out["cookie_mgr"] = "可用"
                    # 同步方式：GetCookiesAsync 是异步的，这里仅证明可访问
                    out["cookie_mgr_type"] = type(mgr).__name__
            except Exception as e:
                out["native_err"] = f"{type(e).__name__}: {str(e)[:100]}"
        except Exception as e:
            out["err"] = str(e)[:100]
        finally:
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
