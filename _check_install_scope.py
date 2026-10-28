# -*- coding: utf-8 -*-
"""核查：pywebview/pythonnet 装在哪，是否污染全局 Python。"""
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("═══ 当前解释器 ═══")
print("  sys.executable:", sys.executable)
print("  sys.prefix    :", sys.prefix)
print("  venv 内?      :", sys.prefix != sys.base_prefix)

print("\n═══ venv 里的包（新装的那几个）═══")
venv_site = os.path.join(sys.prefix, "Lib", "site-packages")
for name in ("pywebview", "pythonnet", "clr_loader", "bottle", "proxy_tools", "webview"):
    p = os.path.join(venv_site, name)
    if os.path.isdir(p):
        print(f"  venv ✅ {name}")
    else:
        print(f"  venv ❌ {name}")

# 版本
for dist in ("pywebview", "pythonnet", "clr_loader", "bottle", "proxy_tools"):
    try:
        d = os.path.join(venv_site, f"{dist}-{''}")
        cands = [x for x in os.listdir(venv_site) if x.lower().startswith(dist.lower()) and x.endswith(".dist-info")]
        print(f"  {dist}: {cands[0] if cands else '未找到 dist-info'}")
    except Exception:
        pass

print("\n═══ 全局 Python（3.12.10 那个）有没有被污染 ═══")
GLOBAL_PY = r"C:\Users\14506\AppData\Local\Programs\Python\Python312\python.exe"
if os.path.exists(GLOBAL_PY):
    for pkg in ("pywebview", "pythonnet", "clr_loader", "bottle", "proxy_tools"):
        r = subprocess.run([GLOBAL_PY, "-c", f"import {pkg}"], capture_output=True, text=True)
        print(f"  全局 {pkg}: {'❌ 已装（污染！）' if r.returncode == 0 else '✅ 未装'}")

print("\n═══ 全局 site-packages 目录实际内容（找这些包）═══")
gsite = r"C:\Users\14506\AppData\Local\Programs\Python\Python312\Lib\site-packages"
if os.path.isdir(gsite):
    hits = [x for x in os.listdir(gsite)
            if any(k in x.lower() for k in ("webview", "pythonnet", "clr_loader", "bottle", "proxy_tools"))]
    print("  命中:", hits if hits else "✅ 无")

print("\n═══ 全局是否有 portable 版 Python 的 site-packages 被写 ═══")
alt = os.path.expandvars(r"%LOCALAPPDATA%\Python\pythoncore-3.15-64")
print(f"  3.15 目录: {'存在' if os.path.isdir(alt) else '不存在（已卸载）'}")
