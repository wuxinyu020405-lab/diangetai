# -*- coding: utf-8 -*-
"""验证：绕过 pywebview 的主线程名称检查后，WebView2 窗口能否在子线程工作。
如果 WinForms 真的需要主线程，这里会挂死或崩溃 —— 那就必须换架构。"""
import os
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import webview

# 技巧：临时改线程名绕过检查（仅用于测试其真实可行性）
result = {}


def run(fake_name):
    def inner():
        old = threading.current_thread().name
        try:
            threading.current_thread().name = fake_name
        except Exception:
            pass
        try:
            w = webview.create_window("线程测试", "https://passport.bilibili.com/login",
                                      width=900, height=650)

            def poll():
                for _ in range(16):
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
            webview.start(debug=False)
            result["returned"] = True
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            try:
                threading.current_thread().name = old
            except Exception:
                pass

    t = threading.Thread(target=inner, daemon=True)
    t.start()
    t.join(timeout=22)
    return t.is_alive()


alive = run("MainThread")
print("\n═══ 结果 ═══")
for k, v in result.items():
    print(f"  {k}: {v}")
print(f"  线程是否卡死未返回: {alive}")
if result.get("error"):
    print("\n❌ 子线程 + WebView2 不可行")
elif result.get("url"):
    print("\n✅ 绕过名称检查后可行（但需评估稳定性）")
else:
    print("\n⚠ 未确认（可能卡死）")
