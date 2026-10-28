# -*- coding: utf-8 -*-
"""验证关键风险：从非主线程调用 webview.start() 能否正常工作。
如果不能，登录必须改成在主线程排队执行。"""
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import webview

print("主线程:", threading.current_thread().name)
result = {}


def run_in_thread():
    """在后台线程里创建窗口并 start()。"""
    def inner():
        result["thread"] = threading.current_thread().name
        try:
            w = webview.create_window("线程测试", "https://passport.bilibili.com/login",
                                      width=900, height=650)

            def poll():
                for _ in range(20):
                    time.sleep(0.5)
                    try:
                        u = w.get_current_url()
                    except Exception:
                        u = None
                    if u and len(str(u)) > 15:
                        result["url"] = str(u)[:60]
                        break
                try:
                    w.destroy()
                except Exception:
                    pass

            threading.Thread(target=poll, daemon=True).start()
            result["start_before"] = True
            webview.start(debug=False)
            result["start_returned"] = True
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)[:200]}"

    inner()


t = threading.Thread(target=run_in_thread, daemon=True)
t.start()
t.join(timeout=25)

print("\n═══ 结果 ═══")
for k, v in result.items():
    print(f"  {k}: {v}")

if result.get("error"):
    print("\n❌ 后台线程方案不可行，需要主线程方案")
elif result.get("url"):
    print("\n✅ 后台线程可行")
else:
    print("\n⚠ 未确认")
