# -*- coding: utf-8 -*-
"""穿透锁死修复验证：真实 Win32 全局热键闭环（候选列表版）。
本机 Ctrl+Alt+L 被占 → 应自动降级到下一个候选并成功注册。
用法: python -X utf8 _test_hotkey.py"""
import os, sys, time, ctypes
from ctypes import wintypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util
spec = importlib.util.spec_from_file_location("dl", os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop_lyric.py"))
dl = importlib.util.module_from_spec(spec); spec.loader.exec_module(dl)

results = []
def ck(name, ok, d=""):
    results.append(ok); print(("OK  " if ok else "FAIL"), name, d)

user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312

# ① 注册（本机 L 被占，应降级到候选2 Ctrl+Alt+D）
hk = dl._HotkeyThread(on_fire=lambda: setattr(hk, "_fired", True))
hk._fired = False
hk.start()
time.sleep(0.4)
ck("① 候选列表注册成功", hk.registered)
ck("① label 非空且为候选之一", hk.label in [c[2] for c in dl.HOTKEY_CANDIDATES], "label=%r" % hk.label)

# ② 模拟触发（PostThreadMessage 到热键线程，与具体 vk 无关）
tid = hk.native_id
if tid:
    user32.PostThreadMessageW(tid, WM_HOTKEY, dl.HOTKEY_ID, 0)
    time.sleep(0.3)
    ck("② 热键触发回调", getattr(hk, "_fired", False))
else:
    ck("② 热键触发回调", False, "无 native_id")

# ③ 候选耗尽：再开 N 个实例占满其余候选，最后一个必须注册失败
#    （这验证不变量"注册失败→拒绝穿透"在极端情况下依然成立）
pool = [hk]
for i in range(len(dl.HOTKEY_CANDIDATES) + 1):
    h = dl._HotkeyThread(on_fire=lambda: None)
    h.start(); time.sleep(0.35)
    pool.append(h)
    if not h.registered:
        ck("③ 候选耗尽后第%d个实例注册失败" % (i + 2), True)
        break
else:
    ck("③ 候选耗尽后注册失败", False, "所有实例都注册成功（候选数=%d 未耗尽？）" % len(dl.HOTKEY_CANDIDATES))

for h in pool:
    h.stop()
time.sleep(0.2)
bad = results.count(False)
print("结论:", "✅ 穿透锁死修复验证通过 (%d/%d)" % (len(results), len(results)) if bad == 0 else "❌ 失败 %d 项" % bad)
sys.exit(0 if bad == 0 else 1)
