# -*- coding: utf-8 -*-
"""对照实验：页面加载后，get_cookies() 到底能否读到匿名 Cookie（buvid3 等）。
bilibili 首页一定会下发 buvid3，所以"读到 0 个"就说明 API 有问题；
"读到几个但没 SESSDATA"才说明是未登录（正常现象）。"""
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
log = []


def build():
    w = wv.create_window("ck", "https://www.bilibili.com/", width=1000, height=700)

    def poll():
        last = -2
        for i in range(16):
            time.sleep(1.2)
            try:
                raw = w.get_cookies()
                ck = browserlogin._cookies_to_dict(raw)
                t = round(i * 1.2, 1)
                entry = f"+{t}s: get_cookies 返回 {type(raw).__name__}, "
                entry += f"len={len(raw) if raw else 0}, dict={len(ck)}, names={list(ck.keys())[:6]}"
                if len(ck) != last:
                    log.append(entry)
                    last = len(ck)
                if len(ck) >= 2:
                    break
            except Exception as e:
                log.append(f"+{round(i*1.2,1)}s: ERR {type(e).__name__}: {str(e)[:60]}")
        try:
            # 最后对照 JS
            js = w.evaluate_js("document.cookie") or ""
            log.append(f"JS document.cookie 长度={len(js)}, 前60={js[:60]}")
        except Exception as e:
            log.append(f"JS ERR: {str(e)[:60]}")
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

print("═══ get_cookies 逐次结果 ═══")
for line in log:
    print("  ", line)

print("\n判读:")
print("  · 读到 >=2 个（buvid3/buvid4...）→ API 正常，之前 0 是因为页面没加载成功")
print("  · 读到 0 个但 JS 有 694 字符      → API 确实有缺陷")
