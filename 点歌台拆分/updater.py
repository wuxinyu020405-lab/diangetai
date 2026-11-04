# -*- coding: utf-8 -*-
"""自动更新：GitHub Releases 检查 + 一键自动升级（v1.2.1 需求 #19 拍板）。

行为分层：
  - fetch_latest_full()  查 Releases API（8~12s 超时，失败静默 (None,None,None)）
      返回 (tag, html_url, assets)；assets 里含 name/size/browser_download_url/digest
  - start_background_check(app)   启动 20s 后静默查一次；有新版 → 弹窗问"立即更新"
  - manual_check(app)  手动触发：无论结果都给明确反馈
  - 用户点【立即更新】→ download_and_apply(app, tag, asset)：
      后台线程下载 portable zip → size+SHA256 校验 → 写 _update_pending.json
      → 弹窗确认 → spawn 更新器 worker → 主程序落盘配置并 os._exit(0)
      更新器等旧进程退出后按白名单覆盖（不碰 config/credential/music_cache/
      sign.js/node），全成功才生效，失败自动回滚，然后重启新版。

安全口径（拍板记录）：只走 GitHub 官方 HTTPS 资产；校验 size+digest 防半包防劫持；
下载失败回退"复制下载地址"手动通道；未签名自我替换的杀软风险用户已知情。
仓库地址留常量 REPO，fork 后改这一处即可。
"""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import version
import settings

REPO = "wuxinyu020405-lab/diangetai"          # GitHub 仓库（owner/name）
_API = "https://api.github.com/repos/{}/releases/latest".format(REPO)
_UA = {"User-Agent": "DianGeTai-Updater", "Accept": "application/vnd.github+json"}

_notified = {"ver": None}     # 同一版本只提醒一次
_downloading = {"running": False}

# 更新白名单：只有这些会被替换（相对 base 根）。其余用户文件碰都不碰。
WHITELIST = ["点歌台.exe", "_internal", "dotnet", "douyin_sign", "使用说明.md"]


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
    """挑当前版本的便携 zip：名字含 tag 的 portable zip，退回任意 portable zip。"""
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    if not zips:
        return None
    want = tag.lower()
    for a in zips:
        if want and want in str(a.get("name", "")).lower():
            return a
    return zips[0]


def _sha256_of(path, block=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class _ProgressDialog:
    """极简进度窗（tkinter，无 CTk）。任何创建失败都退回纯日志，绝不拦更新流程。"""

    def __init__(self, app, title):
        self.app = app
        self.win = None
        self.lbl = None
        self.bar = None
        self._title = title
        try:
            import tkinter as tk
            from tkinter import ttk

            def _mk():
                w = tk.Toplevel(app.root)
                w.title(title)
                w.geometry("360x110")
                w.resizable(False, False)
                w.attributes("-topmost", True)
                tk.Label(w, text=title, font=("Microsoft YaHei", 10, "bold")).pack(pady=(12, 4))
                bar = ttk.Progressbar(w, length=320, mode="determinate", maximum=100)
                bar.pack(pady=2)
                lbl = tk.Label(w, text="准备中…", font=("Microsoft YaHei", 9))
                lbl.pack()
                w.protocol("WM_DELETE_WINDOW", lambda: None)   # 下载中不给关
                self.win, self.bar, self.lbl = w, bar, lbl
            app.root.after(0, _mk)
        except Exception:
            pass

    def set(self, pct, text):
        try:
            if self.bar is not None:
                self.app.root.after(0, lambda: (self.bar.configure(value=pct),
                                                self.lbl.configure(text=text)))
        except Exception:
            pass

    def close(self):
        try:
            if self.win is not None:
                self.app.root.after(0, self.win.destroy)
        except Exception:
            pass


def download_and_apply(app, tag, asset, html_url):
    """线程入口：下载→校验→写标记→spawn 更新器→退出。失败回退手动下载。"""
    if _downloading["running"]:
        return
    _downloading["running"] = True

    def _worker():
        try:
            _do_download(app, tag, asset, html_url)
        except Exception as e:
            app.log(f"❌ 自动更新失败：{e}（可改用手动下载）")
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


def _do_download(app, tag, asset, html_url):
    name = asset.get("name") or f"diangetai-{tag}-portable.zip"
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release 资产缺下载地址")
    size = int(asset.get("size") or 0)
    digest = (asset.get("digest") or "").replace("sha256:", "").strip().lower()

    base = settings.BASE_DIR
    dl_dir = os.path.join(base, "_update_dl")
    os.makedirs(dl_dir, exist_ok=True)
    zip_path = os.path.join(dl_dir, name)

    dlg = _ProgressDialog(app, f"正在下载 {tag}")
    app.log(f"⬇️ 开始下载 {name}（约 {size/1024/1024:.0f} MB）…")
    req = urllib.request.Request(url, headers={"User-Agent": "DianGeTai-Updater"})
    t0 = time.time()
    last_pct = -10
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(zip_path, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0) or size
            got = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                pct = int(got * 100 / total) if total else 0
                if pct - last_pct >= 5:
                    last_pct = pct
                    mb = got / 1024 / 1024
                    dlg.set(pct, f"{mb:.0f} / {total/1024/1024:.0f} MB（{pct}%）")
    except Exception:
        dlg.close()
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise RuntimeError("下载中断")

    # 校验：大小 + SHA256（digest 缺失时只校验大小并明示）
    actual = os.path.getsize(zip_path)
    if size and actual != size:
        dlg.close(); os.remove(zip_path)
        raise RuntimeError(f"下载包大小不符（期望 {size}，实际 {actual}），已丢弃")
    if digest:
        app.log("校验 SHA256…（大包约需十几秒）")
        got_hex = _sha256_of(zip_path)
        if got_hex != digest:
            dlg.close(); os.remove(zip_path)
            raise RuntimeError("SHA256 校验失败（包可能被劫持或损坏），已丢弃")
    dlg.set(100, f"下载完成，用时 {time.time()-t0:.0f}s")
    time.sleep(0.6)
    dlg.close()
    app.log(f"✅ {name} 下载并校验通过")

    # 写待更新标记（marker 先落盘：选"稍后"时它保证下次启动自动完成更新；
    # worker 只在用户确认"立即重启"后才 spawn——否则会出现 worker 干等
    # 90 秒把还在直播的主进程强杀的恶性时序）
    marker = os.path.join(base, "_update_pending.json")
    plan = {
        "tag": tag,
        "zip": zip_path,
        "staging": os.path.join(base, "_update_staging"),
        "whitelist": WHITELIST,
        "pid": os.getpid(),
    }
    with open(marker, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False)

    _prompt_restart(app, tag, marker)


def _spawn_worker(base, marker):
    """拉起更新器 worker（它自己等主进程退出再动手）。
    主程序是 console=False 的 GUI exe，spawn 的子进程天然无黑窗，不需要
    DETACHED/CREATE_NO_WINDOW 标志；子进程也不会因父进程退出而死（Windows
    默认无作业对象），worker 活得比主程序久。"""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--__upd__"]
    else:
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "autoupdater.py")]
    try:
        subprocess.Popen(cmd, cwd=base, close_fds=True)
        return True
    except Exception as e:
        try:
            os.remove(marker)
        except OSError:
            pass
        raise RuntimeError(f"更新器启动失败：{e}")


