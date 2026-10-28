"""
登录：Selenium 驱动浏览器完成 B站 / QQ音乐 扫码并抓取 Cookie
"""

from tkinter import messagebox, scrolledtext, filedialog, colorchooser, ttk
import threading
import urllib.parse
import urllib.request
import time
import json
import os
import sys
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from qqmusic_api import Client, Credential
import settings
import state

def start_driver(log_fn=None):
    """启动浏览器驱动：本地驱动优先（免联网，最稳），其次交给 Selenium Manager 自动管理。

    关键：所有启动尝试的真实异常都会通过 log_fn 打印到 OBS 日志区，便于定位
    究竟是驱动版本不匹配、驱动缺失还是浏览器缺失；--windowed 打包下 print 是看不到的，
    因此必须走 app_instance.log 才能让用户看到真正报错。
    """
    logs = []   # 收集本次启动的全部日志，失败时落盘给用户排错

    def _log(msg):
        logs.append(str(msg))
        if log_fn:
            try:
                log_fn(msg)
                return
            except Exception:
                pass
        try:
            print(msg)
        except Exception:
            pass

    edge_driver_path = os.path.join(settings.BASE_DIR, "msedgedriver.exe")
    chrome_driver_path = os.path.join(settings.BASE_DIR, "chromedriver.exe")
    browser = settings.get_default_browser_path()

    # ── 登录专用临时区（修"打包前后时好时坏"的根因，2026-10-28 实测）──
    # 浏览器驱动创建会话要在系统 TEMP 里建 user-data-dir；TEMP 被安全软件
    # 或权限策略拦截时即报 "cannot create temp dir"。改放程序目录下（与
    # music_cache 同性质），并显式传给浏览器绕开 TEMP 依赖。
    udd = os.path.join(settings.BASE_DIR, "_login_profile")
    login_tmp = os.path.join(settings.BASE_DIR, "_login_tmp")
    try:
        # 上次崩溃可能留下带锁的 profile，先尽力清掉（被占用则忽略，浏览器多半仍能接管）
        if os.path.isdir(udd):
            shutil.rmtree(udd, ignore_errors=True)
        os.makedirs(udd, exist_ok=True)
        os.makedirs(login_tmp, exist_ok=True)
        os.environ["TEMP"] = login_tmp
        os.environ["TMP"] = login_tmp
    except OSError:
        udd = None   # 建不了就退回默认行为

    def make_edge_opts():
        o = EdgeOptions()
        if browser and browser[0] == "edge":
            o.binary_location = browser[1]
        o.add_argument("--window-size=900,650")
        o.add_argument("--disable-gpu")
        o.add_argument("--no-sandbox")
        o.add_argument("--disable-dev-shm-usage")
        if udd:
            o.add_argument(f"--user-data-dir={udd}")
        try:
            o.add_experimental_option("excludeSwitches", ["enable-logging"])
        except Exception:
            pass
        return o

    def make_chrome_opts():
        o = ChromeOptions()
        if browser and browser[0] == "chrome":
            o.binary_location = browser[1]
        o.add_argument("--window-size=900,650")
        o.add_argument("--disable-gpu")
        o.add_argument("--no-sandbox")
        o.add_argument("--disable-dev-shm-usage")
        if udd:
            o.add_argument(f"--user-data-dir={udd}")
        try:
            o.add_experimental_option("excludeSwitches", ["enable-logging"])
        except Exception:
            pass
        return o

    if not browser:
        _log("[WARN] 未在常见安装路径找到 Edge/Chrome，将尝试由 Selenium Manager 自动处理。")
    else:
        _log(f"[INFO] 找到浏览器: {browser[0]} ({browser[1]})")

    # ── 本地驱动版本校验（关键：版本不匹配是"打不开浏览器"的首要原因）──
    edge_ok = os.path.exists(edge_driver_path)
    chrome_ok = os.path.exists(chrome_driver_path)
    if edge_ok:
        ok, detail = settings.check_driver_match("edge", edge_driver_path)
        _log("[INFO] Edge 本地驱动: " + detail)
        edge_ok = ok
    else:
        _log("[INFO] Edge 本地驱动: 未放置")
    if chrome_ok:
        ok, detail = settings.check_driver_match("chrome", chrome_driver_path)
        _log("[INFO] Chrome 本地驱动: " + detail)
        chrome_ok = ok
    else:
        _log("[INFO] Chrome 本地驱动: 未放置")

    # 尝试顺序：匹配的本地驱动 → 自动管理
    plans = [
        ("Edge(本地驱动)", edge_ok,
         lambda: webdriver.Edge(service=EdgeService(executable_path=edge_driver_path), options=make_edge_opts())),
        ("Edge(自动管理)", bool(browser and browser[0] == "edge") or True,
         lambda: webdriver.Edge(options=make_edge_opts())),
        ("Chrome(本地驱动)", chrome_ok,
         lambda: webdriver.Chrome(service=ChromeService(executable_path=chrome_driver_path), options=make_chrome_opts())),
        ("Chrome(自动管理)", True,
         lambda: webdriver.Chrome(options=make_chrome_opts())),
    ]

    last_err = None
    last_err_type = "None"
    tried = []
    for name, available, fn in plans:
        if not available:
            continue
        tried.append(name)
        try:
            drv = fn()
            _log("[OK] 已通过 " + name + " 成功启动浏览器。")
            return drv
        except Exception as e:
            last_err = e
            last_err_type = type(e).__name__
            _log("[WARN] " + name + " 启动失败: " + last_err_type + ": " + str(e).split("\n")[0][:200])

    # ── 全部失败：给出人话指引，而不是异常堆栈 ──
    _log("[ERR] 所有浏览器启动方式均失败")
    _log("")
    _log("══════════ 浏览器启动失败，请按以下步骤处理 ══════════")
    if not browser:
        _log("① 你的电脑没有装 Edge 或 Chrome。")
        _log("   请先安装其中一个（Win10/11 一般自带 Edge）。")
    else:
        _log(f"① 已检测到 {browser[0]}，但驱动无法启动它。")
        bv = settings.get_browser_version(browser[1])
        if bv:
            _log(f"   你的浏览器主版本: v{bv}")
            _log(f"   请下载 **v{bv}.x.x.x** 版本的驱动（版本号前两段要一致即可）")
            _log("   放到本程序(exe)所在目录，文件名必须是:")
            if browser[0] == "edge":
                _log("     msedgedriver.exe")
                _log("   下载入口（官方页面，选与你版本最接近的一条）:")
                _log("     https://developer.microsoft.com/microsoft-edge/tools/webdriver/")
                _log(f"     直链格式: https://msedgedriver.microsoft.com/{bv}.0.<补丁号>.<次版本>/edgedriver_win64.zip")
            else:
                _log("     chromedriver.exe")
                _log("   下载入口（Chrome for Testing 官方页面）:")
                _log("     https://googlechromelabs.github.io/chrome-for-testing/")
                _log(f"     选版本号以 {bv}. 开头的那一行，平台 win64")
    _log("② 放好驱动后，重启本程序再点登录。")
    _log("③ 若仍失败，把程序目录下的『启动日志.txt』发给开发者。")
    _log("═══════════════════════════════════════════════════")

    # 落盘日志（--windowed 下看不到控制台，这是唯一能收集现场的方式）
    try:
        body = "\n".join([
            "启动时间: " + time.strftime("%Y-%m-%d %H:%M:%S"),
            "程序目录: " + settings.BASE_DIR,
            "冻结环境: " + str(getattr(sys, 'frozen', False)),
            "Python: " + sys.version,
            "",
            "浏览器检测: " + (str(browser) if browser else "未找到"),
            "Edge 驱动存在: " + str(os.path.exists(edge_driver_path)),
            "Chrome 驱动存在: " + str(os.path.exists(chrome_driver_path)),
            "尝试过的方案: " + ", ".join(tried),
            "最后错误类型: " + last_err_type,
            "最后错误内容: " + (str(last_err).split(chr(10))[0][:500] if last_err else ""),
            "",
            "── 完整尝试日志 ──",
        ] + logs)
        settings.save_startup_log(body)
        _log(f"[INFO] 已写出排错日志: {os.path.join(settings.BASE_DIR, '启动日志.txt')}")
    except Exception:
        pass
    return None

