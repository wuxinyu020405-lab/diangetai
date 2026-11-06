# -*- coding: utf-8 -*-
"""自动更新：GitHub Releases 检查 + 一键自动升级（v1.2.3 修复版）。

v1.2.1/v1.2.2 的教训（真机 WinError 5 实录，朋友装机实测）：更新器 worker
用 点歌台.exe 自己跑（--__upd__），它运行时从 _internal 加载自己的 python
DLL——**自己锁自己**。Windows 拒绝改名含被打开文件的目录 →
`_internal -> _internal.bak` 拒绝访问 → 换名失败回滚 → 永远更新不上。

v1.2.3 修法（Chrome/VSCode 同款套路）：换文件的活交给**外部进程**——
Windows 自带的 powershell.exe（在 System32，不加载安装目录任何文件，
天然不锁目标）。主程序只做：下载 → size+SHA256 校验 → 解压到 staging →
包内版本核对 → 写 marker → 生成 ps1 → spawn → 退出。ps1 等主进程死透后
按白名单 .bak 换名替换，失败回滚，成功后清理并重启新版，脚本自删。

安全口径不变：只走 GitHub 官方 HTTPS 资产；校验防半包防劫持；白名单外的
用户数据（config/credential/quota_state/music_cache/desktop_lyric/
sign.js/node/日志）碰都不碰；失败回退"复制下载地址"手动通道。
仓库地址留常量 REPO，fork 后改这一处即可。
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

import version
import settings

REPO = "wuxinyu020405-lab/diangetai"          # GitHub 仓库（owner/name）
_API = "https://api.github.com/repos/{}/releases/latest".format(REPO)
_UA = {"User-Agent": "DianGeTai-Updater", "Accept": "application/vnd.github+json"}

_notified = {"ver": None}      # 同一版本后台检查只提醒一次（每进程）
_downloading = {"running": False}
_offer_busy = {"v": False}     # v1.2.3：同一时刻只允许一个"发现新版"弹窗（修重复弹窗）

# 更新白名单：只有这些会被替换（相对 base 根）。其余用户文件碰都不碰。
WHITELIST = ["点歌台.exe", "_internal", "dotnet", "douyin_sign", "使用说明.md"]

EXE_NAME = "点歌台.exe"


def fetch_latest(timeout=8):
    """返回 (tag字符串, html_url) 或 (None, None)。任何异常都吞掉返回 None。"""
    tag, url, _ = fetch_latest_full(timeout)
    return tag, url


def fetch_latest_full(timeout=8):
    """返回 (tag, html_url, assets)；失败 (None, None, None)。"""
    if "/" not in REPO or REPO.startswith("OWNER"):
        return None, None, None    # 还没配置仓库地址 → 功能自动休眠
    try:
        req = urllib.request.Request(_API, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").strip()
        url = (data.get("html_url") or "").strip()
        assets = data.get("assets") or []
        return tag, url, assets
    except Exception:
        return None, None, None


def pick_portable_asset(assets, tag):
    """挑当前版本的便携 zip：名字含 tag 的 portable zip，退回任意 zip。"""
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    if not zips:
        return None
    want = tag.lower()
    for a in zips:
        if want and want in str(a.get("name", "")).lower():
            return a
    return zips[0]


def _sha256_of(path, block=1024 * 1024, cancelled=None):
    """算文件 SHA256。cancelled（threading.Event）置位时抛 _Cancelled 提前退出，
    免得用户点了取消还要等整包校验完（128MB 校验十几秒）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if cancelled is not None and cancelled.is_set():
                raise _Cancelled()
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class _Cancelled(Exception):
    """用户主动取消更新下载的内部信号（不是错误，不弹任何提示）。"""


