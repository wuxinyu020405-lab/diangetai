# -*- coding: utf-8 -*-
"""按 PR #1832：把 netcoreapp3.0 版 WebView2 程序集放进 webview/lib/netcoreapp3.0/，
并改造 winforms.py 让 coreclr 下优先用它们。"""
import io
import os
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIB = os.path.abspath(os.path.join(".venv", "Lib", "site-packages", "webview", "lib"))
SUB = os.path.join(LIB, "netcoreapp3.0")
os.makedirs(SUB, exist_ok=True)

z = zipfile.ZipFile("_nv/wv2.nupkg")
want = [
    "lib_manual/netcoreapp3.0/Microsoft.Web.WebView2.Core.dll",
    "lib_manual/netcoreapp3.0/Microsoft.Web.WebView2.WinForms.dll",
]
for src in want:
    dst = os.path.join(SUB, os.path.basename(src))
    with z.open(src) as f, open(dst, "wb") as o:
        o.write(f.read())
    print(f"  ✅ {os.path.basename(src)} → {dst} ({os.path.getsize(dst)//1024} KB)")

print("\n═══ webview/lib 现状 ═══")
for root, dirs, files in os.walk(LIB):
    dlls = [f for f in files if f.endswith(".dll")]
    if dlls:
        rel = os.path.relpath(root, LIB)
        print(f"  {rel if rel != '.' else '(根)':18s}: {len(dlls)} 个 dll")
