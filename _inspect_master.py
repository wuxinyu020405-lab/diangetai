# -*- coding: utf-8 -*-
"""核实 pywebview master 源码里是否与 PR #1832 一致的修复点。"""
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = "_pwsrc/pywebview-master/webview"

print("═══ 1. lib 目录构成 ═══")
lib = os.path.join(ROOT, "lib")
if os.path.isdir(lib):
    for item in sorted(os.listdir(lib)):
        p = os.path.join(lib, item)
        print(f"  {item}{'/' if os.path.isdir(p) else ''}")

print("\n═══ 2. 运行时选择：coreclr 优先？ ═══")
# 找设置 PYTHONNET_RUNTIME 的地方
import glob
for f in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
    txt = io.open(f, encoding="utf-8", errors="replace").read()
    if "PYTHONNET_RUNTIME" in txt:
        rel = os.path.relpath(f, ROOT)
        # 找关键行
        for i, line in enumerate(txt.splitlines(), 1):
            if "PYTHONNET_RUNTIME" in line and ("coreclr" in line or "netfx" in line):
                print(f"  {rel}:{i}  {line.strip()[:90]}")

print("\n═══ 3. interop_dll_path 是否会按运行时选 netcoreapp？ ═══")
u = os.path.join(ROOT, "util.py")
txt = io.open(u, encoding="utf-8", errors="replace").read()
i = txt.find("def interop_dll_path")
if i > 0:
    seg = txt[i:i + 1200]
    print("  含 netcoreapp:", "netcoreapp" in seg)
    print("  片段:")
    for line in seg.splitlines()[:22]:
        print("   ", line[:95])

print("\n═══ 4. SystemEvents 是否在 coreclr 下显式引用 ═══")
wf = os.path.join(ROOT, "platforms", "winforms.py")
txt = io.open(wf, encoding="utf-8", errors="replace").read()
print("  含 Microsoft.Win32.SystemEvents:", "SystemEvents" in txt)
for i, line in enumerate(txt.splitlines(), 1):
    if "SystemEvents" in line:
        print(f"    {i}: {line.strip()[:90]}")

print("\n═══ 5. WebView2 程序集版本 ═══")
for sub in ("netcoreapp3.0", "."):
    d = os.path.join(lib, sub)
    for dll in ("Microsoft.Web.WebView2.Core.dll",):
        p = os.path.join(d, dll)
        if os.path.exists(p):
            print(f"  {sub}/{dll}: {os.path.getsize(p)//1024} KB")
