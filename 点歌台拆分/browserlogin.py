"""
登录（pywebview 内嵌浏览器版）

设计要点：
- 用 pywebview（WebView2 内嵌）替代 Selenium + 外部浏览器
- 登录窗口是主进程内的子窗口，随程序生死，**不会产生残留进程**
- Cookie 通过 window.get_cookies() 获取（含 HttpOnly）
- 保留原有的 Cookie 解析、直播间号查询、配置保存逻辑

注意：pywebview 的 GUI 循环必须在主线程，且一旦 start() 会阻塞。
因此登录窗口单独开一个线程 + 独立 GUI 不是一个好做法；
这里采用「登录时在后台线程创建一个独立 webview 窗口」的方案，
pywebview 6.x 支持在非主线程创建窗口后由主线程 start 的用法受限，
故采用更稳妥的：登录窗口复用主程序已经存在的 Tk 事件循环，
用 webview 的独立窗口 + 阻塞式 start（在主线程外的线程中运行，
WebView2 的 WinForms 后端允许这样做）。
"""

from tkinter import messagebox
import threading
import urllib.request
import urllib.parse
import time
import json
import os
import sys

import settings
import state

# pywebview 延迟导入：打包时若缺依赖，顶多登录不能用，不影响主程序启动
_webview = None
_webview_patched = False


def _patch_pywebview_for_thread():
    """让 pywebview 能在非主线程运行 —— 本程序的 Tk 已占用主线程。

    pywebview 6.x 有两处"主线程假设"，都可用轻量补丁绕过：
      ① threading.current_thread().name != 'MainThread' → 直接 raise
         这是纯名称检查，登录线程里临时改名即可；
      ② signal.signal(...) 只能在主线程调用 → 子线程里打桩成空操作。

    实测（WinForms + WebView2）：打桩后窗口正常显示，能读 URL 与 Cookie。
    若未来 pywebview 改成真正依赖主线程行为，此方案会失效，
    届时需改为「主线程托管登录窗口」架构。
    """
    global _webview_patched
    if _webview_patched:
        return
    try:
        import signal as _sig
        _orig_signal = _sig.signal

        def _safe_signal(signum, handler):
            try:
                return _orig_signal(signum, handler)
            except ValueError:
                return None

        _sig.signal = _safe_signal
        _webview_patched = True
    except Exception as e:
        print(f"[WARN] pywebview 线程适配失败: {e}")


def _get_webview():
    """延迟导入并做环境适配。"""
    global _webview
    if _webview is not None:
        return _webview
    _patch_pywebview_for_thread()
    import webview as _wv
    _webview = _wv
    return _webview


def _cookies_to_dict(ck):
    """把 pywebview `window.get_cookies()` 的返回值统一成 {name: value}。

    ★ 实测（pywebview master + 57/58 版本，WinForms/EdgeChromium）返回的是
      **list of SimpleCookie**，每个元素是一个只含**单个** Cookie 的 SimpleCookie，
      例如 `[SimpleCookie: buvid3='...'), SimpleCookie: _uuid='...'), ...]`。
      因此必须逐个展开每个 SimpleCookie 的 items()，不能去找 .name/.value 属性
      （SimpleCookie 没有这两个属性 —— 这曾经导致所有 Cookie 被静默丢弃）。
    另外也兼容：单个 SimpleCookie / 普通 dict / 带 name+value 的对象列表。
    """
    import http.cookies as _ck

    out = {}
    try:
        if ck is None:
            return out

        def _absorb(container):
            """把 SimpleCookie / dict / 带 name+value 的对象收进 out。"""
            if container is None:
                return
            if isinstance(container, (_ck.SimpleCookie, dict)) or hasattr(container, "items"):
                for k, v in container.items():
                    out[str(k)] = str(getattr(v, "value", v))
                return
            # 单个 Morsel
            if hasattr(container, "key"):
                out[str(container.key)] = str(getattr(container, "value", ""))
                return
            # 带 name/value 属性的对象
            name = getattr(container, "name", None) or getattr(container, "Name", None)
            val = getattr(container, "value", None)
            if val is None:
                val = getattr(container, "Value", None)
            if name:
                out[str(name)] = str(val if val is not None else "")

        if isinstance(ck, list):
            for item in ck:
                _absorb(item)
        else:
            _absorb(ck)
    except Exception as e:
        print(f"[WARN] Cookie 解析异常: {e}")
    return out


