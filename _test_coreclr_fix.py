# -*- coding: utf-8 -*-
"""按 PR #1832 的方式，用带 runtimeconfig 的 coreclr 启动，再试 WebView2。
核心：PYTHONNET_CORECLR_RUNTIME_CONFIG 指向我们生成的 json，
      pythonnet 会把它作为 runtime_config 传给 clr_loader。"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIB = os.path.abspath(os.path.join(".venv", "Lib", "site-packages", "webview", "lib"))
CFG = os.path.join(LIB, "pywebview-runtimeconfig.json")
print("runtimeconfig:", CFG, "存在:", os.path.exists(CFG))

os.environ["PYTHONNET_RUNTIME"] = "coreclr"
os.environ["PYTHONNET_CORECLR_RUNTIME_CONFIG"] = CFG

import pythonnet
pythonnet.load("coreclr")
import clr

print("\n═══ 用 PR 的 runtimeconfig 加载 WinForms ═══")
try:
    clr.AddReference("System.Windows.Forms")
    print("  ✅ System.Windows.Forms 加载成功！")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:200]}")
    sys.exit(1)

print("\n═══ 检查关键类型是否可用（之前卡在 ContextMenu）═══")
try:
    from System.Windows.Forms import Form, Button
    print("  ✅ Form / Button 可用")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:160]}")

print("\n═══ 尝试导入 pywebview winforms 后端 ═══")
try:
    import webview.platforms.winforms as wf
    print("  ✅ winforms 后端导入成功")
    print("     WebView2 类:", getattr(wf, "WebView2", "?"))
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:260]}")
