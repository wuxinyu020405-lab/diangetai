# -*- coding: utf-8 -*-
"""定位 pythonnet + WinForms 的正确配置。"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ["PYTHONNET_RUNTIME"] = "coreclr"

import pythonnet
pythonnet.load("coreclr")
import clr

print("═══ 尝试各种方式加载 System.Windows.Forms ═══")

attempts = [
    ("直接 AddReference", lambda: clr.AddReference("System.Windows.Forms")),
    ("加 Desktop 共享路径", None),
]

# 方式1：直接加
try:
    clr.AddReference("System.Windows.Forms")
    print("  ① clr.AddReference('System.Windows.Forms')  → ✅")
except Exception as e:
    print(f"  ① 失败: {type(e).__name__}: {str(e)[:90]}")

# 方式2：检查 Desktop 目录里的程序集
import glob
d9 = r"C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App\9.0.19"
print(f"\n  WindowsDesktop 9.0.19 目录内容（前15）:")
if os.path.isdir(d9):
    for f in sorted(os.listdir(d9))[:15]:
        print("    ", f)
    has_forms = os.path.exists(os.path.join(d9, "System.Windows.Forms.dll"))
    print(f"    System.Windows.Forms.dll: {'✅ 存在' if has_forms else '❌ 缺失'}")
else:
    print("    目录不存在")

# 方式3：把 Desktop 目录加入 sys.path 再试
print("\n═══ 方式3：临时 sys.path 加入 Desktop 目录 ═══")
sys.path.insert(0, d9)
try:
    clr.AddReference(os.path.join(d9, "System.Windows.Forms.dll"))
    print("  ✅ 用完整路径加载成功")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:120]}")

# 方式4：检查 NETFX 是否其实可用（换 pythonnet 加载参数）
print("\n═══ 方式4：netfx 的详细失败原因 ═══")
import importlib
os.environ.pop("PYTHONNET_RUNTIME", None)
os.environ["PYTHONNET_RUNTIME"] = "netfx"
try:
    importlib.reload(pythonnet)
    pythonnet.load("netfx")
    print("  ✅ netfx 加载成功")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {str(e)[:150]}")