def _open_login_window(url, title, on_poll, timeout_sec=180, width=1100, height=800):
    """打开一个 pywebview 登录窗口，期间周期性调用 on_poll(cookie_dict)。
    返回 on_poll 的最终结果（非 None 表示成功）。

    ★ 必须在**调用方的当前线程**里执行 wv.start()（它会阻塞到窗口关闭）。
      本函数由 bilibili_auto_login / qq_scan_login 在登录线程中直接调用，
      调用前线程名会被临时改成 'MainThread' 以绕过 pywebview 的名称检查
      （见 _patch_pywebview_for_thread 的说明）。
    """
    wv = _get_webview()
    done = {"ok": False, "value": None}

    cur_thread = threading.current_thread()
    old_name = cur_thread.name
    try:
        # pywebview 的检查是 `current_thread().name != 'MainThread'`，纯名称判断
        cur_thread.name = "MainThread"
    except Exception:
        pass

    window = wv.create_window(title, url, width=width, height=height)

    def poll_loop():
        """轮询 Cookie，直到登录成功或超时。"""
        deadline = time.time() + timeout_sec
        try:
            # 等页面加载
            for _ in range(40):
                time.sleep(0.5)
                try:
                    cur = window.get_current_url()
                except Exception:
                    cur = None
                if cur and len(str(cur)) > 12:
                    break
            while time.time() < deadline:
                time.sleep(1.0)
                try:
                    ck = _cookies_to_dict(window.get_cookies())
                except Exception:
                    ck = {}
                try:
                    res = on_poll(ck)
                except Exception as e:
                    print(f"[WARN] on_poll 异常: {e}")
                    res = None
                if res:
                    done["ok"] = True
                    done["value"] = res
                    break
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    threading.Thread(target=poll_loop, daemon=True).start()
    try:
        wv.start(debug=False)      # 阻塞直到窗口关闭
    except Exception as e:
        print(f"[WARN] webview.start 异常: {type(e).__name__}: {e}")
        return None
    finally:
        try:
            cur_thread.name = old_name
        except Exception:
            pass
    return done["value"] if done["ok"] else None


# ================= B站登录 =================
def bilibili_auto_login(app_instance):
    """对外入口：在独立线程里跑，避免阻塞 Tk 主线程。"""
    threading.Thread(target=_bilibili_auto_login_worker, args=(app_instance,),
                     daemon=True).start()


