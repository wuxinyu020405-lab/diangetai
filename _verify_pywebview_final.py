# -*- coding: utf-8 -*-
"""端到端验证：用 netcoreapp3.0 程序集 + coreclr，真正起一个 WebView2 窗口加载网页。"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIB = os.path.abspath(os.path.join(".venv", "Lib", "site-packages", "webview", "lib"))
SUB = os.path.join(LIB, "netcoreapp3.0")
CFG = os.path.join(LIB, "pywebview-runtimeconfig.json")

os.environ["PYTHONNET_RUNTIME"] = "coreclr"
os.environ["PYTHONNET_CORECLR_RUNTIME_CONFIG"] = CFG

import pythonnet
pythonnet.load("coreclr")
import clr

# 依赖顺序很重要：先 WinForms，再 SystemEvents，最后 WebView2 的 netcoreapp3.0 版
for name in ("System.Windows.Forms", "Microsoft.Win32.SystemEvents",
             "System.Drawing.Common"):
    try:
        clr.AddReference(name)
    except Exception:
        p = os.path.join(r"C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App\9.0.19",
                        name + ".dll")
        if os.path.exists(p):
            clr.AddReference(p)

print("加载 netcoreapp3.0 版 WebView2:")
for dll in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"):
    p = os.path.join(SUB, dll)
    try:
        clr.AddReference(p)
        print(f"  ✅ {dll}")
    except Exception as e:
        print(f"  ❌ {dll}: {str(e)[:140]}")

print("\n═══ 验证类型是否可解析（关键：不能出现 ContextMenu 错误）═══")
try:
    import System.Windows.Forms
    from Microsoft.Web.WebView2.WinForms import WebView2
    print("  ✅ Microsoft.Web.WebView2.WinForms.WebView2 类型可用！")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:280]}")
    sys.exit(1)

print("\n═══ 真正创建窗口加载网页 ═══")
import threading
import time
import webview

result = {}


def worker(w):
    try:
        for _ in range(20):
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
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:100]}"


w = webview.create_window("pywebview 验证", "https://passport.bilibili.com/login",
                          width=1100, height=780)
threading.Thread(target=worker, args=(w,), daemon=True).start()


def closer():
    time.sleep(13)
    try:
        w.destroy()
    except Exception:
        pass


threading.Thread(target=closer, daemon=True).start()

try:
    webview.start(debug=False)
except Exception as e:
    print(f"\n❌ webview.start 失败: {type(e).__name__}: {str(e)[:300]}")
    sys.exit(1)

print("\n═══ 结果 ═══")
for k, v in result.items():
    print(f"  {k}: {v}")
ok = result.get("url") and "bilibili" in str(result.get("url"))
print("\n结论:", "🎉 pywebview 可用！" if ok else "⚠ 窗口起了但页面未确认")
