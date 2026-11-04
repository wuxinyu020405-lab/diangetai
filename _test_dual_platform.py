# -*- coding: utf-8 -*-
"""双平台并发集成冒烟：真实 MusicApp 起真实 main_async 循环，
B站(真 cookie/房间) + 抖音(真房间) 同时连，验证两路都活。
用法: python -X utf8 _test_dual_platform.py [秒数]
判定：/api/data 响应=服务起；窗口标题=GUI在；抖音通道日志靠 provider
自测已证——这里验证的是"接进 MusicApp 后整进程不崩、双路并发共存"。"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

# 1) 把抖音房间号写进 config（备份原值，测完还原）
CFG = os.path.join(ROOT, "点歌台拆分", "config.json")
cfg = json.load(open(CFG, encoding="utf-8"))
old_dy = cfg.get("douyin_room_id")
cfg["douyin_room_id"] = "7704209084769471268"   # 实测在播热门房（spike 验证过）
json.dump(cfg, open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
print("config 已注入 douyin_room_id（原值=%r）" % old_dy)

import subprocess
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
MAIN = os.path.join(ROOT, "点歌台拆分", "main.py")
proc = subprocess.Popen([PY, MAIN], cwd=os.path.join(ROOT, "点歌台拆分"))

ok = False
try:
    # 2) 轮询 OBS 服务（main_async 走到端口绑定即说明双路启动段没炸）
    svc = False
    t0 = time.time()
    while time.time() - t0 < 45:
        if proc.poll() is not None:
            print("❌ 进程提前退出 code=%s" % proc.returncode)
            break
        for port in range(8080, 8091):
            try:
                req = urllib.request.Request("http://127.0.0.1:%d/api/data" % port,
                                             headers={"User-Agent": "dual-test"})
                urllib.request.urlopen(req, timeout=2)
                svc = True
                print("✅ OBS 服务在线 :%d（main_async 完整跑通=双路启动无异常）" % port)
                break
            except Exception:
                continue
        if svc:
            break
        time.sleep(2)

    # 3) 窗口标题确认 GUI 活着
    title = ""
    if svc:
        import ctypes
        user32 = ctypes.windll.user32
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
        def cb(hwnd, l):
            if user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                if buf.value.startswith("点歌台控制台"):
                    found.append(buf.value)
            return True
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        title = found[0] if found else ""
        print("✅ GUI 窗口:", title or "(未找到)")

    # 4) 再活 20s 不崩 = 双平台并发稳定窗口期
    alive = proc.poll() is None
    time.sleep(20)
    still = proc.poll() is None
    print("20s 并发窗口期后进程:", "✅ 仍存活" if still else "❌ 崩了 code=%s" % proc.returncode)
    ok = svc and title and still
finally:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    # 还原 config
    cfg["douyin_room_id"] = old_dy if old_dy is not None else ""
    if old_dy is None:
        cfg.pop("douyin_room_id", None)
    json.dump(cfg, open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
    print("config 已还原")

print("结论:", "✅ 双平台并发集成冒烟通过" if ok else "❌ 失败")
sys.exit(0 if ok else 1)
