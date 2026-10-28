# -*- coding: utf-8 -*-
"""最终验证：只设环境变量，让 pywebview 走自己的完整初始化流程。
这是真实使用场景（业务代码会这么写）。"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIB = os.path.abspath(os.path.join(".venv", "Lib", "site-packages", "webview", "lib"))
CFG = os.path.join(LIB, "pywebview-runtimeconfig.json")

# ★ 必须在 import webview 之前
os.environ["PYTHONNET_RUNTIME"] = "coreclr"
os.environ["PYTHONNET_CORECLR_RUNTIME_CONFIG"] = CFG

import threading
import time

print("导入 webview...")
import webview
print("  ✅ 导入成功")

result = {}


def worker(w):
    try:
        for _ in range(22):
            time.sleep(0.5)
            try:
                u = w.get_current_url()
            except Exception:
                u = None
            if u and len(str(u)) > 15:
                result["url"] = str(u)[:70]
                break
        time.sleep(1.5)
        ck = w.get_cookies()
        result["cookie_count"] = len(ck) if ck else 0
        if ck and isinstance(ck, dict):
            result["cookie_names"] = list(ck.keys())[:6]
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:110]}"


print("\n创建窗口，加载 B站登录页...")
w = webview.create_window("pywebview 最终验证", "https://passport.bilibili.com/login",
                          width=1100, height=780)
threading.Thread(target=worker, args=(w,), daemon=True).start()


def closer():
    time.sleep(14)
    try:
        w.destroy()
    except Exception:
        pass


threading.Thread(target=closer, daemon=True).start()

try:
    webview.start(debug=False)
except Exception as e:
    print(f"\n❌ webview.start 失败: {type(e).__name__}: {str(e)[:350]}")
    sys.exit(1)

print("\n═══ 结果 ═══")
for k, v in result.items():
    print(f"  {k}: {v}")
ok = result.get("url") and "bilibili" in str(result.get("url"))
print("\n" + ("🎉 pywebview 完全可用！" if ok else "⚠ 窗口起了，页面未确认"))
