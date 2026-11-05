# -*- coding: utf-8 -*-
"""v1.2.3 更新器回归：真实 spawn 外部 powershell worker 走完整换文件流程。

v1.2.1 的 exe-worker（点歌台.exe --__upd__）在真机死于"自己锁自己"：
worker 从 _internal 加载自身 DLL，Windows 拒绝改名被锁的目录 → WinError 5
→ 回滚 → 永远更新不上（朋友装机实录）。本版 worker 是 powershell.exe
（System32，零加载安装目录文件）——因此**本测试能在开发环境真实执行
完整替换路径**，不再有冻结版盲区。

覆盖：成功路径（换身/用户数据逐项保护/清理自删）、错包拦截、
共享锁注入的"半成功回滚+marker保留"、resume 作废分支。
用法: ./.venv\\Scripts\\python.exe -X utf8 _test_autoupdater.py"""
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "点歌台拆分"))
import updater

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  [{extra}]"))


def rd(path):
    return open(path, "rb").read() if os.path.exists(path) else None


def read_log(base):
    lg = os.path.join(base, "更新日志.txt")
    for _ in range(3):   # Add-Content 写入瞬间会短暂占锁，重试
        try:
            return open(lg, encoding="utf-8-sig", errors="replace").read()
        except OSError:
            time.sleep(0.4)
    return ""


