# -*- coding: utf-8 -*-
"""验证：预加载 Desktop 程序集后，pywebview 能否真正起窗口并加载页面。"""
import glob
import os
import sys
import threading
import time

os.environ["PYTHONNET_RUNTIME"] = "coreclr"

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def preload_winforms():
    """在 import webview 之前，手动把 WindowsDesktop 程序集喂给 CLR。"""
    import pythonnet
    pythonnet.load("coreclr")
    import clr

    base = r"C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App"
    # 选最高版本
    vers = sorted(os.listdir(base), key=lambda s: [int(x) for x in s.split(".") if x.isdigit()][:3], reverse=True) \
        if os.path.isdir(base) else []
    if not vers:
        raise RuntimeError("找不到 WindowsDesktop.App")
    d = os.path.join(base, vers[0])
    # 关键：加载 Forms/Drawing 及其依赖
    for name in ("System.Windows.Forms.dll", "System.Drawing.Common.dll",
                 "System.Drawing.dll", "Accessibility.dll",
                 "Microsoft.Win32.SystemEvents.dll"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            try:
                clr.AddReference(p)
            except Exception as e:
                print(f"   [warn] {name}: {str(e)[:60]}")
    return d


print("预加载 WindowsDesktop 程序集...")
try:
    d = preload_winforms()
    print("  完成，目录:", d)
except Exception as e:
    print("  ❌ 预加载失败:", type(e).__name__, str(e)[:150])
    sys.exit(1)

print("\nimport webview...")
try:
    import webview
    print("  ✅ webview 导入成功")
except Exception as e:
    print("  ❌", type(e).__name__, str(e)[:200])
    sys.exit(1)

result = {}


def worker(w):
    try:
        for _ in range(20):
            time.sleep(0.5)
            try:
                cur = w.get_current_url()
            except Exception:
                cur = None
            if cur and len(str(cur)) > 15:
                result["url"] = str(cur)[:80]
                break
        time.sleep(1.5)
        ck = w.get_cookies()
        result["cookie_count"] = len(ck) if ck else 0
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:100]}"


print("\n创建窗口加载 B站登录页...")
w = webview.create_window("验证", "https://passport.bilibili.com/login",
                          width=1100, height=780)
threading.Thread(target=worker, args=(w,), daemon=True).start()


def closer():
    time.sleep(12)
    try:
        w.destroy()
    except Exception:
        pass


threading.Thread(target=closer, daemon=True).start()

try:
    webview.start(debug=False)
    print("\n窗口已关闭")
except Exception as e:
    print(f"\n❌ webview.start 失败: {type(e).__name__}: {str(e)[:250]}")
    sys.exit(1)

print("\n═══ 结果 ═══")
for k, v in result.items():
    print(f"  {k}: {v}")
ok = result.get("url") and "bilibili" in str(result.get("url"))
print("\n结论:", "✅ pywebview 可用" if ok else "⚠ 窗口起来了但页面未确认")
