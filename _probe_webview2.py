# -*- coding: utf-8 -*-
"""探测 WebView2 Runtime 是否安装（官方推荐的两处注册表）。"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import winreg

GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID}"),
    (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID}"),
    (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{GUID}"),
]

found = None
for root, path in KEYS:
    try:
        with winreg.OpenKey(root, path) as k:
            pv, _ = winreg.QueryValueEx(k, "pv")
            if pv and pv != "0.0.0.0":
                found = pv
                print(f"  ✅ {path.split(chr(92))[1]} → pv = {pv}")
                break
    except FileNotFoundError:
        print(f"  ❌ 无此键: ...{path[-60:]}")
    except Exception as e:
        print(f"  ⚠ {type(e).__name__}: {e}")

print()
if found:
    print(f"WebView2 Runtime 已安装，版本 {found}")
else:
    print("❌ WebView2 Runtime 未安装")

# 再看 Edge 版本（WebView2 通常与 Edge 同源）
try:
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsPlaybackStatus
except Exception:
    pass
