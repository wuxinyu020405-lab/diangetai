# -*- coding: utf-8 -*-
"""验证页面是否真的渲染了（用 DOM 查询判断），而非只是 URL 变了对。"""
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


def work():
    old = threading.current_thread().name
    threading.current_thread().name = "MainThread"
    try:
        w = wv.create_window("dom", "https://www.bilibili.com/", width=900, height=650)

        def poll():
            for i in range(12):
                time.sleep(1.5)
                try:
                    title = w.evaluate_js("document.title")
                    ready = w.evaluate_js("document.readyState")
                    body_len = w.evaluate_js("document.body ? document.body.innerHTML.length : -1")
                    out[f"t{i}"] = f"title={str(title)[:30]!r} ready={ready} body={body_len}"
                    # 一旦 body 有内容就停
                    if isinstance(body_len, int) and body_len > 500:
                        out["loaded_at"] = i * 1.5
                        break
                except Exception as e:
                    out[f"t{i}"] = f"ERR {type(e).__name__}: {str(e)[:60]}"
            # 最后再读 cookie
            try:
                ck = w.get_cookies()
                out["cookies"] = len(ck) if ck else 0
                if ck:
                    out["cookie_list"] = [str(x)[:40] for x in list(ck)[:5]]
            except Exception as e:
                out["cookie_err"] = str(e)[:60]
            try:
                w.destroy()
            except Exception:
                pass

        threading.Thread(target=poll, daemon=True).start()
        wv.start(debug=False)
    finally:
        threading.current_thread().name = old


t = threading.Thread(target=work, daemon=True)
t.start()
t.join(timeout=40)

print("═══ 页面渲染探测 ═══")
for k in sorted(out.keys()):
    print(f"  {k}: {out[k]}")
