# -*- coding: utf-8 -*-
"""自动更新：GitHub Releases 版本检查（只检查+引导下载，不自替换）。

为什么不做静默自替换：
  - exe 未签名，自动替换二进制 = 给杀软送把柄 + 供应链风险面；
  - onedir 结构 278MB，增量替换复杂度高，收益低（版本迭代慢）；
  - 用户点一下"下载新版"的摩擦，远小于"更新坏了没法直播"的损失。

行为：
  - check_latest()   查 GitHub Releases API 的 latest 标签（8s 超时，失败静默）
  - start_background_check(app)
      启动 20s 后静默查一次；有新版 → GUI 日志提示 + 弹窗（可复制下载地址）。
      同一版本每次进程只提醒一次。
  - manual_check(app)  菜单/按钮触发：无论有无新版都给明确反馈。

仓库地址留常量 REPO，fork 后改这一处即可。
"""

import json
import threading
import time
import urllib.request

import version

REPO = "OWNER/REPO"          # ← 开源发布时改成实际 GitHub 仓库
_API = "https://api.github.com/repos/{}/releases/latest".format(REPO)
_UA = {"User-Agent": "DianGeTai-Updater", "Accept": "application/vnd.github+json"}

_notified = {"ver": None}     # 同一版本只提醒一次


def fetch_latest(timeout=8):
    """返回 (tag字符串, html_url) 或 (None, None)。任何异常都吞掉返回 None。"""
    if "/" not in REPO or REPO.startswith("OWNER"):
        return None, None    # 还没配置仓库 → 功能自动休眠
    try:
        req = urllib.request.Request(_API, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").strip()
        url = (data.get("html_url") or "").strip()
        return tag, url
    except Exception:
        return None, None


def _notify(app, tag, url):
    """弹窗 + 日志。在主线程外调用安全（内部 root.after 回主线程）。"""
    msg = f"发现新版本 {tag}（当前 {version.DISPLAY}）\n\n下载地址已复制到剪贴板，浏览器打开即可。"
    try:
        app.root.after(0, lambda: _notify_ui(app, msg, url))
    except Exception:
        pass


def _notify_ui(app, msg, url):
    try:
        app.root.clipboard_clear(); app.root.clipboard_append(url)
    except Exception:
        pass
    try:
        from tkinter import messagebox
        messagebox.showinfo("点歌台 更新", msg)
    except Exception:
        pass


def start_background_check(app):
    """启动后延迟静默检查。不阻塞、不打扰（除非真有新版）。"""
    def _worker():
        time.sleep(20)
        tag, url = fetch_latest()
        if not tag:
            return
        if version.is_newer(tag, version.VERSION) and _notified["ver"] != tag:
            _notified["ver"] = tag
            app.log(f"🔔 检查到新版本 {tag}（当前 {version.DISPLAY}），弹窗查看下载地址")
            _notify(app, tag, url)
    threading.Thread(target=_worker, daemon=True).start()


def manual_check(app):
    """GUI 按钮触发的显式检查：任何结果都给反馈。"""
    def _worker():
        app.log("正在检查更新…")
        tag, url = fetch_latest(timeout=12)
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
            _notify(app, tag, url)
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
