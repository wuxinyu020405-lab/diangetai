# -*- coding: utf-8 -*-
"""点歌台自动更新器（需求 #19 / v1.2.1）。

由主程序 spawn 的后台 worker 进程执行（冻结版用自带 exe `--__upd__`，
开发环境用当前 python 直跑本文件）。

职责：主程序退出后，把已下载校验过的 zip 按白名单覆盖进安装目录，然后重启。

调用：点歌台.exe --__upd__     或     python autoupdater.py

自替换时序（冻结版的关键难点）：worker 本身就是 点歌台.exe 的进程，
Windows 不允许重命名正在运行的 exe。所以 点歌台.exe 一项单独走"孙进程换身"：
worker 把旧 exe 改名 .bak → 用**新 exe** spawn 孙进程(--__upd_g__ <worker_pid>)
并给自己 --startup-timeout 0 续命 bootloader → worker 退出 →
孙进程等 worker 死透 → 删 .bak → 退出。孙进程跑在新 exe 里，
天然验证了替换成功；任何一步失败 .bak 都留着可手救。

安全设计（照拍板方案）：
  - 白名单覆盖：只替换 点歌台.exe / _internal / dotnet / douyin_sign 壳
    （壳=只覆盖 sign_runner.js/package.json，绝不碰 douyin_sign\\sign.js）。
    config.json / credential.json / quota_state.json / music_cache /
    desktop_lyric.json / node\\ / 启动日志.txt 等用户数据**碰都不碰**——
    保留承诺由"不覆盖"保证，不是备份恢复保证。
  - 两遍法：先全量拷成 *.new 暂存（此遍失败可完整放弃），
    再逐项快速换名（旧→.bak，new→正式，删.bak）。失败尽力回滚。
  - 消费即删：启动第一件事删 marker，任何路径都不可能无限更新循环。
  - 全程日志：BASE_DIR\\更新日志.txt。
"""

import json
import os
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IS_WIN = os.name == "nt"


def _real_args():
    """真实命令行参数（跳过 arg0）。冻结 bootloader 会把 sys.argv[0] 改写、
    并可能藏掉尾部参数，所以优先走 kernel32.GetCommandLineW。"""
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32
        kernel32.GetCommandLineW.restype = wintypes.LPWSTR
        cmd = kernel32.GetCommandLineW()
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        n = ctypes.c_int(0)
        argv = shell32.CommandLineToArgvW(cmd, ctypes.byref(n))
        if not argv:
            raise OSError("CommandLineToArgvW returned NULL")
        out = [argv[i] for i in range(n.value)]
        # CommandLineToArgvW 的第一个元素恒为 exe 自身路径，固定丢弃
        return out[1:]
    except Exception:
        return sys.argv[1:]


