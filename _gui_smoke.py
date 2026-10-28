# -*- coding: utf-8 -*-
"""GUI 冒烟：源码起进程 → 验证标题含 v1.0.0 → 二次启动被锁拒绝 → 关闭。"""
import subprocess, sys, os, time, ctypes

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分")
PY = sys.executable
user32 = ctypes.windll.user32

def find_titles():
    found = []
    EnumWindows = user32.EnumWindows
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
    def cb(hwnd, l):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value.startswith("点歌台控制台"):
                found.append(buf.value)
        return True
    EnumWindows(WNDENUMPROC(cb), 0)
    return found

p1 = subprocess.Popen([PY, os.path.join(HERE, "main.py")], cwd=HERE)
ok = False
try:
    for _ in range(30):
        time.sleep(1)
        t = find_titles()
        if t:
            break
    title = t[0] if t else "(窗口未出现)"
    print("窗口标题:", title)
    has_ver = "v1.0.0" in title
    print("标题含版本号:", "PASS" if has_ver else "FAIL")

    # 二次启动：应弹"已经在运行"提示框，进程自行退出
    p2 = subprocess.Popen([PY, os.path.join(HERE, "main.py")], cwd=HERE)
    time.sleep(12)
    alive2 = p2.poll() is None
    dialogs = []
    def cb2(hwnd, l):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if "已经在运行" in buf.value or buf.value == "点歌台":
                dialogs.append(buf.value)
        return True
    user32.EnumWindows(WNDENUMPROC := ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)(cb2), 0)
    print("二次启动提示框:", dialogs if dialogs else "(未捕获)")

    # 模态框在等用户点"确定"——模拟用户：向对话框发 Enter（默认按钮=OK）
    def cb3(hwnd, l):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == "点歌台":
                user32.PostMessageW(hwnd, 0x0100, 0x0D, 0)   # WM_KEY VK_RETURN
                user32.PostMessageW(hwnd, 0x0101, 0x0D, 0)   # WM_KEYUP
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)(cb3), 0)
    time.sleep(4)
    alive2 = p2.poll() is None
    print("关掉提示框后，二次进程已退出:", "PASS" if not alive2 else "FAIL(还在跑)")

    # 窗口数量应仍只有 1 个主窗口
    t2 = [x for x in find_titles()]
    print("主窗口数量:", len(t2), "PASS" if len(t2) == 1 else "FAIL")
    ok = has_ver and (not alive2) and len(t2) == 1
finally:
    p1.terminate(); p1.wait(timeout=10)
    if p2.poll() is None:
        p2.terminate()
print("结论:", "✅ GUI 冒烟通过" if ok else "❌ 有失败项")
sys.exit(0 if ok else 1)