class _ProgressDialog:
    """极简进度窗（tkinter，无 CTk）。任何创建失败都退回纯日志，绝不拦更新流程。

    v1.2.5 需求"下载窗口可控"：
    - 有「取消」按钮；点窗口 X 与点取消**完全等价**；
    - 取消只置位 self.cancelled，真正的收尾（中断读流 → 删 .part → 关窗）
      由下载线程的 finally 统一做，所以任何异常路径都不会留下残窗；
    - 取消后立刻显示"正在取消…"，不会看起来像点了没反应。
    """

    def __init__(self, app, title, on_cancel=None):
        self.app = app
        self.win = None
        self.lbl = None
        self.bar = None
        self.btn = None
        self.cancelled = threading.Event()   # 下载/解压/校验循环逐块检查
        self._closing = False
        try:
            import tkinter as tk
            from tkinter import ttk

            def _request_cancel():
                """取消 / 点 X：置位标志 + 按钮禁用防重复点，然后交给下载线程收尾。
                这里**不** destroy 窗口——窗口留着显示"正在取消"，由下载线程
                finally 里的 close() 真正销毁，确保任何路径窗口都必然消失。"""
                if self.cancelled.is_set():
                    return
                self.cancelled.set()
                try:
                    self.btn.configure(state="disabled", text="正在取消…")
                except Exception:
                    pass
                try:
                    self.lbl.configure(text="正在中断下载并清理残留…")
                except Exception:
                    pass
                if callable(on_cancel):
                    try:
                        on_cancel()
                    except Exception:
                        pass

            def _mk():
                if self._closing:
                    return
                w = tk.Toplevel(app.root)
                w.title(title)
                w.geometry("360x146")
                w.resizable(False, False)
                w.attributes("-topmost", True)
                tk.Label(w, text=title, font=("Microsoft YaHei", 10, "bold")).pack(pady=(12, 4))
                bar = ttk.Progressbar(w, length=320, mode="determinate", maximum=100)
                bar.pack(pady=2)
                lbl = tk.Label(w, text="准备中…", font=("Microsoft YaHei", 9))
                lbl.pack()
                btn = tk.Button(w, text="取消", width=10, command=_request_cancel)
                btn.pack(pady=(6, 8))
                w.protocol("WM_DELETE_WINDOW", _request_cancel)   # v1.2.5：X = 取消
                self.win, self.bar, self.lbl, self.btn = w, bar, lbl, btn
            app.root.after(0, _mk)
        except Exception:
            pass

    def set(self, pct, text):
        if self.cancelled.is_set():
            return    # 取消后不再刷新进度，把"正在取消…"的文案留着
        try:
            if self.bar is not None:
                self.app.root.after(0, lambda: (self.bar.configure(value=pct),
                                                self.lbl.configure(text=text)))
        except Exception:
            pass

    def close(self):
        """幂等关窗。调用点覆盖：成功、失败、取消、解压失败、校验失败、体积不符。"""
        if self._closing:
            return
        self._closing = True
        try:
            if self.win is None:
                return      # _mk 还没跑/创建失败 → 它自己看到 _closing 就不建了
            self.app.root.after(0, self._destroy)
        except Exception:
            pass

    def _destroy(self):
        try:
            if self.win is not None:
                self.win.destroy()
        except Exception:
            pass
        finally:
            self.win = None


# ════════════════ ps1 生成与 spawn（v1.2.3 核心）════════════════════════

def _psq(s):
    """PowerShell 单引号字符串转义。"""
    return "'" + str(s).replace("'", "''") + "'"


def _sanitize_tag(tag):
    """tag 会进 ps1 文本，只放行安全字符（防注入）。"""
    t = re.sub(r"[^A-Za-z0-9._+\-]", "", str(tag or ""))
    return t[:32]


