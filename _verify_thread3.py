# -*- coding: utf-8 -*-
"""进一步验证：把 signal.signal 打桩后，WebView2 能否在子线程真正跑起来。
这是判断"能否与 Tk 共存"的关键实验。"""
import os
import signal
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 打桩：子线程里 signal.signal 是空操作
_orig_signal = signal.signal


def _safe_signal(sig, handler):
    try:
        return _orig_signal(sig, handler)
    except ValueError:
        return None     # 非主线程：忽略


signal.signal = _safe_signal

import webview

result = {}


def inner():
    old = threading.current_thread().name
    try:
        threading.current_thread().name = "MainThread"
    except Exception:
        pass
    try:
        w = webview.create_window("线程测试", "https://passport.bilibili.com/login",
                                  width=900, height=650)

        def poll():
            for _ in range(18):
                time.sleep(0.5)
                try:
                    u = w.get_current_url()
                except Exception:
                    u = None
                if u and len(str(u)) > 15:
                    result["url"] = str(u)[:60]
                    try:
                        ck = w.get_cookies()
                        result["cookies"] = len(ck) if ck else 0
                    except Exception:
                        pass
                    break
            try:
                w.destroy()
            except Exception:
                pass

        threading.Thread(target=poll, daemon=True).start()
        webview.start(debug=False)
        result["returned"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:180]}"
    finally:
        try:
            threading.current_thread().name = old
        except Exception:
            pass


t = threading.Thread(target=inner, daemon=True)
t.start()
t.join(timeout=24)

print("\n═══ 结果 ═══")
for k, v in result.items():
    print(f"  {k}: {v}")
print(f"  线程卡死: {t.is_alive()}")
if result.get("url"):
    print("\n✅ 子线程可行（打桩 signal 后）→ 可与 Tk 共存")
elif result.get("error"):
    print("\n❌ 仍失败:", result["error"])
else:
    print("\n⚠ 疑似卡死")
