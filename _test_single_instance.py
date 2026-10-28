# -*- coding: utf-8 -*-
"""单实例锁验证：进程A 持锁 → 进程B 拿不到 → A退出后 C 重新能拿到。
（子进程会先打印 pygame 横幅，故按标记行读取，忽略其它输出。）"""
import subprocess, sys, os, time

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分")
CHILD = r'''
import sys, os, time
sys.path.insert(0, r"%s")
import main
got = main._acquire_single_instance()
print("LOCKMARK:" + ("ACQUIRED" if got else "REFUSED"), flush=True)
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 3)
''' % HERE

def spawn(hold):
    p = subprocess.Popen([sys.executable, "-c", CHILD, str(hold)],
                         stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
    # 读到 LOCKMARK: 那行为止，跳过 pygame 横幅
    mark = None
    for line in p.stdout:
        if "LOCKMARK:" in line:
            mark = line.split("LOCKMARK:")[1].strip()
            break
    return p, mark

p1, m1 = spawn(6)
print("进程A（先启动，应持锁）:", m1)
time.sleep(0.8)
p2, m2 = spawn(1)
print("进程B（应被拒）      :", m2)
ok = (m1 == "ACQUIRED" and m2 == "REFUSED")

p1.wait(timeout=15)
time.sleep(0.8)
p3, m3 = spawn(1)
print("进程C（A退出后应重新拿到锁）:", m3)
ok = ok and (m3 == "ACQUIRED")

p2.wait(timeout=10); p3.wait(timeout=10)
print("\n结论:", "✅ 单实例锁工作正常" if ok else "❌ 锁行为不符合预期")
sys.exit(0 if ok else 1)
