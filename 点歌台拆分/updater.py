# -*- coding: utf-8 -*-
"""检查更新（v1.2.9.3 改造版）：只查版本号，不再由程序下载/安装自己。

发现新版时，版本号旁边出现一个「⬆ 下载 vX」按钮，点一下就用**系统默认浏览器**
打开 Setup 安装包的直链——GitHub 资产响应带 Content-Disposition: attachment，
浏览器会自己开始下载，没有中间确认页、不用手选版本。装包交给 Setup 安装程序
（它已有"优雅请退已运行旧版 → 写文件"的逻辑）。

为什么砍掉旧的自动更新（教训，别再走回头路）：
- v1.2.1~v1.2.9.2 是"程序下载 zip → 起外部 PowerShell 进程替换自己 → 退出 →
  重启"。链路太长：分段下载/续传/校验/解压/staging/marker/ps1/换名/回滚，
  任何一环断（网络、杀软拦、文件锁、用户点了稍后）用户看到的就是
  "点了没反应 / 重开还是旧版"，排查成本极高。真机已多次证实跑不通。
- 现在只做两件事：① 读 GitHub 最新 release 的 tag；② 有新版就显示链接。
  不下载、不解压、不替换、不写 marker、不留后台进程 —— 没有任何一步会失败到
  让程序起不来。

安全口径：只读 GitHub 官方 HTTPS API；打开的地址只来自该 release 的资产链接
（官方域名），不做任何本地文件操作（除清理旧版残留）。

仓库地址留常量 REPO，fork 后改这一处即可。
"""

import json
import os
import shutil
import threading
import time
import urllib.request
import webbrowser

import settings
import version

REPO = "wuxinyu020405-lab/diangetai"          # GitHub 仓库（owner/name）
_API = "https://api.github.com/repos/{}/releases/latest".format(REPO)
_UA = {"User-Agent": "DianGeTai-Updater", "Accept": "application/vnd.github+json"}

# 旧版自动更新留下、现已无意义的运行期残留（清理用，别删用户自己的东西）
_LEGACY_DIRS = ("_update_staging", "_update_dl")
_LEGACY_FILES = ("_update_pending.json", "_update_status.json", "_update_notified.json")

_checking = {"v": False}          # 同一时刻只跑一次检查（后台 + 手动撞车防重复）
_link = {"app": None}             # 已挂接的界面（界面层建完控件后登记）

# 本次检查到的新版本信息（按钮点下去就用它）
_latest = {"tag": None, "release_url": "", "setup_url": "", "direct": False}


# ════════════════ 查版本（唯一的网络动作）════════════════

def fetch_latest(timeout=8):
    """返回 (tag字符串, html_url) 或 (None, None)。任何异常都吞掉返回 None。"""
    tag, url, _ = fetch_latest_full(timeout)
    return tag, url


def fetch_latest_full(timeout=8):
    """返回 (tag, html_url, assets)；失败 (None, None, None)。"""
    if "/" not in REPO or REPO.startswith("OWNER"):
        return None, None, None      # 还没配置仓库地址 → 功能自动休眠
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


def pick_setup_asset(assets, tag):
    """挑新版 Setup 安装包（.exe 结尾）。

    实际资产名形如 `diangetai-Setup-v1.2.9.2.exe`（另有 portable.zip，绝不能用）。
    优先级：名字含本次 tag 且含 setup → 含 tag → 含 setup → 任一 exe。
    没有 exe 资产时返回 None，调用方退回打开发布页。
    """
    exes = [a for a in (assets or [])
            if str(a.get("name", "")).lower().endswith(".exe")]
    if not exes:
        return None
    want = str(tag or "").strip().lower().lstrip("v")

    def name_of(a):
        return str(a.get("name", "")).lower()

    tagged = [a for a in exes if want and want in name_of(a)] if want else []
    for group in (tagged, exes):
        for a in group:
            if "setup" in name_of(a):
                return a
    return (tagged or exes)[0]