_PS1_TEMPLATE = r'''
# DianGeTai auto-update worker (generated, self-deleting)
$ErrorActionPreference = 'Stop'
$base      = {base}
$staging   = {staging}
$marker    = {marker}
$exe       = {exe}
$ps1Self   = {self}
$pid0      = {pid}
$restart   = {restart}
$waitSec   = {wait}
$tag       = {tag}
$wl        = @({whitelist})
$log  = Join-Path $base '更新日志.txt'
$stat = Join-Path $base '_update_status.json'
function Log($m) {{ try {{ Add-Content -LiteralPath $log -Value ((Get-Date -Format 'HH:mm:ss') + ' ' + $m) -Encoding UTF8 }} catch {{}} }}
# v1.2.3：结局落盘给主程序看（v1.2.1 的失败只写日志、日志还被下次覆盖 →
# 用户只看到"重开还是旧版"，完全不知道发生了什么）
function Stat($status, $msg) {{
    try {{
        @{{ tag=$tag; status=$status; message=$msg; ts=(Get-Date).ToString('yyyy-MM-dd HH:mm:ss') }} |
            ConvertTo-Json -Compress | Set-Content -LiteralPath $stat -Encoding UTF8 -Force
    }} catch {{}}
}}
Log "=== 更新开始: $tag (ps1 worker) ==="

# 1) 等主进程退出。绝不强杀（可能正在直播）；超时=放弃，marker 保留下次启动重试
if ($pid0 -gt 0) {{
    $t = 0
    while ($t -lt $waitSec) {{
        if (-not (Get-Process -Id $pid0 -ErrorAction SilentlyContinue)) {{ break }}
        Start-Sleep -Seconds 1; $t++
    }}
    if (Get-Process -Id $pid0 -ErrorAction SilentlyContinue) {{
        Log "主进程 $pid0 在 $waitSec 秒内未退出，本次放弃（marker 保留，下次启动自动重试）"
        Stat 'stalled' "程序在 $waitSec 秒内没有退出，更新未开始（更新包已就绪，下次启动自动重试）"
        try {{ Remove-Item -LiteralPath $ps1Self -Force }} catch {{}}
        exit 1
    }}
}}
Start-Sleep -Milliseconds 1200    # 等文件句柄彻底释放

if (-not (Test-Path -LiteralPath $staging)) {{
    Log "staging 缺失（被清理/上次失败），作废 marker，下次启动重新走完整流程"
    Stat 'dropped' "更新暂存文件已丢失，本次更新作废（下次启动会重新下载）"
    try {{ Remove-Item -LiteralPath $marker -Force }} catch {{}}
    try {{ Remove-Item -LiteralPath $ps1Self -Force }} catch {{}}
    exit 1
}}

# 裸重命名：[IO.*]::Move 是单个 rename 系统调用——失败时源目录**原样不动**、
# 零复制垃圾。绝不用 Move-Item：它失败会回退成"边复制边删"，把旧安装也弄残
# （测试注入实证：锁定目录 Move-Item 后源目录文件散进嵌套 .bak）。
function Move-Hard($src, $dst) {{
    if (-not (Test-Path -LiteralPath $src)) {{ return }}
    if ((Get-Item -LiteralPath $src).PSIsContainer) {{
        [System.IO.Directory]::Move($src, $dst)
    }} else {{
        [System.IO.File]::Move($src, $dst)
    }}
}}

# 2) 白名单替换：旧→.bak，新→正式；douyin_sign 只换壳文件，sign.js 碰都不碰
# moved 项带 $mine 标记：True=dst 当时确实被换走（回滚可删现 dst 再还原 bak）；
# Move 当场失败=dst 还是完好旧版 → 回滚绝不碰它。
$moved = @()
$fail = $false
foreach ($item in $wl) {{
    $src = Join-Path $staging $item
    $dst = Join-Path $base $item
    if (-not (Test-Path -LiteralPath $src)) {{ Log "包内缺 $item，跳过"; continue }}
    $movedNow = $false
    $hadDst = (Test-Path -LiteralPath $dst)
    try {{
        if ($item -eq 'douyin_sign') {{
            if (-not $hadDst) {{ New-Item -ItemType Directory -Path $dst | Out-Null }}
            foreach ($sh in @('sign_runner.js','package.json')) {{
                $s2 = Join-Path $src $sh
                if (-not (Test-Path -LiteralPath $s2)) {{ continue }}
                $d2 = Join-Path $dst $sh
                if (Test-Path -LiteralPath $d2) {{
                    if (Test-Path -LiteralPath "$d2.bak") {{ Remove-Item -LiteralPath "$d2.bak" -Force }}
                    Move-Hard $d2 "$d2.bak"
                    $moved += ,@($d2, "$d2.bak", $true)
                }}
                Copy-Item -LiteralPath $s2 -Destination $d2 -Force
            }}
            Log "douyin_sign 壳已更新（sign.js 未碰）"
            continue
        }}
        if ($hadDst) {{
            if (Test-Path -LiteralPath "$dst.bak") {{ Remove-Item -LiteralPath "$dst.bak" -Recurse -Force }}
            Move-Hard $dst "$dst.bak"
            $movedNow = $true
            $moved += ,@($dst, "$dst.bak", $true)
        }}
        Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
        if (-not $movedNow -and -not $hadDst) {{ $moved += ,@($dst, "$dst.bak", $true) }}
        Log "已替换 $item"
    }} catch {{
        Log "FAIL 替换 $item : $_"
        # Move-Hard 失败=目录原样未动（原子调用零副作用），回滚不能碰它，
        # 也绝不能按"包内同名"去清理 dst——那会误删装机自带的旧文件。
        # 只有"原本没有 dst 的新项 copy 出残包"才登记 mine=True 供回滚整删。
        if (-not $movedNow -and -not $hadDst -and (Test-Path -LiteralPath $dst)) {{
            $moved += ,@($dst, "$dst.bak", $true)
        }}
        $fail = $true
        break
    }}
}}

if ($fail) {{
    Log "开始回滚"
    for ($i = $moved.Count - 1; $i -ge 0; $i--) {{
        $dst = $moved[$i][0]; $bak = $moved[$i][1]; $mine = $moved[$i][2]
        try {{
            if ($mine) {{
                if (Test-Path -LiteralPath $dst) {{ Remove-Item -LiteralPath $dst -Recurse -Force }}
                Move-Hard $bak $dst
            }}
        }} catch {{ Log "WARN 回滚 $dst 失败: $_（保留 .bak 可手动恢复）" }}
    }}
    Log "已回滚到旧版本（marker 保留，下次启动可重试或手动下载）"
    Stat 'rolled_back' "升级到 $tag 失败，已自动回滚到旧版本（你的设置和数据未受影响）。更新包已保留，下次启动会自动重试。"
    try {{ Remove-Item -LiteralPath $ps1Self -Force }} catch {{}}
    exit 1
}}

# 3) 成功：清 .bak → 清 marker/staging → 重启新版
foreach ($triple in $moved) {{
    try {{ if (Test-Path -LiteralPath $triple[1]) {{ Remove-Item -LiteralPath $triple[1] -Recurse -Force }} }} catch {{}}
}}
Get-ChildItem -LiteralPath $base -Filter '*.bak' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
foreach ($p in @($marker, $staging)) {{
    if ($p -and (Test-Path -LiteralPath $p)) {{ try {{ Remove-Item -LiteralPath $p -Recurse -Force }} catch {{}} }}
}}
Log "全部替换成功，清理完成"
Stat 'ok' "已成功升级到 $tag"
if ($restart) {{
    try {{ Start-Process -FilePath $exe -WorkingDirectory $base; Log "新版已启动" }}
    catch {{ Log "WARN 重启失败: $_（请手动打开点歌台）" }}
}}
Log "=== 更新完成 $tag ==="
try {{ Remove-Item -LiteralPath $ps1Self -Force }} catch {{}}
exit 0
'''


