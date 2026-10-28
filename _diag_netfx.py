# -*- coding: utf-8 -*-
"""深挖 netfx 失败的根因：Python.Runtime.dll 的加载问题。
常见原因：
  1. .NET Framework 版本太老（需 4.6.2+）
  2. clr_loader 的 netfx 探测依赖注册表
  3. pythonnet 3.x 用到的 Python.Runtime.dll 需要特定 ABI
"""
import os
import sys
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("═══ .NET Framework 版本 ═══")
for hive in (r"HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",):
    try:
        r = subprocess.run(["reg", "query", hive, "/v", "Release"],
                           capture_output=True, text=True, timeout=10, encoding="gbk",
                           errors="replace")
        out = r.stdout or ""
        for line in out.splitlines():
            if "Release" in line:
                print("  ", line.strip())
    except Exception as e:
        print("  查询失败:", e)

print("\n═══ Python.Runtime.dll 检查 ═══")
import glob
pns = glob.glob(r".venv\Lib\site-packages\pythonnet\runtime\*.dll")
for p in pns:
    print(f"  {os.path.basename(p)}: {os.path.getsize(p)//1024} KB")

print("\n═══ pythonnet 版本与支持的运行时 ═══")
import pythonnet
print("  pythonnet:", pythonnet.__version__)
try:
    from clr_loader import get_netfx, get_coreclr
    print("  clr_loader 可用")
    try:
        fx = get_netfx()
        print("  get_netfx() 成功:", fx)
    except Exception as e:
        print(f"  get_netfx() 失败: {type(e).__name__}: {str(e)[:200]}")
except Exception as e:
    print("  clr_loader 导入失败:", e)

print("\n═══ 关键：netfx 需要 .NET Framework 的 pythonnet runtime ═══")
rt = r".venv\Lib\site-packages\pythonnet\runtime"
print("  runtime 目录内容:", os.listdir(rt) if os.path.isdir(rt) else "缺失")