def _set_latest(tag, release_url, assets):
    """把本次查到的版本信息存好，并算出按钮要打开的地址。"""
    asset = pick_setup_asset(assets or [], tag)
    direct_url = str((asset or {}).get("browser_download_url") or "").strip()
    url = direct_url or (release_url or "")     # 兜底：没 setup 资产就打开发布页
    _latest.update({
        "tag": tag,
        "release_url": release_url or "",
        "setup_url": url,
        "direct": bool(direct_url),
    })
    return dict(_latest)


def latest_info():
    """当前已知的新版本信息（调试/自检用）。"""
    return dict(_latest)


# ════════════════ 打开默认浏览器下载（核心）════════════════

def open_in_default_browser(url):
    """用系统默认浏览器打开 url。

    webbrowser.open 在 Windows 上走系统注册表里的默认浏览器（= 双击链接的同一个
    ShellExecute），浏览器收到 `Content-Disposition: attachment` 会自动开始下载。
    失败再退回 os.startfile（同样等价于双击链接）。返回 True/False。
    """
    if not url:
        return False
    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception:
        pass
    if os.name == "nt" and hasattr(os, "startfile"):
        try:
            os.startfile(url)      # type: ignore[attr-defined]
            return True
        except Exception:
            pass
    return False


def open_setup_download(app=None):
    """「⬆ 下载」按钮的回调：直接把 setup 直链交给默认浏览器。"""
    url = str(_latest.get("setup_url") or "").strip()
    tag = _latest.get("tag") or ""
    if not url:
        _log(app, "⚠️ 还没有拿到下载地址，请先点「检查更新」")
        return False
    ok = open_in_default_browser(url)
    if ok:
        if _latest.get("direct"):
            _log(app, "🌐 已交给默认浏览器下载 " + (tag or "新版") +
                      " 安装包（看浏览器下载进度，完成后双击安装即可）")
        else:
            _log(app, "🌐 已在默认浏览器打开 " + (tag or "最新版") +
                      " 发布页（这次没找到 Setup 资产，请在页里点 Setup 安装包）")
    else:
        _log(app, "❌ 没能调起默认浏览器，请手动打开：" + url)
    return ok


# ════════════════ 界面上的「⬆ 下载」按钮（同一个位置替换「检查更新」）════════════════

def register_update_link(app):
    """界面层建好按钮后调用。若检查结果先到，这里立刻补一次显示。"""
    _link["app"] = app
    if _latest.get("tag") and version.is_newer(_latest["tag"], version.VERSION):
        _show_link(app, _latest["tag"])
    else:
        _hide_link(app)


def _show_link(app, tag):
    """把「检查更新」换成「⬆ 下载 vX」——复用同一个位置，顶栏不会变宽挤掉别的按钮。"""
    if app is None:
        app = _link.get("app")
    if app is None:
        return
    text = "⬆ 下载 " + (str(tag or "").strip() or "新版")

    def _ui():
        try:
            btn = getattr(app, "btn_update_link", None)
            chk = getattr(app, "btn_check_update", None)
            if btn is None:
                return
            btn.configure(text=text)
            if chk is not None:
                try:
                    chk.pack_forget()
                except Exception:
                    pass
            try:
                btn.pack(side="left")
            except Exception:
                pass
        except Exception:
            pass
    _after(app, _ui)


def _hide_link(app):
    """没有新版：隐藏下载按钮，恢复「检查更新」。"""
    if app is None:
        app = _link.get("app")
    if app is None:
        return

    def _ui():
        try:
            btn = getattr(app, "btn_update_link", None)
            chk = getattr(app, "btn_check_update", None)
            if btn is not None:
                try:
                    btn.pack_forget()
                except Exception:
                    pass
            if chk is not None:
                try:
                    chk.pack(side="left")
                except Exception:
                    pass
        except Exception:
            pass
    _after(app, _ui)


# ════════════════ 检查入口 ════════════════