def write_ps1(base, plan):
    """按 plan 生成 ps1 到 %TEMP%，返回路径。plan 需含 tag/staging/marker/pid/restart。"""
    ps1 = os.path.join(tempfile.gettempdir(),
                       "dgt_update_%d.ps1" % (plan.get("pid") or os.getpid()))
    text = _PS1_TEMPLATE.format(
        base=_psq(base),
        staging=_psq(plan["staging"]),
        marker=_psq(plan["marker"]),
        exe=_psq(os.path.join(base, EXE_NAME)),
        self=_psq(ps1),
        pid=int(plan.get("pid") or 0),
        restart="$true" if plan.get("restart") else "$false",
        wait=int(plan.get("wait_timeout") or 120),
        tag=_psq(_sanitize_tag(plan.get("tag", ""))),
        whitelist=",".join(_psq(w) for w in (plan.get("whitelist") or WHITELIST)),
    )
    with open(ps1, "w", encoding="utf-8-sig") as f:   # BOM：PS 5.1 正确解析中文
        f.write(text)
    return ps1


def spawn_ps_worker(base, plan):
    """生成并拉起 ps1 worker。冻结版加 CREATE_NO_WINDOW 防黑窗一闪。"""
    ps1 = write_ps1(base, plan)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-WindowStyle", "Hidden", "-File", ps1]
    flags = 0x08000000 if getattr(sys, "frozen", False) else 0
    subprocess.Popen(cmd, cwd=tempfile.gettempdir(),
                     creationflags=flags, close_fds=True)
    return ps1


def extract_zip(zip_path, staging, log=None, cancelled=None):
    """解压便携 zip 到 staging（剥掉 zip 根目录名），返回文件数。zip-slip 防呆。

    v1.2.5：cancelled 置位时抛 _Cancelled 提前中止（解压 7000+ 文件要几秒，
    用户点了取消不该再等），staging 半成品由调用方统一清掉。"""
    if cancelled is not None and cancelled.is_set():
        raise _Cancelled()
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"zip 损坏于 {bad}")
        names = zf.infolist()
        roots = {i.filename.split("/")[0] for i in names if "/" in i.filename}
        prefix = (list(roots)[0] + "/") if len(roots) == 1 else ""
        for info in names:
            if cancelled is not None and cancelled.is_set():
                raise _Cancelled()
            rel = info.filename[len(prefix):] if prefix else info.filename
            if not rel:
                continue
            dst = os.path.normpath(os.path.join(staging, rel))
            if not dst.startswith(os.path.normpath(staging) + os.sep):
                continue
            if info.is_dir():
                os.makedirs(dst, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with zf.open(info) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            n += 1
            if log and n % 2000 == 0:
                log(f"解压中… {n}")
    return n


def _staging_version_ok(staging, tag):
    """staging 里 version.py 必须含目标版本号，防错包。缺失/不符都算不符。"""
    vp = os.path.join(staging, "_internal", "version.py")
    try:
        txt = open(vp, "r", encoding="utf-8").read()
    except OSError:
        return False
    return _sanitize_tag(tag).lstrip("vV") in txt


def resume_pending_update(marker_path):
    """启动时发现挂起 marker（上次选了"稍后"）→ 重新拉起 ps1 完成更新。
    返回 True=已拉起 worker（调用方应立即退出让位）；False=marker 作废照常启动。"""
    try:
        plan = json.load(open(marker_path, "r", encoding="utf-8"))
    except Exception:
        _rm(marker_path)
        return False
    base = settings.BASE_DIR
    if not os.path.isdir(plan.get("staging") or ""):
        # staging 没了（被清理/上次失败）→ 作废 marker，正常启动，
        # 后台检查会重新走完整下载流程
        _rm(marker_path)
        return False
    plan["pid"] = os.getpid()
    plan["restart"] = True
    plan["marker"] = marker_path
    try:
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)
        spawn_ps_worker(base, plan)
        return True
    except Exception:
        return False


