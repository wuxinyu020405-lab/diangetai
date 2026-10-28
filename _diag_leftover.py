# -*- coding: utf-8 -*-
"""诊断：driver.quit() 后 msedgedriver 进程是否真的退出。"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import settings
import browserlogin


def count_drivers():
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq msedgedriver.exe"],
                           capture_output=True, text=True, timeout=10)
        return (r.stdout or "").lower().count("msedgedriver.exe")
    except Exception:
        return -1


print("═══ 启动前 ═══")
print("  msedgedriver 进程数:", count_drivers())

logs = []
drv = browserlogin.start_driver(lambda m: logs.append(str(m)))
print("\n═══ 启动后 ═══")
print("  msedgedriver 进程数:", count_drivers())
if drv:
    print("  pid:", getattr(drv.service, "process", None) and drv.service.process.pid)
    print("  quit() 前...")
    drv.quit()
    print("  quit() 已调用")
    for i in range(6):
        time.sleep(0.5)
        n = count_drivers()
        print(f"   +{0.5*(i+1):.1f}s 后进程数: {n}")
        if n <= 0:
            break
else:
    print("  启动失败")
    for l in logs[-8:]:
        print("   ", l[:130])