def start_background_check(app):
    """启动后静默检查一次：先清旧版残留，20 秒后查版本。有新版只亮按钮 + 写日志，
    **绝不弹窗**（用户要的是安静出现一个链接，不是被弹窗打断）。"""
    def _worker():
        try:
            removed = cleanup_legacy_update_files()
            if removed:
                _log(app, "🧹 已清理旧版自动更新残留：" + "、".join(removed))
        except Exception:
            pass
        time.sleep(20)
        _check(app, timeout=8, manual=False)

    threading.Thread(target=_worker, daemon=True).start()


def manual_check(app):
    """GUI「检查更新」按钮：任何结果都给反馈（用户主动点的，必须有回音）。"""
    if _checking["v"]:
        _log(app, "正在检查更新中，请稍候…")
        return

    def _worker():
        _check(app, timeout=12, manual=True)

    threading.Thread(target=_worker, daemon=True).start()


def _check(app, timeout=8, manual=False):
    """真正的检查逻辑：查版本 → 新版显示下载按钮 / 无新版隐藏。"""
    if _checking["v"]:
        return
    _checking["v"] = True
    try:
        if manual:
            _log(app, "正在检查更新…")
        tag, release_url, assets = fetch_latest_full(timeout=timeout)
        if not tag:
            if manual:
                _log(app, "ℹ️ 检查更新失败（网络不通或更新源未配置）")
                _msgbox(app, "showwarning", "检查更新",
                        "暂时获取不到版本信息：\n网络不通，或本版本未配置更新源。")
            return

        if version.is_newer(tag, version.VERSION):
            info = _set_latest(tag, release_url, assets)
            tip = ("用默认浏览器下载 Setup 安装包" if info["direct"]
                   else "打开发布页（本次没找到 Setup 资产）")
            _log(app, "⬆ 发现新版本 " + tag + "（当前 " + version.DISPLAY +
                      "）：点「⬆ 下载」，浏览器直接开始下载，完成后双击安装")
            _show_link(app, tag)
            if manual:
                _msgbox(app, "showinfo", "发现新版本",
                        "新版本 " + tag + " 可用（当前 " + version.DISPLAY + "）。\n\n"
                        "点版本号旁的「⬆ 下载」按钮即可" + tip +
                        "；浏览器会自动开始下载，不需要再确认什么。")
        else:
            _latest.update({"tag": None, "release_url": "", "setup_url": "", "direct": False})
            _hide_link(app)
            if manual:
                _log(app, "✅ 已是最新版本（" + version.DISPLAY + "，线上 " + tag + "）")
                _msgbox(app, "showinfo", "检查更新",
                        "已是最新版本 " + version.DISPLAY)
    except Exception as e:
        _log(app, "⚠️ 检查更新异常：" + str(e))
    finally:
        _checking["v"] = False


# ════════════════ 旧版残留清理 ════════════════

def cleanup_legacy_update_files(base=None):
    """删掉旧版自动更新留下的运行期垃圾（staging 目录、下载目录、marker、状态文件）。

    只动这几项：全是旧更新器自己生成的临时物，不含任何用户数据（配置/歌单/缓存/
    凭据都不在这里）。返回实际删掉的名单，便于写日志。"""
    base = base or settings.BASE_DIR
    removed = []
    for name in _LEGACY_DIRS:
        p = os.path.join(base, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                if not os.path.exists(p):
                    removed.append(name)
        except Exception:
            pass
    for name in _LEGACY_FILES:
        p = os.path.join(base, name)
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed.append(name)
        except Exception:
            pass
    return removed


# ════════════════ 小工具 ════════════════

def _after(app, fn):
    """切到界面线程执行（app.root 不存在时安全跳过，测试里可用假对象）。"""
    try:
        app.root.after(0, fn)
    except Exception:
        pass


def _log(app, msg):
    try:
        app.log(msg)
    except Exception:
        pass


def _msgbox(app, kind, title, msg):
    def _ui():
        try:
            from tkinter import messagebox
            getattr(messagebox, kind)(title, msg)
        except Exception:
            pass
    _after(app, _ui)
