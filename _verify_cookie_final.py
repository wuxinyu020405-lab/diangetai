# -*- coding: utf-8 -*-
"""最终关键验证：真实页面下 get_cookies 能否读到大站下发的 Cookie。"""
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
samples = []


def build():
    w = wv.create_window("cookie final", "https://www.bilibili.com/",
                         width=1000, height=700)

    def poll():
        for i in range(14):
            time.sleep(1.2)
            try:
                ck = browserlogin._cookies_to_dict(w.get_cookies())
                samples.append((round(i * 1.2, 1), len(ck),
                                [k for k in list(ck.keys())[:5]]))
                if len(ck) >= 3:
                    out["final"] = ck
                    out["count"] = len(ck)
                    break
            except Exception as e:
                samples.append((round(i * 1.2, 1), -1, str(e)[:40]))
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=poll, daemon=True).start()


build()
try:
    wv.start(debug=False)
except Exception as e:
    print("start 异常:", str(e)[:100])

print("═══ 轮询读 Cookie ═══")
for t, n, names in samples:
    print(f"  +{t}s: {n} 个 {names}")

print(f"\n最终读到 {out.get('count', 0)} 个 Cookie")
print("结论:", "✅ Cookie 读取正常" if out.get("count", 0) > 0 else "❌ 仍读不到")