# ════════════════ 下载 → 解压 → 弹窗确认 ════════════════

def download_and_apply(app, tag, asset, html_url):
    """线程入口：下载→校验→解压→写 marker→弹窗。失败回退手动下载。"""
    if _downloading["running"]:
        return
    _downloading["running"] = True

    def _worker():
        try:
            _do_download(app, tag, asset, html_url)
        except _Cancelled:
            pass            # v1.2.5：用户主动取消，不是失败，不弹任何提示
        except Exception as e:
            try:
                app.log(f"❌ 自动更新失败：{e}（可改用手动下载）")
            except Exception:
                pass
            _fallback_manual(app, html_url)
        finally:
            _downloading["running"] = False

    threading.Thread(target=_worker, daemon=True).start()


def _fallback_manual(app, url):
    def _ui():
        try:
            app.root.clipboard_clear(); app.root.clipboard_append(url or "")
            from tkinter import messagebox
            messagebox.showwarning("点歌台 更新",
                "自动更新没走通。\n下载地址已复制到剪贴板，浏览器打开手动下载即可。")
        except Exception:
            pass
    try:
        app.root.after(0, _ui)
    except Exception:
        pass


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ═════════ v1.2.5：下载加速 · 断点续传 · 重试（需求①）═════════
# 旧实现是"单连接、从头写到尾、失败即整包重下、只有 30s socket 读超时"，
# 边下边吐字节时永远不会超时 → 用户实测"特别慢、基本下载不成功"。
# 现在：能分段就 8 连接并发分段下发（每段独立 seek 写自己的区间，互不覆盖）；
#      中断后按各段已完成位置续传，不再从 0 开始；限次退避重试 + 整体时限兜底。
_SEG_MIN_SIZE = 4 * 1024 * 1024      # < 4MB 不分段：连接开销大于收益
_SEG_MAX = 8                          # 最多 8 个并发连接
_DL_TOTAL_TIMEOUT = 900               # 整体截止（秒），慢速吐字节也不会无限挂着
_DL_ATTEMPTS = 3                      # 最多尝试次数（含首轮）
_DL_CHUNK = 256 * 1024
_UA = "DianGeTai-Updater"


def _open_range(url, start=None, end=None, timeout=30):
    """打开 URL。给 start 时带 Range 头（end 为 None 表示"从 start 到末尾"）。"""
    headers = {"User-Agent": _UA, "Accept": "*/*"}
    if start is not None:
        headers["Range"] = "bytes=%d-%s" % (start, "" if end is None else end)
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=timeout)


