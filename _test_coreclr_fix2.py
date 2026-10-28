# -*- coding: utf-8 -*-
"""补上 PR 提到的最后一块：coreclr 下需显式 AddReference('Microsoft.Win32.SystemEvents')。"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIB = os.path.abspath(os.path.join(".venv", "Lib", "site-packages", "webview", "lib"))
CFG = os.path.join(LIB, "pywebview-runtimeconfig.json")
os.environ["PYTHONNET_RUNTIME"] = "coreclr"
os.environ["PYTHONNET_CORECLR_RUNTIME_CONFIG"] = CFG

import pythonnet
pythonnet.load("coreclr")
import clr

print("═══ 依 PR 顺序加载程序集 ═══")
for name in ("System.Windows.Forms",
             "Microsoft.Win32.SystemEvents",
             "System.Drawing.Common"):
    try:
        clr.AddReference(name)
        print(f"  ✅ {name}")
    except Exception as e:
        # 尝试用 Desktop 运行时目录的完整路径
        base = r"C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App\9.0.19"
        p = os.path.join(base, name + ".dll")
        if os.path.exists(p):
            try:
                clr.AddReference(p)
                print(f"  ✅ {name}（完整路径）")
                continue
            except Exception as e2:
                print(f"  ❌ {name}: {str(e2)[:100]}")
        else:
            print(f"  ❌ {name}: {str(e)[:100]}")

print("\n═══ 导入 pywebview winforms 后端 ═══")
try:
    import webview.platforms.winforms as wf
    print("  ✅ winforms 后端导入成功")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:300]}")
    sys.exit(1)

print("\n═══ 载入 WebView2 程序集 ═══")
for dll in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"):
    p = os.path.join(LIB, dll)
    print(f"  {dll}: {'存在' if os.path.exists(p) else '缺失'}")
    try:
        clr.AddReference(p)
        print(f"    ✅ 加载成功")
    except Exception as e:
        print(f"    ❌ {str(e)[:150]}")
