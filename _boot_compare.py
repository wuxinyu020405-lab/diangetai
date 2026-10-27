# -*- coding: utf-8 -*-
"""真实启动对比：原版 vs 拆分版，同条件各自启动，抓取可观察行为逐字节对比。

隔离措施：各自放入独立目录 + 独立的最小 config.json（room_id 为空、无 cookie、
无 credential），因此不会连真实直播间、不会加载真实账号、不碰用户真实配置。
观察点：stdout/stderr、Tk 窗口能否创建、8080 服务能否响应、/api/data 的 JSON、
/api/data 中 style 是否含 GUI 合并后的值。每个进程 12 秒后终止。
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

PY = os.path.abspath(os.path.join(".venv", "Scripts", "python.exe"))
ORIG = "扫码点歌台_优化首次成功_4.py"
SPLIT = "点歌台拆分"
CONFIG = json.dumps({"room_id": "", "bili_cookie": "", "qqmusic_path": ""},
                    ensure_ascii=False)


def free_port_check():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8080))
        return True
    except OSError:
        return False
    finally:
        s.close()


def run_variant(name, entry, setup):
    d = f"_boot_{name}"
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    setup(d)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(os.path.join(d, "_boot.log"), "wb")
    proc = subprocess.Popen([PY, os.path.basename(entry) if os.path.dirname(entry) == "." else entry],
                            cwd=d, stdout=log, stderr=subprocess.STDOUT, env=env)
    out = {"pid": proc.pid}
    try:
        deadline = time.time() + 12
        api = None
        html = None
        while time.time() < deadline:
            if proc.poll() is not None:
                out["exit_early"] = proc.returncode
                break
            try:
                with urllib.request.urlopen("http://127.0.0.1:8080/api/data", timeout=2) as r:
                    api = json.loads(r.read().decode("utf-8"))
                with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=2) as r:
                    html = r.read().decode("utf-8")
                break
            except Exception:
                time.sleep(0.5)
        out["api"] = api
        out["html_len"] = len(html) if html else None
        out["html_sha"] = __import__("hashlib").sha256(html.encode()).hexdigest() if html else None
    finally:
        proc.terminate()
        try:
            proc.wait(8)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    out["log"] = io.open(os.path.join(d, "_boot.log"), encoding="utf-8", errors="replace").read()
    shutil.rmtree(d, ignore_errors=True)
    return out


def setup_orig(d):
    shutil.copy2(ORIG, os.path.join(d, "run_entry.py"))
    io.open(os.path.join(d, "config.json"), "w", encoding="utf-8").write(CONFIG)


def setup_split(d):
    for f in os.listdir(SPLIT):
        if f.endswith(".py"):
            shutil.copy2(os.path.join(SPLIT, f), os.path.join(d, f))
    io.open(os.path.join(d, "config.json"), "w", encoding="utf-8").write(CONFIG)


print("8080 可绑定:", free_port_check())
a = run_variant("orig", "run_entry.py", setup_orig)
time.sleep(1.5)
b = run_variant("split", "main.py", setup_split)


def norm_api(x):
    if x is None:
        return None
    y = dict(x)
    # 去掉随时间变化的值
    return y


print()
print("=" * 66)
print("对比项".ljust(20), "原版")
print("-" * 66)
rows = [
    ("提前退出码", a.get("exit_early", "无(活到超时)"), b.get("exit_early", "无(活到超时)")),
    ("api 拿到", a["api"] is not None, b["api"] is not None),
    ("HTML 字节数", a["html_len"], b["html_len"]),
    ("HTML sha256", (a["html_sha"] or "")[:16], (b["html_sha"] or "")[:16]),
]
for name, va, vb in rows:
    flag = "✅" if va == vb else "❌"
    print(f"{flag} {name:16s} {va}  vs  {vb}")

if a["api"] and b["api"]:
    ka, kb = sorted(a["api"]), sorted(b["api"])
    print(f"{'✅' if ka==kb else '❌'} api 键集合      {ka}  vs  {kb}")
    sa = json.dumps(a["api"]["style"], sort_keys=True)
    sb = json.dumps(b["api"]["style"], sort_keys=True)
    print(f"{'✅' if sa==sb else '❌'} style 配置逐字节 {len(sa)} vs {len(sb)}")
    for key in ["system_playing", "lyric", "current", "list"]:
        va, vb = json.dumps(a["api"][key], sort_keys=True), json.dumps(b["api"][key], sort_keys=True)
        print(f"{'✅' if va==vb else '❌'} {key:14s}  {va[:40]}  vs  {vb[:40]}")

# 日志差异（去时间戳与路径）
import re
def logkey(t):
    t = re.sub(r"\[\d{2}:\d{2}:\d{2}\]", "", t)
    t = re.sub(r"_[a-z]+/", "", t)
    return sorted(l.strip() for l in t.splitlines() if l.strip())

la, lb = logkey(a["log"]), logkey(b["log"])
print()
print("=" * 66)
print("stdout 日志行集合对比（去时间戳后排序）")
only_a = [x for x in la if x not in lb]
only_b = [x for x in lb if x not in la]
print(f"   共同 {len(set(la)&set(lb))} 行 | 仅原版 {len(only_a)} | 仅拆分版 {len(only_b)}")
for x in only_a[:8]:
    print("   仅原版:", x[:90])
for x in only_b[:8]:
    print("   仅拆分:", x[:90])
print()
print("原版日志尾 5 行:")
for x in a["log"].splitlines()[-5:]:
    print("   ", x[:100])
print("拆分版日志尾 5 行:")
for x in b["log"].splitlines()[-5:]:
    print("   ", x[:100])
