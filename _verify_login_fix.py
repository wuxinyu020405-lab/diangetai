# -*- coding: utf-8 -*-
"""端到端验证 start_driver 修复：真实启动浏览器 → 开页面 → 读 cookie → 关闭。"""
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "点歌台拆分")
import browserlogin
import settings

logs = []


def log(m):
    logs.append(m)
    print("   [log]", m[:110])


drv = browserlogin.start_driver(log)
if drv is None:
    print("❌ start_driver 返回 None")
    sys.exit(1)
try:
    print("✅ 浏览器启动成功，capabilities:", drv.capabilities.get("browserName"),
          drv.capabilities.get("browserVersion"))
    # 用本地页面验证（不联网，避开直播间/网络依赖）
    probe = os.path.join(settings.BASE_DIR, "_probe_page.html")
    with open(probe, "w", encoding="utf-8") as f:
        f.write("<html><head><title>PROBE_OK</title></head><body>x</body></html>")
    drv.get("file:///" + probe.replace("\\", "/"))
    print("✅ 导航成功，title =", repr(drv.title))
    cookies = drv.get_cookies()
    print("✅ get_cookies 可用，返回", len(cookies), "条")
    os.remove(probe)
finally:
    try:
        drv.quit()
        print("✅ quit OK")
    except Exception as e:
        print("⚠ quit 异常:", e)
    shutil.rmtree(os.path.join(settings.BASE_DIR, "_login_profile"), ignore_errors=True)
    shutil.rmtree(os.path.join(settings.BASE_DIR, "_login_tmp"), ignore_errors=True)
print("\n结论：start_driver 修复有效 ✅")