def _prompt_restart(app, tag, marker):
    """主线程弹窗：立即重启（spawn 更新器后退出）或稍后（下次启动自动完成）。"""
    def _ui():
        from tkinter import messagebox
        ans = messagebox.askyesno(
            "准备就绪",
            f"新版本 {tag} 已下载并校验完成。\n\n"
            "【是】立即重启完成更新（几秒钟，设置/登录/缓存全部保留）\n"
            "【否】稍后我自己关窗口——下次启动点歌台时会自动完成更新")
        if ans:
            try:
                _spawn_worker(settings.BASE_DIR, marker)
            except Exception as e:
                app.log(f"❌ {e}")
                return
            _quit_for_update(app)
        else:
            app.log(f"⏳ 更新已就绪：{tag}。下次启动点歌台时自动完成安装。")
    try:
        # 弹窗必须在主线程；本函数从下载线程调用
        app.root.after(0, _ui)
    except Exception:
        pass


def _quit_for_update(app):
    """显式落盘 → 杀残留子进程 → 立即退。更新器在等着接手。"""
    try:
        app.save_style_config()
    except Exception:
        pass
    # 兜底清 node 子进程（抖音签名是一次性子进程；此处清孤儿残留保险 #18 方向）
    try:
        subprocess.run(["taskkill", "/F", "/IM", "node.exe", "/T"],
                       capture_output=True, creationflags=0x08000000, timeout=8)
    except Exception:
        pass
    os._exit(0)


def _offer_update(app, tag, url, assets):
    """发现新版后的统一入口：问用户 立即自动更新 / 手动下载 / 忽略。"""
    asset = pick_portable_asset(assets or [], tag)

    def _ui():
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
    try:
        app.root.after(0, _ui)
    except Exception:
        pass


def start_background_check(app):
    """启动后延迟静默检查。不阻塞、不打扰（除非真有新版）。"""
    def _worker():
        time.sleep(20)
        tag, url, assets = fetch_latest_full()
        if not tag:
            return
        if version.is_newer(tag, version.VERSION) and _notified["ver"] != tag:
            _notified["ver"] = tag
            app.log(f"🔔 发现新版本 {tag}（当前 {version.DISPLAY}），弹窗可选自动更新")
            _offer_update(app, tag, url, assets)
    threading.Thread(target=_worker, daemon=True).start()


def manual_check(app):
    """GUI 按钮触发的显式检查：任何结果都给反馈。"""
    if _downloading["running"]:
        app.log("正在下载更新中，请稍候…")
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