def build_base(tmp):
    """伪安装目录：程序文件 + 必须原样保留的用户数据。"""
    base = os.path.join(tmp, "base")
    for sub in ("_internal", "douyin_sign", "music_cache", "node"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    open(os.path.join(base, "点歌台.exe"), "wb").write(b"OLD-EXE")
    open(os.path.join(base, "_internal", "version.py"), "w", encoding="utf-8").write('VERSION = "1.0.0"')
    open(os.path.join(base, "_internal", "old_module.py"), "wb").write(b"old")
    open(os.path.join(base, "douyin_sign", "sign_runner.js"), "wb").write(b"OLD-shell")
    open(os.path.join(base, "douyin_sign", "sign.js"), "wb").write(b"FRIEND-SIGN-JS")
    open(os.path.join(base, "config.json"), "w", encoding="utf-8").write('{"room_id":"999"}')
    open(os.path.join(base, "credential.json"), "w", encoding="utf-8").write('{"musickey":"secret"}')
    open(os.path.join(base, "quota_state.json"), "w", encoding="utf-8").write('{"downloaded":5}')
    open(os.path.join(base, "desktop_lyric.json"), "w", encoding="utf-8").write('{"x":1}')
    open(os.path.join(base, "music_cache", "song.mp3"), "wb").write(b"AUDIO")
    open(os.path.join(base, "node", "node.exe"), "wb").write(b"NODE")
    open(os.path.join(base, "启动日志.txt"), "w", encoding="utf-8").write("log")
    return base


def build_zip(tmp):
    """伪新版便携 zip：根=点歌台/（与真实 CI 产物结构一致）。"""
    zp = os.path.join(tmp, "diangetai-v9.9.9-portable.zip")
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("点歌台/点歌台.exe", b"NEW-EXE")
        zf.writestr("点歌台/_internal/version.py", 'VERSION = "9.9.9"')
        zf.writestr("点歌台/_internal/new_module.py", b"new")
        zf.writestr("点歌台/douyin_sign/sign_runner.js", b"NEW-shell")
        zf.writestr("点歌台/douyin_sign/sign.js", b"SHOULD-NEVER-LAND")
        zf.writestr("点歌台/dotnet/x.dll", b"DLL")
        zf.writestr("点歌台/使用说明.md", b"# NEW DOC")
    return zp


def wait_done(base, signal="marker_gone", timeout=45):
    """成功=marker 消失；回滚=日志出现'回滚到旧版本'。"""
    marker = os.path.join(base, "_update_pending.json")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if signal == "marker_gone" and not os.path.exists(marker):
            return True
        if signal == "rollback" and "回滚到旧版本" in read_log(base):
            return True
        time.sleep(0.5)
    return False


def main():
    tmp = os.path.join(ROOT, "_test_tmp_autoupdater")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    zp = build_zip(tmp)

    # ════ 场景① 成功路径（真实 powershell worker 端到端）════
    base = build_base(tmp)
    staging = os.path.join(base, "_update_staging")
    marker = os.path.join(base, "_update_pending.json")
    n = updater.extract_zip(zp, staging)
    ck("⓪ 解压+zip根剥离+包内版本核对", n == 7 and updater._staging_version_ok(staging, "v9.9.9"))

    user_before = {f: rd(os.path.join(base, f)) for f in
                   ("config.json", "credential.json", "quota_state.json",
                    "desktop_lyric.json", "music_cache/song.mp3",
                    "node/node.exe", "启动日志.txt", "douyin_sign/sign.js")}

    fake_main = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    plan = {"tag": "v9.9.9", "staging": staging, "marker": marker,
            "whitelist": updater.WHITELIST, "pid": fake_main.pid,
            "restart": False, "wait_timeout": 30}
    json.dump(plan, open(marker, "w", encoding="utf-8"), ensure_ascii=False)  # 真实流程里 marker 先落盘
    ps1 = updater.spawn_ps_worker(base, plan)
    ck("① worker 等待主进程退出后完成(未超时)", wait_done(base))
    ck("② 主 exe 换身成功", rd(os.path.join(base, "点歌台.exe")) == b"NEW-EXE")
    ck("③ _internal 整目录替换（新模块进/旧模块无）",
       rd(os.path.join(base, "_internal", "new_module.py")) == b"new"
       and not os.path.exists(os.path.join(base, "_internal", "old_module.py")))
    ck("④ 用户数据 8 项逐一原样", all(
        rd(os.path.join(base, f)) == v for f, v in user_before.items()))
    ck("⑤ sign.js 未动且壳已更新（zip 混入的 sign.js 没落盘）",
       rd(os.path.join(base, "douyin_sign", "sign.js")) == b"FRIEND-SIGN-JS"
       and rd(os.path.join(base, "douyin_sign", "sign_runner.js")) == b"NEW-shell")
    ck("⑥ 使用说明随包更新 + dotnet 就位",
       rd(os.path.join(base, "使用说明.md")) == b"# NEW DOC"
       and os.path.exists(os.path.join(base, "dotnet", "x.dll")))
    leftovers = [x for x in os.listdir(base)
                 if x.endswith((".bak", ".new")) or x in ("_update_staging", "_update_pending.json")]
    ck("⑦ 成功收尾无残留（marker/staging/.bak 全清）", not leftovers, leftovers)
    ck("⑧ ps1 脚本自删", not os.path.exists(ps1))
    st = updater.read_last_update_result(base)
    ck("⑧b 成功结局落盘且可被主程序读到",
       isinstance(st, dict) and st.get("status") == "ok" and "v9.9.9" in (st.get("message") or ""), st)
    ck("⑧c 时间戳格式正常（%格式符未被吞）",
       bool(st) and len(str(st.get("ts") or "")) == 19 and str(st.get("ts")).startswith("20"), st.get("ts"))

    # ════ 场景② 错包拦截（纯函数层）════
    staging2 = os.path.join(tmp, "wrongstaging")
    updater.extract_zip(zp, staging2)
    open(os.path.join(staging2, "_internal", "version.py"), "w", encoding="utf-8").write('VERSION = "8.8.8"')
    ck("⑨ 包内版本不符被拦", not updater._staging_version_ok(staging2, "v9.9.9"))
    ck("⑩ version.py 缺失被拦", not updater._staging_version_ok(tmp, "v9.9.9"))

    # ════ 场景③ 半成功回滚：另一进程无共享打开 _internal/version.py
    # （模拟真机"文件被占用"），worker 换 _internal 必失败 →
    # 已换的 exe 回滚还原，marker 保留可下次续跑。
    base3 = os.path.join(tmp, "base3")
    shutil.copytree(base, base3)   # 用①已更新完的目录复制一份，重放旧版布局
    # 还原成"旧版"状态：把①的产物当旧版重新摆
    open(os.path.join(base3, "点歌台.exe"), "wb").write(b"OLD-EXE")
    open(os.path.join(base3, "_internal", "old_module.py"), "wb").write(b"old")
    _nm = os.path.join(base3, "_internal", "new_module.py")
    if os.path.exists(_nm):
        os.remove(_nm)      # rmtree 对文件会静默失败（ignore_errors），必须 remove
    shutil.rmtree(os.path.join(base3, "dotnet"), ignore_errors=True)
    os.makedirs(os.path.join(base3, "dotnet"), exist_ok=True)
    staging3 = os.path.join(base3, "_update_staging")
    marker3 = os.path.join(base3, "_update_pending.json")
    updater.extract_zip(zp, staging3)
    if os.path.exists(os.path.join(base3, "更新日志.txt")):
        os.remove(os.path.join(base3, "更新日志.txt"))
    target = os.path.join(base3, "_internal", "version.py")
    # 用 python 持无删除共享的句柄模拟"文件被占用"（Windows：普通 open
    # 不带 FILE_SHARE_DELETE，Move-Item/Rename 必失败——正是真机现场）
    locker = subprocess.Popen(
        [sys.executable, "-c",
         "import time\nf=open(r'%s','rb')\ntime.sleep(20)" % target])
    time.sleep(1.5)   # 确保句柄已持有
    fake_main = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    plan3 = {"tag": "v9.9.9", "staging": staging3, "marker": marker3,
             "whitelist": updater.WHITELIST, "pid": fake_main.pid,
             "restart": False, "wait_timeout": 30}
    json.dump(plan3, open(marker3, "w", encoding="utf-8"), ensure_ascii=False)
    updater.spawn_ps_worker(base3, plan3)
    ck("⑪ 占用注入后 worker 走到回滚", wait_done(base3, "rollback", 60))
    ck("⑫ 回滚后 exe 还原旧版", rd(os.path.join(base3, "点歌台.exe")) == b"OLD-EXE")
    ck("⑬ 回滚后 _internal 完好（old 在/new 无）",
       os.path.exists(os.path.join(base3, "_internal", "old_module.py"))
       and not os.path.exists(os.path.join(base3, "_internal", "new_module.py")))
    ck("⑭ marker+staging 保留（下次启动可续装，无需重下载）",
       os.path.exists(marker3) and os.path.isdir(staging3))
    try:
        locker.kill()
    except Exception:
        pass

    # ════ 场景④ resume_pending_update：staging 缺失 → 作废 marker 不 spawn ════
    m4 = os.path.join(tmp, "resume_marker.json")
    json.dump({"tag": "v9", "staging": os.path.join(tmp, "不存在staging"),
               "marker": m4}, open(m4, "w", encoding="utf-8"))
    r = updater.resume_pending_update(m4)
    ck("⑮ resume: staging 缺失返回 False 且删 marker", r is False and not os.path.exists(m4))

    bad = [name for name, ok in RESULTS if not ok]
    print(f"\n{'✅' if not bad else '❌'} _test_autoupdater: {len(RESULTS)-len(bad)}/{len(RESULTS)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
