# -*- coding: utf-8 -*-
"""直接调用 WebView2 的 CookieManager.GetCookiesAsync 读全部 Cookie（含 HttpOnly）。

关键：必须通过 pywebview 暴露的 native 对象，且 API 只能在 UI 线程调用。
pywebview 的 window.events.before_show 提供 native 访问点。
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


def build():
    w = wv.create_window("cm", "https://www.bilibili.com/", width=1000, height=700)

    def grab_cookies():
        """在 UI 线程里通过 CookieManager 抓 Cookie。
        pywebview 的 window.dom / evaluate_js 都在 UI 线程调度，
        我们用 evaluate_js 无法拿 HttpOnly，所以走 native。"""
        try:
            native = w.native            # BrowserForm
            ctl = getattr(native, "webview", None) or getattr(native, "browser", None)
            out["native_type"] = f"{type(native).__name__} / ctl={type(ctl).__name__ if ctl else None}"
            # 尝试从控件上拿 CoreWebView2
            for attr in ("CoreWebView2", "core_webview2"):
                if ctl is not None and hasattr(ctl, attr):
                    core = getattr(ctl, attr)
                    out["core"] = str(core)[:40]
                    mgr = core.CookieManager
                    res = mgr.GetCookies(w.get_current_url())
                    # 等待异步完成
                    cnt = 0
                    for _ in range(100):
                        if res.IsCompleted:
                            break
                        time.sleep(0.05)
                    if res.IsCompleted:
                        items = res.Result
                        out["cookie_count"] = len(items) if items else 0
                        names = []
                        values = {}
                        for c in (items or []):
                            names.append(str(c.Name))
                            values[str(c.Name)] = str(c.Value)
                        out["names"] = names[:12]
                        out["has_SESSDATA"] = "SESSDATA" in values
                        out["values"] = values   # 完整值，仅本地验证用
                    else:
                        out["status"] = "异步未完成"
                    break
        except Exception as e:
            out["err"] = f"{type(e).__name__}: {str(e)[:150]}"

    def poll():
        time.sleep(8)
        grab_cookies()
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

print("═══ CookieManager 结果 ═══")
for k in sorted(out):
    if k == "values":
        print(f"  values: <{len(out[k])} 个，含 SESSDATA={ 'SESSDATA' in out[k] }>")
    else:
        print(f"  {k}: {out[k]}")
