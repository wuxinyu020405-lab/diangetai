# -*- coding: utf-8 -*-
"""_test_autoupdater.py — v1.2.1 需求19：更新器核心逻辑回归（10 断言）。
在临时目录里搭一个"安装目录"，造便携 zip，直接调 autoupdater._run 走真实
替换路径（pid 用不存在的号，_wait_exit 会立刻放行）。
运行：python _test_autoupdater.py"""
import json
import os
import shutil
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "点歌台拆分"))
import autoupdater

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("  " + str(extra) if extra and not cond else ""))


def build_base(tmp):
    """伪安装目录：程序文件 + 用户数据（更新后必须原样）"""
    base = os.path.join(tmp, "base")
    os.makedirs(os.path.join(base, "_internal"))
    os.makedirs(os.path.join(base, "douyin_sign"))
    os.makedirs(os.path.join(base, "music_cache"))
    os.makedirs(os.path.join(base, "node"))
    open(os.path.join(base, "点歌台.exe"), "wb").write(b"OLD-EXE")
    open(os.path.join(base, "_internal", "version.py"), "w", encoding="utf-8").write('VERSION = "1.0.0"')
    open(os.path.join(base, "_internal", "old_module.py"), "w", encoding="utf-8").write("old")
    open(os.path.join(base, "douyin_sign", "sign_runner.js"), "w", encoding="utf-8").write("OLD-shell")
    open(os.path.join(base, "douyin_sign", "sign.js"), "w", encoding="utf-8").write("FRIEND-SIGN-JS")
    open(os.path.join(base, "config.json"), "w", encoding="utf-8").write('{"room_id":"999"}')
    open(os.path.join(base, "credential.json"), "w", encoding="utf-8").write('{"musickey":"secret"}')
    open(os.path.join(base, "quota_state.json"), "w", encoding="utf-8").write('{"downloaded":5}')
    open(os.path.join(base, "desktop_lyric.json"), "w", encoding="utf-8").write('{"x":1}')
    open(os.path.join(base, "music_cache", "song.mp3"), "wb").write(b"AUDIO")
    open(os.path.join(base, "node", "node.exe"), "wb").write(b"NODE")
    open(os.path.join(base, "启动日志.txt"), "w", encoding="utf-8").write("log")
    return base


def build_zip(tmp, broken=False):
    """伪新版便携 zip：根=点歌台/（与真实 CI 产物一致）"""
    zp = os.path.join(tmp, "diangetai-v9.9.9-portable.zip")
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("点歌台/点歌台.exe", b"NEW-EXE")
        zf.writestr("点歌台/_internal/version.py", 'VERSION = "9.9.9"')
        zf.writestr("点歌台/_internal/new_module.py", "new")
        zf.writestr("点歌台/douyin_sign/sign_runner.js", b"NEW-shell")
        zf.writestr("点歌台/douyin_sign/sign.js", b"SHOULD-NEVER-LAND")
        zf.writestr("点歌台/dotnet/x.dll", b"DLL")
        zf.writestr("点歌台/使用说明.md", "# NEW DOC")
        if broken:
            zf.writestr("点歌台/点歌台.exe", b"X")      # 内容随便，zip 本身被截断
            zf.comment = b"normal"
    return zp


def rd(path):
    return open(path, "rb").read() if os.path.exists(path) else None


def run_log(_msg):
    pass


def main():
    tmp = os.path.join(ROOT, "_test_tmp_autoupdater")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    base = build_base(tmp)
    zp = build_zip(tmp)
    user_files_before = {f: rd(os.path.join(base, f)) for f in
                         ("config.json", "credential.json", "quota_state.json",
                          "desktop_lyric.json", "music_cache/song.mp3",
                          "node/node.exe", "启动日志.txt", "douyin_sign/sign.js")}

    plan = {"tag": "v9.9.9", "zip": zp, "staging": os.path.join(tmp, "staging"),
            "whitelist": ["点歌台.exe", "_internal", "dotnet", "douyin_sign", "使用说明.md"],
            "pid": 999999}   # 不存在的 pid：_wait_exit 立即放行
    autoupdater._run(plan, base, run_log)

    ck("① 主 exe 被替换", rd(os.path.join(base, "点歌台.exe")) == b"NEW-EXE")
    ck("② _internal 整目录替换（新模块进/旧模块无）",
       rd(os.path.join(base, "_internal", "new_module.py")) == b"new"
       and not os.path.exists(os.path.join(base, "_internal", "old_module.py")))
    ck("③ 用户数据 8 项逐一原样", all(
        rd(os.path.join(base, f)) == v for f, v in user_files_before.items()))
    ck("④ sign.js 未被动 且 壳已更新",
       rd(os.path.join(base, "douyin_sign", "sign.js")) == b"FRIEND-SIGN-JS"
       and rd(os.path.join(base, "douyin_sign", "sign_runner.js")) == b"NEW-shell")
    ck("⑤ zip 里混入的 sign.js 没落盘",
       rd(os.path.join(base, "douyin_sign", "sign.js")) != b"SHOULD-NEVER-LAND")
    ck("⑥ 使用说明随包更新", rd(os.path.join(base, "使用说明.md")) == b"# NEW DOC")
    ck("⑦ 收尾无残留（zip/暂存/.bak/.new 全清）",
       not os.path.exists(zp) and not os.path.exists(plan["staging"])
       and not any(x.endswith((".bak", ".new")) for x in os.listdir(base)))

    # 失败路径：第二遍换名时注入异常 → 应回滚到旧版
    base2 = build_base(os.path.join(tmp, "f2"))
    os.makedirs(os.path.join(base2, "dotnet"))
    zp2 = build_zip(os.path.join(tmp, "f2"))
    plan2 = dict(plan, zip=zp2, staging=os.path.join(tmp, "staging2"))
    real_rename = os.rename
    state = {"n": 0}

    def flaky_rename(a, b):
        state["n"] += 1
        if state["n"] == 2:
            raise OSError("注入：磁盘忙")
        return real_rename(a, b)

    os.rename = flaky_rename
    try:
        autoupdater._run(plan2, base2, run_log)
    finally:
        os.rename = real_rename
    ck("⑧ 换名失败回滚：exe 仍是旧版", rd(os.path.join(base2, "点歌台.exe")) == b"OLD-EXE")
    ck("⑨ 回滚后无 .new 残留", not any(x.endswith(".new") for x in os.listdir(base2)))

    # 大小校验：伪造 size 不符 → 取消且不碰任何文件
    base3 = build_base(os.path.join(tmp, "f3"))
    zp3 = build_zip(os.path.join(tmp, "f3"))
    plan3 = dict(plan, zip=zp3, size=os.path.getsize(zp3) + 1, staging=os.path.join(tmp, "staging3"))
    autoupdater._run(plan3, base3, run_log)
    ck("⑩ 大小校验不符→取消，exe 原样", rd(os.path.join(base3, "点歌台.exe")) == b"OLD-EXE")

    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'✅' if not bad else '❌'} _test_autoupdater: {len(RESULTS) - len(bad)}/{len(RESULTS)}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