# ================= B站 与 QQ音乐 登录 =================
def bilibili_auto_login(app_instance):
    app_instance.log("正在启动浏览器进行 B站 登录...")
    driver = start_driver(app_instance.log)
    if not driver:
        app_instance.log("❌ 浏览器启动失败，请检查是否安装了 Edge 或 Chrome")
        return

    try:
        driver.get("https://passport.bilibili.com/login")
        app_instance.log("👉 请在弹出浏览器中扫码/登录 B站，成功后保持浏览器打开。")
    except Exception as e:
        app_instance.log(f"❌ 打开 B站登录页面失败：{type(e).__name__}: {e}")
        try: driver.quit()
        except Exception:
            pass

        return

    def wait_for_bili():
        try:
            cookie_dict = {}
            logged_in = False
            for _ in range(180):
                time.sleep(1)
                try:
                    cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
                    if cookie_dict.get("SESSDATA") and cookie_dict.get("DedeUserID"):
                        logged_in = True
                        break
                    if "www.bilibili.com" not in driver.current_url:
                        driver.get("https://www.bilibili.com/")
                        time.sleep(1)
                        cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
                        if cookie_dict.get("SESSDATA") and cookie_dict.get("DedeUserID"):
                            logged_in = True
                            break
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")


            if not logged_in:
                app_instance.log("❌ 等待登录超时。")
                return

            cookie_names = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4"]
            cookie_str = "; ".join(f"{name}={cookie_dict[name]}" for name in cookie_names if cookie_dict.get(name))
            uid = str(cookie_dict.get("DedeUserID", "")).strip()
            app_instance.log("✅ 已读取 B站登录 Cookie，正在自动查询直播间号...")

            common_headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0", "Referer": "https://live.bilibili.com/"}
            room_id = ""
            endpoints = [
                "https://api.live.bilibili.com/xlive/web-ucenter/v1/bind/get_live_info",
                f"https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld?mid={uid}"
            ]
            for url in endpoints:
                try:
                    req = urllib.request.Request(url, headers=common_headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode())
                        payload = data.get("data") or {}
                        candidates = [payload.get("room_id"), payload.get("roomid"), payload.get("room_info", {}).get("room_id")]
                        candidate = next((str(x) for x in candidates if x not in (None, "", 0, "0")), "")
                        if data.get("code") == 0 and candidate:
                            room_id = candidate
                            break
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")


            config = {}
            if os.path.exists(settings.CONFIG_FILE):
                try:
                    with open(settings.CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
                except Exception:
                    pass

            config["bili_cookie"] = cookie_str
            if room_id: config["room_id"] = room_id

            with open(settings.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)

            if room_id:
                app_instance.log(f"✅ 自动获取直播间号成功：{room_id}")
                result_message = f"B站 Cookie 和直播间号均已保存。\n直播间号：{room_id}\n\n请关闭并重新打开软件以应用配置。"
            else:
                app_instance.log("❌ 未能自动获取直播间号，请手动在 config.json 中填写 room_id。")
                result_message = "Cookie 已保存，但未能自动获取直播间号。请手动在 config.json 中填写 room_id。"

            app_instance.root.after(0, lambda: app_instance.update_account_status())
            app_instance.root.after(0, lambda msg=result_message: messagebox.showinfo("B站登录结果", msg))

        except Exception as e:
            app_instance.log(f"❌ B站登录处理失败：{type(e).__name__}: {e}")
        finally:
            try: driver.quit()
            except Exception:
                pass


    threading.Thread(target=wait_for_bili, daemon=True).start()

def qq_scan_login(app_instance):
    app_instance.log("正在启动浏览器登录 QQ音乐...")
    driver = start_driver(app_instance.log)
    if not driver:
        app_instance.log("❌ 浏览器启动失败")
        return

    driver.get("https://y.qq.com")
    app_instance.log("👉 请在浏览器中扫码登录 QQ音乐。")

    def wait_for_qq():
        for _ in range(120):
            time.sleep(1)
            try:
                cookies = driver.get_cookies()
                cookie_dict = {c['name']: c['value'] for c in cookies}
                musicid_str = cookie_dict.get('uin', '').lstrip('oO0')
                musickey = cookie_dict.get('qm_keyst') or cookie_dict.get('qqmusic_key') or cookie_dict.get('p_skey')
                if musicid_str and musickey:
                    global qq_credential
                    state.qq_credential = Credential(musicid=int(musicid_str), musickey=musickey)
                    settings.save_credential(state.qq_credential)
                    app_instance.log("✅ 扫码成功！已绑定 VIP QQ 账号。")
                    app_instance.root.after(0, lambda: app_instance.update_account_status())
                    driver.quit()
                    return
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

        driver.quit()
    threading.Thread(target=wait_for_qq, daemon=True).start()