def _probe_segments(url, total):
    """探测服务端是否支持 Range，返回分段数（1 = 不支持或包太小）。"""
    if not total or total < _SEG_MIN_SIZE:
        return 1
    try:
        with _open_range(url, 0, 0) as r:
            ok = getattr(r, "status", None) == 206
    except Exception:
        return 1
    if not ok:
        return 1
    return max(1, min(_SEG_MAX, total // _SEG_MIN_SIZE))


def _download_file(url, dest, total, dlg):
    """下载到 dest：分段并发 + 断点续传 + 重试 + 整体时限。

    取消（dlg.cancelled 置位）时抛 _Cancelled，并把 .part 残留清掉。
    成功后 dest 是完整文件，.part 消失。
    """
    part = dest + ".part"
    cancelled = dlg.cancelled
    deadline = time.time() + _DL_TOTAL_TIMEOUT

    # 上次已下满：直接归位
    if total and os.path.exists(part) and os.path.getsize(part) == total:
        os.replace(part, dest)
        return total

    nseg = _probe_segments(url, total)
    segs = []          # [[start, end_or_None], ...]
    if nseg > 1:
        step = total // nseg
        for i in range(nseg):
            s = i * step
            e = total - 1 if i == nseg - 1 else (i + 1) * step - 1
            segs.append([s, e])
        # 分段写需要固定长度文件，各段才能独立 seek
        with open(part, "ab") as f:
            f.truncate(total)
        done = [s - 1 for s, _ in segs]        # s-1 = 该段尚未开始
    else:
        # 单线程：支持从已有 .part 续传（.part 比目标小就是上次中断留下的）
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if not total:
            have = 0                            # 总长未知时不能续
        if have > total:
            have = 0
        if have:
            # 续传前必须确认服务端真的认 Range：有些源直接忽略 Range 返回 200 全量，
            # 那样从 have 往后写会把整包写错位 —— 宁可从 0 重下。
            try:
                with _open_range(url, 0, 0) as h:
                    if getattr(h, "status", None) != 206:
                        have = 0
            except Exception:
                have = 0
            if not have:
                _rm(part)
        if not os.path.exists(part):
            open(part, "ab").close()            # r+b 要求文件先存在
        segs.append([have, (total - 1) if total else None])
        done = [have - 1]

    lock = threading.Lock()
    errs = []

    def _run_seg(idx):
        start, end = segs[idx]
        try:
            if end is not None and start > end:
                return
            r = _open_range(url, start if start else 0, end)
            if start and getattr(r, "status", None) != 206:
                # 服务端无视 Range、回了 200 全量 → 必须从 0 写，否则整包错位
                start = 0
                with lock:
                    done[idx] = -1
            with r, open(part, "r+b", buffering=0) as f:
                f.seek(start)
                pos = start
                while True:
                    if cancelled.is_set():
                        raise _Cancelled()
                    if time.time() > deadline:
                        raise RuntimeError("下载超时（整体时限）")
                    want = _DL_CHUNK if end is None else min(_DL_CHUNK, end - pos + 1)
                    if want <= 0:
                        break
                    b = r.read(want)
                    if not b:
                        break
                    f.write(b)
                    pos += len(b)
                    with lock:
                        done[idx] = pos - 1
        except _Cancelled:
            raise
        except Exception as e:            # 交给主循环决定是否重试
            errs.append(e)

    def _got():
        with lock:
            return sum(max(0, d - s + 1) for (s, _), d in zip(segs, done))

    for attempt in range(1, _DL_ATTEMPTS + 1):
        errs.clear()
        threads = [threading.Thread(target=_run_seg, args=(i,), daemon=True)
                   for i in range(len(segs))]
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            if cancelled.is_set():
                break
            got = _got()
            pct = int(got * 100 / total) if total else 0
            dlg.set(pct, "%d / %d MB（%d%%）%s" % (
                got // 1024 // 1024, (total or 0) // 1024 // 1024, pct,
                ("· 第%d次重试" % attempt) if attempt > 1 else ""))
            if time.time() > deadline:
                errs.append(RuntimeError("下载超时（整体时限）"))
                break
            time.sleep(0.3)
        for t in threads:
            t.join(timeout=5)

        if cancelled.is_set():
            _rm(part)
            raise _Cancelled()

        finished = all((e is not None and d >= e) for (_, e), d in zip(segs, done))
        if finished:
            break
        if attempt < _DL_ATTEMPTS:
            time.sleep(2 * attempt)     # 退避 2s / 4s

    got = _got()
    if total and got < total:
        why = errs[-1] if errs else "连接异常"
        _rm(part)
        raise RuntimeError("下载中断（已下载 %d/%d MB，原因：%s）"
                           % (got // 1024 // 1024, total // 1024 // 1024, why))
    os.replace(part, dest)
    return os.path.getsize(dest)


def _do_download(app, tag, asset, html_url):
    name = "dgt_update.zip"   # 固定文件名：不用资产名，杜绝奇怪字符进路径/脚本
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release 资产缺下载地址")
    size = int(asset.get("size") or 0)
    digest = (asset.get("digest") or "").replace("sha256:", "").strip().lower()

    base = settings.BASE_DIR
    dl_dir = os.path.join(base, "_update_dl")
    os.makedirs(dl_dir, exist_ok=True)
    zip_path = os.path.join(dl_dir, name)
    staging = os.path.join(base, "_update_staging")

    dlg = _ProgressDialog(app, f"正在下载 {tag}",
                          on_cancel=lambda: app.log("⏹ 已请求取消更新下载"))
    app.log(f"⬇️ 开始下载新版（约 {size/1024/1024:.0f} MB）…")
    t0 = time.time()
    try:
        _download_file(url, zip_path, size, dlg)

        # 校验：大小 + SHA256
        actual = os.path.getsize(zip_path)
        if size and actual != size:
            _rm(zip_path)
            raise RuntimeError(f"下载包大小不符（期望 {size}，实际 {actual}），已丢弃")
        if digest:
            dlg.set(100, "校验 SHA256…（约十几秒）")
            app.log("校验 SHA256…")
            if _sha256_of(zip_path, cancelled=dlg.cancelled) != digest:
                _rm(zip_path)
                raise RuntimeError("SHA256 校验失败（包可能被劫持或损坏），已丢弃")
        app.log(f"✅ 下载校验通过（{time.time()-t0:.0f}s）")

        # 解压 + 包内版本核对（主程序退出前做完；ps1 只负责换文件，停机时间最短）
        dlg.set(100, "解压中…")
        n = extract_zip(zip_path, staging, log=app.log, cancelled=dlg.cancelled)
        if not _staging_version_ok(staging, tag):
            shutil.rmtree(staging, ignore_errors=True)
            _rm(zip_path)
            raise RuntimeError("包内版本号与目标不符，已丢弃（防错包）")
        _rm(zip_path)      # staging 就绪，zip 使命完成，省 128MB
        dlg.set(100, f"就绪：{n} 个文件已解压")
        app.log(f"✅ 解压完成（{n} 个文件），等待你确认重启")
        time.sleep(0.4)
    except _Cancelled:
        # 用户主动取消：不弹任何提示，清干净残留，保持现有版本可用
        _rm(zip_path)
        shutil.rmtree(staging, ignore_errors=True)
        app.log("⏹ 更新已取消（现有版本未做任何改动）")
        return
    finally:
        dlg.close()        # 幂等：成功/失败/取消/超时任何路径窗口都必然关闭

    # 写 marker（选"稍后"时它保证下次启动自动完成更新；立即模式确认时再改写）
    marker = os.path.join(base, "_update_pending.json")
    plan = {
        "tag": _sanitize_tag(tag),
        "staging": staging,
        "marker": marker,
        "whitelist": WHITELIST,
        "pid": 0,          # 稍后模式=不等任何进程；立即模式在确认时改写
        "restart": False,
    }
    with open(marker, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False)

    _prompt_restart(app, tag, marker, plan)


def _prompt_restart(app, tag, marker, plan):
    """主线程弹窗：立即重启（spawn ps1 后退出）或稍后（下次启动自动完成）。"""
    def _ui():
        from tkinter import messagebox
        ans = messagebox.askyesno(
            "准备就绪",
            f"新版本 {tag} 已下载、校验并解压完成。\n\n"
            "【是】立即重启完成更新（几秒钟，设置/登录/缓存全部保留）\n"
            "【否】稍后——下次启动点歌台时会自动完成更新")
        if ans:
            try:
                plan["pid"] = os.getpid()
                plan["restart"] = True
                with open(marker, "w", encoding="utf-8") as f:
                    json.dump(plan, f, ensure_ascii=False)
                spawn_ps_worker(settings.BASE_DIR, plan)
            except Exception as e:
                app.log(f"❌ 更新器启动失败：{e}")
                _fallback_manual(app, "")
                return
            _quit_for_update(app)
        else:
            app.log(f"⏳ 更新已就绪：{tag}。下次启动点歌台时自动完成安装。")
    try:
        app.root.after(0, _ui)
    except Exception:
        pass


def _quit_for_update(app):
    """显式落盘 → 杀残留子进程 → 立即退。ps1 worker 在等着接手。"""
    try:
        app.save_style_config()
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/IM", "node.exe", "/T"],
                       capture_output=True, creationflags=0x08000000, timeout=8)
    except Exception:
        pass
    os._exit(0)


def _offer_update(app, tag, url, assets):
    """发现新版后的统一入口。v1.2.3：全局 busy 防弹窗重复（后台检查+手动检查撞车）。"""
    if _offer_busy["v"]:
        try:
            app.log("ℹ️ 更新弹窗已在显示中，跳过重复弹窗")
        except Exception:
            pass
        return
    _offer_busy["v"] = True
    asset = pick_portable_asset(assets or [], tag)

    def _ui():
        try:
            from tkinter import messagebox
            if asset:
                ans = messagebox.askyesno(
                    "点歌台 更新",
                    f"发现新版本 {tag}（当前 {version.DISPLAY}）\n\n"
                    "【是】自动更新——下载并安装新版，你的设置/登录/Cookie/缓存全部保留，\n"
                    f"        下载约 {int(asset.get('size', 0))/1024/1024:.0f} MB，完成后自动重启\n"
                    "【否】只复制下载地址，我自己手动弄")
                if ans:
                    download_and_apply(app, tag, asset, url)
                    return
            try:
                app.root.clipboard_clear(); app.root.clipboard_append(url or "")
                messagebox.showinfo("点歌台 更新",
                                    f"新版本 {tag} 的下载地址已复制到剪贴板，浏览器打开即可。")
            except Exception:
                pass
        finally:
            _offer_busy["v"] = False
    try:
        app.root.after(0, _ui)
    except Exception:
        _offer_busy["v"] = False


def _status_path():
    return os.path.join(settings.BASE_DIR, "_update_status.json")


def _ps1_status_write(var_expr, value_expr):
    """生成 ps1 里写状态文件的片段（供 Python 侧拼进模板）。"""
    return ('try { @{tag=$tag; status=' + value_expr + '; ts=(Get-Date -Format '
            "'%Y-%m-%d %H:%M:%S')} | ConvertTo-Json -Compress | "
            'Set-Content -LiteralPath ' + var_expr + " -Encoding UTF8 -Force } catch {}")


def read_last_update_result(base=None):
    """v1.2.3：读上次更新结局（成功/失败原因），供启动时提示。
    返回 dict 或 None。读完即删（避免每次启动都提示同一件事）。"""
    p = os.path.join(base or settings.BASE_DIR, "_update_status.json")
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        os.remove(p)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _notified_state_path():
    return os.path.join(settings.BASE_DIR, "_update_notified.json")


def _load_notified_ver():
    """v1.2.3：已提醒过的版本号持久化。v1.2.1 的 _notified 只活在内存里 →
    程序重启后 20s 后台检查必然再弹一次，用户观感就是"隔一会儿又弹一个窗"。"""
    try:
        with open(_notified_state_path(), "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("ver") or None
    except Exception:
        return None


def _save_notified_ver(tag):
    try:
        with open(_notified_state_path(), "w", encoding="utf-8") as f:
            json.dump({"ver": tag, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, f,
                      ensure_ascii=False)
    except Exception:
        pass


def start_background_check(app):
    """启动后延迟静默检查。不阻塞、不打扰（除非真有新版）。"""
    _notified["ver"] = _load_notified_ver()   # 跨重启去重：已提醒过的版本不再弹

    def _worker():
        time.sleep(20)
        tag, url, assets = fetch_latest_full()
        if not tag:
            return
        if version.is_newer(tag, version.VERSION) and _notified["ver"] != tag:
            _notified["ver"] = tag
            _save_notified_ver(tag)           # 落盘：重启后不再重复提醒同一版本
            app.log(f"🔔 发现新版本 {tag}（当前 {version.DISPLAY}），弹窗可选自动更新")
            _offer_update(app, tag, url, assets)
    threading.Thread(target=_worker, daemon=True).start()


def manual_check(app):
    """GUI 按钮触发的显式检查：任何结果都给反馈。"""
    if _downloading["running"]:
        app.log("正在下载更新中，请稍候…")
        return
    if _offer_busy["v"]:
        app.log("ℹ️ 更新弹窗已在显示中")
        return

    def _worker():
        app.log("正在检查更新…")
        tag, url, assets = fetch_latest_full(timeout=12)
        if not tag:
            app.log("ℹ️ 检查更新失败（未配置仓库地址或网络不通）")
            try:
                app.root.after(0, lambda: _msgbox(app, "showwarning",
                          "检查更新", "暂时获取不到版本信息：\n网络不通，或本版本未配置更新源。"))
            except Exception:
                pass
            return
        if version.is_newer(tag, version.VERSION):
            app.log(f"🔔 新版本 {tag} 可用（当前 {version.DISPLAY}）")
            _offer_update(app, tag, url, assets)
        else:
            app.log(f"✅ 已是最新版本（{version.DISPLAY}，线上 {tag}）")
            try:
                app.root.after(0, lambda: _msgbox(app, "showinfo",
                          "检查更新", f"已是最新版本 {version.DISPLAY}"))
            except Exception:
                pass
    threading.Thread(target=_worker, daemon=True).start()


def _msgbox(app, kind, title, msg):
    try:
        from tkinter import messagebox
        getattr(messagebox, kind)(title, msg)
    except Exception:
        pass