def main():
    if not IS_WIN:
        print("更新器目前仅支持 Windows")
        return 2
    args = _real_args()

    # ── 孙进程模式（仅冻结版）：等新 worker 死透 → 删旧 exe 的 .bak ──
    if args and args[0] == "--__upd_g__":
        try:
            gpid = int(args[1]); gbak = args[2]
        except (ValueError, IndexError):
            return 2
        # 安全阀：只允许删 程序目录\点歌台.exe.bak
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
        want = os.path.join(app_dir, "点歌台.exe.bak")
        if os.path.normcase(os.path.abspath(gbak)) != os.path.normcase(want):
            return 2
        _wait_exit(gpid, _noop_log, kill=False, timeout=120)
        try:
            os.remove(gbak)
        except OSError:
            pass
        return 0

    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))   # 开发环境=settings.BASE_DIR
    marker = os.path.join(base, "_update_pending.json")
    if not os.path.exists(marker):
        print("无待更新标记，直接退出")
        return 0
    with open(marker, "r", encoding="utf-8") as f:
        plan = json.load(f)
    try:
        os.remove(marker)          # 消费即删，防循环
    except OSError:
        pass
    log_lines = []

    def log(msg):
        line = time.strftime("%H:%M:%S ") + str(msg)
        log_lines.append(line)
        print(line)
        try:
            with open(os.path.join(base, "更新日志.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(log_lines))
        except Exception:
            pass

    log(f"=== 更新开始：目标 {plan.get('tag')} ===")
    try:
        _run(plan, base, log)
        return 0
    except Exception as e:
        log(f"❌ 更新异常终止: {type(e).__name__}: {e}")
        return 1


def _noop_log(_msg):
    pass


def _wait_exit(pid, log, timeout=90, kill=True):
    """等目标进程退出；超时则强杀（自己的进程，可控）。kill=False 只等。"""
    import ctypes
    SYNCHRONIZE = 0x00100000
    h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not h:
        log(f"进程 {pid} 已不存在")
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ctypes.windll.kernel32.WaitForSingleObject(h, 1000) == 0:
            break
    else:
        if kill:
            log("主进程超时未退，taskkill 强杀")
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, creationflags=0x08000000)
        else:
            log(f"进程 {pid} 超时未退（不强杀）")
    ctypes.windll.kernel32.CloseHandle(h)
    time.sleep(0.8)   # 等文件句柄释放


def _stage_dir(plan, base):
    d = plan.get("staging") or os.path.join(base, "_update_staging")
    return d


def _zip_prefix(zf):
    """zip 根目录名（portable zip 是 '点歌台/...'）。"""
    roots = {n.split("/")[0] for n in zf.namelist() if "/" in n}
    return (list(roots)[0] + "/") if len(roots) == 1 else ""


def _run(plan, base, log):
    pid = plan.get("pid")
    if pid:
        _wait_exit(pid, log)

    zip_path = plan.get("zip") or ""
    staging = _stage_dir(plan, base)
    whitelist = plan.get("whitelist") or []

    # ① 校验 zip（SHA256 尽力：worker 下载时已核过 digest；这里 size 兜底）
    if not os.path.exists(zip_path):
        log("❌ 下载包不存在，更新取消（现版本不变）")
        return
    expect = int(plan.get("size") or 0)
    actual = os.path.getsize(zip_path)
    if expect and actual != expect:
        log(f"❌ zip 大小不符 期望{expect} 实际{actual}，更新取消")
        return
    log(f"zip 校验通过: {actual/1024/1024:.1f} MB")

    # ② 解压到暂存
    shutil.rmtree(staging, ignore_errors=True)
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            log(f"❌ zip 损坏于 {bad}，更新取消")
            return
        prefix = _zip_prefix(zf)
        names = zf.namelist()
        total = len(names)
        done = 0
        for info in zf.infolist():
            rel = info.filename[len(prefix):] if prefix else info.filename
            if not rel:
                continue
            dst = os.path.normpath(os.path.join(staging, rel))
            if not dst.startswith(os.path.normpath(staging) + os.sep):
                continue                      # zip-slip 防呆
            if info.is_dir():
                os.makedirs(dst, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with zf.open(info) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            done += 1
            if done % 2000 == 0:
                log(f"解压进度 {done}/{total}")
    log(f"解压完成（{done} 个文件）")

    # 版本一致性：staging 的 version.py 必须与 marker 的 tag 一致，防错包
    sv = os.path.join(staging, "_internal", "version.py")
    if os.path.exists(sv):
        try:
            txt = open(sv, "r", encoding="utf-8").read()
            if str(plan.get("tag", "")).lstrip("v") not in txt:
                log("❌ 包内版本号与目标版本不符，更新取消")
                return
        except Exception:
            pass

    # ③ 第一遍：拷成 .new / 直接落位（失败=干净放弃，原封不动）
    # douyin_sign 特例：只覆盖壳文件（sign_runner.js/package.json），
    # 绝不整目录替换——用户的 sign.js 在里面，碰都不许碰。
    # 主 exe 特例：worker 自己就是它（冻结版），运行中不能动——
    # 改走"改名腾位"：旧 exe rename→.bak（Windows 允许重命名运行中 exe），
    # 再把 staging 的新 exe copy2 到原位。worker 代码已在内存，不受影响。
    targets = []        # (src, dst, item) 走 .new 通道的目录/杂项
    EXE_NAME = "点歌台.exe"
    for item in whitelist:
        src = os.path.join(staging, item)
        dst = os.path.join(base, item)
        if not os.path.exists(src):
            log(f"⚠️ 包内缺 {item}，跳过该项")
            continue
        if item == "douyin_sign":
            for shell in ("sign_runner.js", "package.json"):
                s2 = os.path.join(src, shell)
                if os.path.exists(s2):
                    targets.append((s2, os.path.join(dst, shell), f"douyin_sign\\{shell}"))
            continue
        if item == EXE_NAME and getattr(sys, "frozen", False):
            continue    # 稍后专门处理
        targets.append((src, dst, item))
    try:
        for src, dst, item in targets:
            tmp = dst + ".new"
            if os.path.isdir(dst):
                shutil.rmtree(tmp, ignore_errors=True)
            elif os.path.exists(tmp):
                os.remove(tmp)
            if os.path.isdir(src):
                shutil.copytree(src, tmp)
            else:
                shutil.copy2(src, tmp)
        log("第一遍拷贝 .new 完成")
    except Exception as e:
        for _s, dst, item in targets:
            tmp = dst + ".new"
            if os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
            elif os.path.exists(tmp):
                os.remove(tmp)
        log(f"❌ 拷贝失败: {e}，更新放弃（现版本不变）")
        return

    # ④ 第二遍：快速换名。每项在"旧→.bak 成功"后才登记 moved，
    # 保证回滚语义：登记过的项删 dst（必为新版）再还原 .bak；
    # 未登记的项（step A 就失败）dst 还是完好的旧版，绝不碰。
    moved = []
    try:
        for src, dst, item in targets:
            tmp = dst + ".new"
            bak = dst + ".bak"
            if os.path.isdir(dst):
                shutil.rmtree(bak, ignore_errors=True)
            elif os.path.exists(bak):
                os.remove(bak)
            if os.path.exists(dst):
                os.rename(dst, bak)
                moved.append((dst, bak))
            os.rename(tmp, dst)
        log("第二遍换名完成，清 .bak")
        for dst, bak in moved:
            try:
                if os.path.isdir(bak):
                    shutil.rmtree(bak, ignore_errors=True)
                elif os.path.exists(bak):
                    os.remove(bak)
            except Exception:
                pass
    except Exception as e:
        log(f"❌ 换名失败: {e}，开始回滚")
        for dst, bak in reversed(moved):
            try:
                if os.path.isdir(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                elif os.path.exists(dst):
                    os.remove(dst)
                if os.path.isdir(bak) or os.path.exists(bak):
                    os.rename(bak, dst)
            except Exception as re_:
                log(f"⚠️ 回滚 {dst} 失败: {re_}（保留 .bak 请手动恢复）")
        # 清掉所有未轮到的 .new 残留（覆盖全部 targets，不只是登记项）
        for src, dst, item in targets:
            t = dst + ".new"
            try:
                if os.path.isdir(t):
                    shutil.rmtree(t, ignore_errors=True)
                elif os.path.exists(t):
                    os.remove(t)
            except Exception:
                pass
        return

    # ⑤ 主 exe 换身（仅冻结版）：Windows 不许删运行中的 exe，但允许改名。
    # 旧 exe rename→.bak（worker 进程凭镜像继续跑）→ 新 exe copy2 落原位。
    # .bak 由孙进程（跑在新 exe 里）等 worker 死后删——顺带真验证了新二进制。
    # 任一步失败：还原 .bak→原名，其余文件照常更新，下次更新会重试 exe。
    exe_bak = None
    if getattr(sys, "frozen", False):
        src_exe = os.path.join(staging, EXE_NAME)
        dst_exe = os.path.join(base, EXE_NAME)
        bak = dst_exe + ".bak"
        try:
            if os.path.exists(bak):
                os.remove(bak)
            if os.path.exists(dst_exe):
                os.rename(dst_exe, bak)
            landed = False
            try:
                shutil.copy2(src_exe, dst_exe)
                landed = True
            finally:
                if not landed:
                    try:
                        if os.path.exists(dst_exe):
                            os.remove(dst_exe)      # 清掉半包，给还原腾位
                        if os.path.exists(bak):
                            os.rename(bak, dst_exe)   # 新 exe 没落位，还原旧名
                    except Exception:
                        log(f"⚠️ 旧 exe 还原失败，遗留在 {bak}（可手动改回 点歌台.exe）")
                elif landed:
                    exe_bak = bak
            if landed:
                log("主 exe 换身成功（.bak 待孙进程清理）")
        except Exception as e:
            log(f"⚠️ 主 exe 换身失败: {e}（其余文件已更新）")

    # ⑥ 收尾：删 zip/暂存 → 换身孙进程 → 重启新版
    try:
        os.remove(zip_path)
    except Exception:
        pass
    shutil.rmtree(staging, ignore_errors=True)
    log("文件替换全部成功 ✅")
    if getattr(sys, "frozen", False):
        # 主程序是 console=False GUI exe：spawn 子进程天然无黑窗，不加 flags
        dst_exe = os.path.join(base, EXE_NAME)
        if exe_bak:
            try:
                subprocess.Popen([dst_exe, "--__upd_g__", str(os.getpid()), exe_bak],
                                 cwd=base, close_fds=True)
            except Exception as e:
                log(f"⚠️ 换身孙进程启动失败: {e}（{exe_bak} 请手动删）")
        try:
            subprocess.Popen([dst_exe], cwd=base, close_fds=True)
            log("新版已启动，worker 退出")
        except Exception as e:
            log(f"⚠️ 重启失败: {e}，请手动打开点歌台")
    else:
        log("开发环境：文件已替换，不自动重启宿主")


if __name__ == "__main__":
    sys.exit(main())