def _bilibili_auto_login_worker(app_instance):
    app_instance.log("正在打开内嵌浏览器进行 B站 登录...")
    try:
        _get_webview()
    except Exception as e:
        app_instance.log(f"❌ 内嵌浏览器组件不可用: {type(e).__name__}: {e}")
        app_instance.log("   请检查 pywebview / WebView2 运行时是否安装")
        return

    state_buf = {"cookie_dict": {}}

    def on_poll(ck):
        """检查是否已登录。返回非空表示完成。"""
        state_buf["cookie_dict"] = ck
        if ck.get("SESSDATA") and ck.get("DedeUserID"):
            return True
        return None

    app_instance.log("👉 请在弹出窗口中扫码/登录 B站")
    ok = _open_login_window(
        "https://passport.bilibili.com/login",
        "B站登录 - 点歌台",
        on_poll,
        timeout_sec=180,
    )

    if not ok:
        app_instance.log("❌ 等待登录超时或窗口被关闭。")
        return

    cookie_dict = state_buf["cookie_dict"]
    cookie_names = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4"]
    cookie_str = "; ".join(f"{name}={cookie_dict[name]}" for name in cookie_names if cookie_dict.get(name))
    uid = str(cookie_dict.get("DedeUserID", "")).strip()
    app_instance.log("✅ 已读取 B站登录 Cookie，正在自动查询直播间号...")

    # ── 直播间号查询（逻辑与原版一致）──
    common_headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0",
                      "Referer": "https://live.bilibili.com/"}
    room_id = ""
    endpoints = [
        "https://api.live.bilibili.com/xlive/web-ucenter/v1/bind/get_live_info",
        f"https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld?mid={uid}",
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers=common_headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                payload = data.get("data") or {}
                candidates = [payload.get("room_id"), payload.get("roomid"),
                              payload.get("room_info", {}).get("room_id")]
                candidate = next((str(x) for x in candidates if x not in (None, "", 0, "0")), "")
                if data.get("code") == 0 and candidate:
                    room_id = candidate
                    break
        except Exception as e:
            print(f"[WARN] 查询直播间号失败: {e}")

    # ── 保存配置 ──
    config = {}
    if os.path.exists(settings.CONFIG_FILE):
        try:
            with open(settings.CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass
    config["bili_cookie"] = cookie_str
    if room_id:
        config["room_id"] = room_id
    try:
        with open(settings.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except Exception as e:
        app_instance.log(f"❌ 保存配置失败: {e}")
        return

    if room_id:
        app_instance.log(f"✅ 自动获取直播间号成功：{room_id}")
        result_message = (f"B站 Cookie 和直播间号均已保存。\n直播间号：{room_id}\n\n"
                          f"请关闭并重新打开软件以应用配置。")
    else:
        app_instance.log("❌ 未能自动获取直播间号，请手动在 config.json 中填写 room_id。")
        result_message = "Cookie 已保存，但未能自动获取直播间号。请手动在 config.json 中填写 room_id。"

    app_instance.root.after(0, lambda: app_instance.update_account_status())
    app_instance.root.after(0, lambda msg=result_message: messagebox.showinfo("B站登录结果", msg))


# ================= QQ音乐登录 =================
def qq_scan_login(app_instance):
    """对外入口：在独立线程里跑，避免阻塞 Tk 主线程。"""
    threading.Thread(target=_qq_scan_login_worker, args=(app_instance,),
                     daemon=True).start()


def _qq_scan_login_worker(app_instance):
    app_instance.log("正在打开内嵌浏览器登录 QQ音乐...")
    try:
        _get_webview()
    except Exception as e:
        app_instance.log(f"❌ 内嵌浏览器组件不可用: {type(e).__name__}: {e}")
        return

    found = {}

    def on_poll(ck):
        musicid_str = (ck.get("uin") or "").lstrip("oO0")
        musickey = ck.get("qm_keyst") or ck.get("qqmusic_key") or ck.get("p_skey")
        if musicid_str and musickey:
            found["musicid"] = musicid_str
            found["musickey"] = musickey
            return True
        return None

    app_instance.log("👉 请在弹出窗口扫码登录 QQ音乐")
    ok = _open_login_window("https://y.qq.com", "QQ音乐登录 - 点歌台",
                            on_poll, timeout_sec=120)

    if not ok:
        app_instance.log("❌ 等待 QQ音乐登录超时或窗口被关闭。")
        return

    try:
        from qqmusic_api import Credential
        state.qq_credential = Credential(musicid=int(found["musicid"]),
                                         musickey=found["musickey"])
        settings.save_credential(state.qq_credential)
        app_instance.log("✅ 扫码成功！已绑定 QQ 音乐账号。")
        app_instance.root.after(0, lambda: app_instance.update_account_status())
    except Exception as e:
        app_instance.log(f"❌ 保存 QQ音乐凭证失败: {type(e).__name__}: {e}")
