# -*- coding: utf-8 -*-
"""R-28：子进程登记簿。

程序（asyncio worker、抖音签名、登录辅助等）派生的外部进程统一从这里 spawn/
登记；退出时逐个 terminate→kill。

为什么不再 taskkill /IM node.exe：那会连用户自己开的 node（VSCode、别的脚本）
一起杀。登记制只收自己生出来的。
"""

import os
import subprocess
import threading

_lock = threading.Lock()
_procs = []   # 活着的登记句柄


def run(args, **kw):
    """登记式 subprocess.run。参数同 subprocess.run，返回其结果。"""
    kw.pop("creationflags", None)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    return subprocess.run(args, creationflags=flags, **kw)


def spawn(args, **kw):
    """登记式 Popen：返回 Popen 句柄，退出时会被收割。"""
    if "creationflags" not in kw and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    p = subprocess.Popen(args, **kw)
    with _lock:
        _prune_locked()
        _procs.append(p)
    return p


def _prune_locked():
    for p in list(_procs):
        if p.poll() is not None:
            _procs.remove(p)


def kill_all(timeout=2.0):
    """收割所有登记且还活着的子进程：先 terminate，超时补 kill。返回处理数。"""
    with _lock:
        _prune_locked()
        live = list(_procs)
        _procs.clear()
    n = 0
    for p in live:
        try:
            p.terminate()
        except Exception:
            pass
    import time
    deadline = time.time() + timeout
    for p in live:
        try:
            remain = max(0.0, deadline - time.time())
            try:
                p.wait(timeout=remain)
            except Exception:
                p.kill()
                try:
                    p.wait(timeout=1.0)
                except Exception:
                    pass
            n += 1
        except Exception:
            pass
    return n


def kill_own_descendants():
    """R-28：收割本进程的全部后代进程（node 签名、辅助工具…），返回杀掉个数。

    为什么用"自己进程树"而不是 taskkill /IM node.exe：后者会把**用户自己开的
    node**（VSCode/前端/别的脚本）一起杀掉，属于误伤。退出兜底只该收自己生的。
    实现：Toolhelp 快照建 pid→父pid 映射，从本进程 BFS 出后代，逐个 Terminate。
    """
    if os.name != "nt":
        return kill_all()
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x2

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    try:
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return kill_all()
        pe = PE32()
        pe.dwSize = ctypes.sizeof(PE32)
        kids = {}
        ok = k32.Process32First(snap, ctypes.byref(pe))
        while ok:
            kids.setdefault(pe.th32ParentProcessID, []).append(pe.th32ProcessID)
            ok = k32.Process32Next(snap, ctypes.byref(pe))
        k32.CloseHandle(snap)
    except Exception:
        return kill_all()

    me = os.getpid()
    targets, queue = [], list(kids.get(me, []))
    while queue:
        pid = queue.pop()
        targets.append(pid)
        queue.extend(kids.get(pid, []))

    # 倒序（先杀最深的）避免父进程复活子进程
    killed = 0
    PROCESS_TERMINATE = 0x0001
    for pid in reversed(targets):
        try:
            h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if h:
                k32.TerminateProcess(h, 0)
                k32.CloseHandle(h)
                killed += 1
        except Exception:
            pass
    return killed + kill_all()

