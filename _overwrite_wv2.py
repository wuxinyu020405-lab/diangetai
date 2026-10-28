# -*- coding: utf-8 -*-
"""把 netcoreapp3.0 版 WebView2 DLL 覆盖到 webview/lib/ 根目录，
让 pywebview 的 interop_dll_path() 自动选中它们（该函数不认 netcoreapp 子目录）。
先备份旧文件，便于回滚。"""
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIB = os.path.abspath(os.path.join(".venv", "Lib", "site-packages", "webview", "lib"))
SUB = os.path.join(LIB, "netcoreapp3.0")

for dll in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"):
    src = os.path.join(SUB, dll)
    dst = os.path.join(LIB, dll)
    bak = dst + ".net462.bak"
    if not os.path.exists(bak) and os.path.exists(dst):
        shutil.copy2(dst, bak)
        print(f"  备份旧版 → {os.path.basename(bak)}")
    shutil.copy2(src, dst)
    print(f"  ✅ 覆盖 {dll}: {os.path.getsize(dst)//1024} KB")

print("\n完成。现在 webview/lib/ 下是 netcoreapp3.0 版（用 ContextMenuStrip，兼容 .NET 6+）")
