# -*- coding: utf-8 -*-
"""用 coreclr 运行时验证 pywebview 加载 B站/QQ音乐页面。"""
import os
import sys
import threading
import time

# ★ 必须在 import webview 之前设置
os.environ["PYTHONNET_RUNTIME"] = "coreclr"

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import webview

TARGETS = [
    ("B站登录", "https://passport.bilibili.com/login"),
    ("QQ音乐", "https://y.qq.com"),
]


def run_case(title, url, wait=11):
    result = {}

    def worker(w):
        try:
            for _ in range(18):
                time.sleep(0.5)
                try:
                    cur = w.get_current_url()
                except Exception:
                    cur = None
                if cur and len(str(cur)) > 10:
                    result["url"] = str(cur)[:80]
                    break
            time.sleep(1.5)
            ck = w.get_cookies()
            if isinstance(ck, dict):
                result["cookie_count"] = len(ck)
                result["cookie_names"] = list(ck.keys())[:6]
            elif ck:
                result["cookie_count"] = len(ck)
                result["cookie_names"] = [str(x)[:12] for x in list(ck)[:6]]
            else:
                result["cookie_count"] = 0
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)[:120]}"

    w = webview.create_window(f"验证 - {title}", url, width=1100, height=780)

    def closer():
        time.sleep(wait)
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=worker, args=(w,), daemon=True).start()
    threading.Thread(target=closer, daemon=True).start()
    webview.start(debug=False)
    return result


for title, url in TARGETS:
    print(f"\n═══ 测试 {title}: {url} ═══")
    r = run_case(title, url)
    for k, v in r.items():
        print(f"  {k}: {v}")
    loaded = r.get("url") and len(str(r.get("url"))) > 20
    print("  结论:", "✅ 页面加载成功" if loaded else "❌ 未加载")
