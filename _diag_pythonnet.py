# -*- coding: utf-8 -*-
"""诊断 pythonnet 为何加载失败，并尝试用 coreclr 替代 netfx。"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("Python:", sys.version.split()[0])
print()

# 1. 检查 dotnet / .NET Framework 是否存在
import subprocess, shutil
print("═══ 运行时探测 ═══")
print("  dotnet 命令:", shutil.which("dotnet") or "无")
try:
    r = subprocess.run(["dotnet", "--list-runtimes"], capture_output=True, text=True, timeout=20)
    out = (r.stdout or "").strip()
    print("  dotnet runtimes:")
    for line in out.splitlines()[:8]:
        print("    ", line)
except Exception as e:
    print("  dotnet --list-runtimes 失败:", e)

# .NET Framework 目录
import glob
netfx = [r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319",
         r"C:\Windows\Microsoft.NET\Framework\v4.0.30319"]
for p in netfx:
    print(f"  {p}: {'存在' if os.path.isdir(p) else '缺失'}")

print()
print("═══ 尝试用 coreclr 加载 ═══")
os.environ["PYTHONNET_RUNTIME"] = "coreclr"
try:
    import pythonnet
    pythonnet.load("coreclr")
    import clr
    print("  ✅ coreclr 加载成功")
    import System
    print("  System.Runtime:", System.Environment.Version)
except Exception as e:
    print(f"  ❌ coreclr 失败: {type(e).__name__}: {str(e)[:200]}")
    os.environ.pop("PYTHONNET_RUNTIME", None)

print()
print("═══ 尝试 netfx（默认）═══")
os.environ.pop("PYTHONNET_RUNTIME", None)
try:
    import importlib
    import pythonnet
    importlib.reload(pythonnet)
    pythonnet.load("netfx")
    import clr
    print("  ✅ netfx 加载成功")
except Exception as e:
    print(f"  ❌ netfx 失败: {type(e).__name__}: {str(e)[:200]}")
