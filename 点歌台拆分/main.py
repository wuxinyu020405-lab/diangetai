"""
程序入口（PySide6 + qfluentwidgets 界面）
"""

import json
import os
import sys
import time

# ★ 必须在任何 pywebview / pythonnet 导入之前设置。
# 打包（PyInstaller）环境下，pythonnet 的默认 netfx 加载器无法从解压临时
# 目录里解析 Python.Runtime.dll（.NET Framework 程序集加载限制），
# 报 "Failed to resolve Python.Runtime.Loader.Initialize"。
# 实测改用 coreclr 即恢复正常（源码运行与打包运行均已验证）。
os.environ.setdefault("PYTHONNET_RUNTIME", "coreclr")

# CI/管道环境下英文 Windows 默认编码(cp1252)编不了本文件的中文 print，
# 直接 UnicodeEncodeError 崩溃（CI Run#10 实测：stdout 被重定向时炸在启动
# 第一行）。环境变量为时已晚（stdout 已按 locale 绑定），必须运行时 reconfigure。
# GUI 程序 print 只是日志副作用，UTF-8+replace 无害且防炸。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── v1.2.5：`--quit` 外部优雅退出通道（覆盖升级用）──────────────────
# 安装包要把已运行的点歌台"体面关掉"，不能靠用户在托盘右键，更不能强杀丢配置。
# 通道 = 命名事件 state.QUIT_EVENT_NAME：本分支只置位事件，真正退出由已运行
# 实例自己走 quit_app（落盘 → 停托盘 → 清 node 子进程 → 退出）。
# 本进程置位后立即退出，且放在所有重导入（Qt / pygame / webview）之前，
# 启动开销只有解释器本身。
# 注意：这**不改变**"用户点 X 只缩托盘"的既有行为——只有外部显式调用才触发。
def _signal_running_instance_quit():
    """置位退出事件并等已运行实例退干净。

    返回 0 = 已通知（或本来就没有实例在跑），1 = 等实例退出超时。
    事件由 mainapp._start_quit_watcher 创建；没有实例时 OpenEventW 失败，
    首次安装（程序还没跑过）走的就是这条路径。
    """
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    import state
    kernel32 = ctypes.windll.kernel32
    EVENT_MODIFY_STATE = 0x0002
    SYNCHRONIZE = 0x00100000
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, state.QUIT_EVENT_NAME)
    if not h:
        return 0
    try:
        kernel32.SetEvent(h)
    finally:
        kernel32.CloseHandle(h)
    # 等实例真退干净再返回：轮询单实例互斥体是否还存在（最多 15 秒），
    # 免得调用方（安装包 / 脚本）刚发完信号就去动安装目录。
    for _ in range(60):
        hm = kernel32.OpenMutexW(SYNCHRONIZE, False, state.APP_MUTEX_NAME)
        if not hm:
            return 0
        kernel32.CloseHandle(hm)
        time.sleep(0.25)
    return 1


if "--quit" in sys.argv:
    sys.exit(_signal_running_instance_quit())


def _setup_dotnet_for_webview():
    """把 .NET 运行时位置准备好，让 coreclr 能找到 WindowsDesktop 共享框架。

    优先级（关键：包内自带的运行时优先，保证"目标机器无需预装 .NET"）：
      ① 程序目录下的 dotnet/ —— 分发包内置的 .NET 6 运行时
      ② 系统 Program Files\\dotnet —— 开发机环境
      x64 子目录优先（ARM64 上的 x64 Python 需要它）。

    同时把 pywebview 的 runtimeconfig 指对：它的 configure_coreclr() 用
    __file__ 定位，在 PyInstaller 环境（_MEIPASS）下可能取不到正确路径，
    会导致 coreclr 起来了却没有 WindowsDesktop 框架 →
    "Could not load file or assembly 'System.Windows.Forms'"。
    """
    try:
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        cfg = os.path.join(base, "webview", "lib", "pywebview-runtimeconfig.json")
        if os.path.exists(cfg):
            os.environ.setdefault("PYTHONNET_CORECLR_RUNTIME_CONFIG", cfg)

        # ① 包内自带的 dotnet（自定义安装布局：<程序目录>/dotnet）
        app_dirs = []
        if getattr(sys, "frozen", False):
            app_dirs.append(os.path.dirname(sys.executable))
        else:
            app_dirs.append(os.path.dirname(os.path.abspath(__file__)))
        for ad in app_dirs:
            cand = os.path.join(ad, "dotnet")
            if os.path.isdir(os.path.join(cand, "shared")):
                os.environ["DOTNET_ROOT"] = cand
                os.environ["DOTNET_ROOT_X64"] = cand
                return

        # ② 系统安装的 dotnet
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        for cand in (os.path.join(pf, "dotnet", "x64"), os.path.join(pf, "dotnet")):
            if os.path.isdir(cand):
                os.environ.setdefault("DOTNET_ROOT", cand)
                os.environ.setdefault("DOTNET_ROOT_X64", cand)
                break
    except Exception:
        pass


_setup_dotnet_for_webview()

import mainapp
import musiclib
import settings
import state


# ── 单实例锁 ─────────────────────────────────────────────────────
# 命名互斥体（会话级，随进程生死，崩溃自动释放，无需清理文件锁）。
# 二次启动：弹提示并尝试把已有窗口带到前台，然后静默退出。
# 不锁 = 用户开两个实例 → 端口顺延到 8081 两份弹幕，OBS 源只连其一，
# 表现为"点歌时灵时不灵"，极难排查。
_instance_mutex = None


def _acquire_single_instance():
    global _instance_mutex
    if os.name != "nt":
        return True   # 非 Windows（开发调试）不锁
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    ERROR_ALREADY_EXISTS = 183
    # Local\ = 当前登录会话内互斥（普通权限可建）。
    # 不用 Global\：那需要管理员权限，普通用户下 CreateMutex 会失败返回 NULL，
    # 导致下面的"创建失败→放行"分支触发，锁彻底失效。单实例只需同会话互斥。
    # v1.2.5：名字收敛到 state.APP_MUTEX_NAME——安装包 点歌台.iss 的 AppMutex
    # 用的就是这个字符串，两边必须逐字一致。
    _instance_mutex = kernel32.CreateMutexW(None, False, state.APP_MUTEX_NAME)
    if not _instance_mutex:
        return True   # 创建失败（如无权限建 Global）→ 放行，宁多不少
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    return True


def _wake_existing_instance():
    """R-28：二次启动时唤回已运行实例。返回 True=已送达唤醒信号。

    走命名事件 SHOW_EVENT_NAME，让**那个实例自己**在 Qt 主线程里 show 窗口。

    旧做法（v1.2.2 起）是就地 EnumWindows 找标题后 ShowWindow(SW_SHOW)：
    窗口缩在托盘时是 Qt 的 hide() 状态，别的进程用裸 Win32 强行显示，
    Qt 不知情、不重绘 → 用户看到的是一块**白屏死窗口**，只能任务管理器强杀
    （R-28 用户实测反馈）。所以从 R-28 起不再对隐藏窗口强显示。
    """
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    EVENT_MODIFY_STATE = 0x0002
    SYNCHRONIZE = 0x00100000
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, state.SHOW_EVENT_NAME)
    if not h:
        return False        # 老版本实例没有唤醒通道
    try:
        kernel32.SetEvent(h)
    finally:
        kernel32.CloseHandle(h)
    # 顺带把（若存在的）可见窗口置前，纯粹是"锦上添花"：只在窗口本来就可见时
    # 才 SetForegroundWindow，绝不对隐藏窗口做 ShowWindow。
    try:
        _lift_visible_window_only()
    except Exception:
        pass
    return True


def _lift_visible_window_only():
    """只对**当前可见**的已运行实例窗口置前（不解除隐藏，不会白屏）。"""
    import ctypes
    user32 = ctypes.windll.user32
    target = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
    def _cb(hwnd, _l):
        nonlocal target
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.startswith("点歌台控制台"):
            target = hwnd
            return False
        return True

    user32.EnumWindows(_cb, 0)
    if target:
        SW_RESTORE = 9
        user32.ShowWindow(target, SW_RESTORE)   # 只处理最小化，可见窗口安全
        user32.SetForegroundWindow(target)
        return True
    return False


def _bring_existing_window_front():
    """尽力把已运行实例的主窗口置前；找不到就算了，不报错。返回是否找到。

    ⚠️ R-28 起仅作为**老版本实例**（没有 SHOW_EVENT_NAME 唤醒通道）的兜底路径，
    且只敢对"当前可见"的窗口操作。对隐藏窗口强显示 = 白屏死窗（见上）。
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        target = None

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
        def _cb(hwnd, _l):
            nonlocal target
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value.startswith("点歌台控制台"):
                target = hwnd
                return False
            return True

        user32.EnumWindows(_cb, 0)
        if target:
            user32.ShowWindow(target, SW_RESTORE)
            user32.SetForegroundWindow(target)
            return True
    except Exception:
        pass
    return False


def _show_already_running():
    """二次启动时的模态提示。tkinter 独立小进程式用法：
    隐藏根窗 → messagebox → 销毁。调用方负责随后的 sys.exit。"""
    import tkinter as _tk
    from tkinter import messagebox as _mb
    _r = _tk.Tk()
    _r.withdraw()
    _mb.showinfo("点歌台", "点歌台已经在运行了。\n\n"
                           "请在任务栏或屏幕右下角托盘找到它的窗口；\n"
                           "若找不到（异常残留），请打开任务管理器结束\n"
                           "「点歌台」后再重新打开。")
    _r.destroy()


def launch_main_app(config):
    # R-15：界面换成 PySide6 + qfluentwidgets（qtapp.py）。
    # 这里只负责建 Qt 应用并把 MusicApp 挂上去；业务逻辑仍在 mainapp。
    import qtapp

    def _make(win):
        state.app = mainapp.MusicApp(win, config)
        return state.app

    return qtapp.run(config, _make)


def run_selftest():
    """自检模式：验证打包产物完整性（关键模块导入、WebView2、内嵌浏览器）。
    用法: 点歌台.exe --selftest
    结果同时打印并写入 自检报告.txt，方便用户直接发回排错。"""
    import importlib

    lines = []

    def out(m):
        print(m)
        lines.append(str(m))

    out("═══ 点歌台 自检报告 ═══")
    import version as _ver
    out("版本: " + _ver.DISPLAY)
    out("时间: " + time.strftime("%Y-%m-%d %H:%M:%S"))
    out("程序目录: " + settings.BASE_DIR)
    out("冻结环境(frozen): " + str(getattr(sys, "frozen", False)))
    out("Python: " + sys.version.split()[0])
    out("")

    out("── 关键模块导入 ──")
    for m in ("webview", "clr", "pythonnet",
              "PySide6.QtWidgets", "qfluentwidgets", "pygame", "aiohttp", "blivedm",
              "qqmusic_api", "winsdk.windows.media.control",
              # v1.2.1：配置加密（漏打包 = 装完直接崩，必须自检拦住）
              "secretstore",
              # v1.2.2：系统托盘（漏装 = 点X直接崩，同样自检拦住）
              "tray", "pystray", "pystray._win32", "PIL", "PIL.Image", "PIL._tkinter_finder"):
        try:
            importlib.import_module(m)
            out("  OK   " + m)
        except Exception as e:
            out(f"  FAIL {m}: {type(e).__name__}: {e}")
    out("")

    out("── 浏览器环境 ──")
    b = settings.get_default_browser_path()
    out("  默认浏览器: " + (str(b) if b else "未找到 Edge/Chrome"))
    # WebView2 Runtime（pywebview 依赖它，Win11 自带 / Win10 多数已有）
    try:
        import winreg
        guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        pv = None
        for hive, path in (
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
            (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"),
        ):
            try:
                with winreg.OpenKey(hive, path) as k:
                    v, _ = winreg.QueryValueEx(k, "pv")
                    if v and v != "0.0.0.0":
                        pv = v
                        break
            except FileNotFoundError:
                continue
        out("  WebView2 Runtime: " + (f"已安装 v{pv}" if pv else "❌ 未安装（登录会失败）"))
    except Exception as e:
        out("  WebView2 Runtime 检测异常: " + str(e))
    # 打包进来的 WebView2 程序集
    try:
        import webview as _wv
        _lib = os.path.join(os.path.dirname(_wv.__file__), "lib")
        out("  webview/lib: " + ("存在" if os.path.isdir(_lib) else "❌ 缺失"))
        for f in ("Microsoft.Web.WebView2.Core.dll",
                  "Microsoft.Web.WebView2.WinForms.dll",
                  "pywebview-runtimeconfig.json"):
            out(f"    {f}: " + ("有" if os.path.exists(os.path.join(_lib, f)) else "❌ 无"))
    except Exception as e:
        out("  webview 检查异常: " + str(e))
    out("")

    out("── 内嵌浏览器启动测试 ──")
    try:
        import browserlogin
        browserlogin._patch_pywebview_for_thread()
        import webview as _wv2
        out("  OK pywebview 导入正常")
        # 尝试在子线程真起一个窗口（5 秒后自动关）
        import threading
        import time as _t
        res = {"ok": False, "err": None}

        def _probe():
            # ★ pywebview 检查的是"当前线程"的名字，必须在工作线程内部改名
            cur = threading.current_thread()
            old = cur.name
            try:
                cur.name = "MainThread"
                w = _wv2.create_window("自检", "about:blank", width=400, height=300)
                def _closer():
                    _t.sleep(4)
                    try: w.destroy()
                    except Exception: pass
                threading.Thread(target=_closer, daemon=True).start()
                _wv2.start(debug=False)
                res["ok"] = True
            except Exception as e:
                res["err"] = f"{type(e).__name__}: {e}"
            finally:
                try:
                    cur.name = old
                except Exception:
                    pass

        t = threading.Thread(target=_probe, daemon=True)
        t.start()
        t.join(timeout=30)
        if res["ok"]:
            out("  OK 内嵌浏览器窗口可正常创建与关闭")
        else:
            out("  FAIL " + str(res["err"]))
    except Exception as e:
        out("  FAIL 异常: " + type(e).__name__ + ": " + str(e))
    out("")
    out("═══ 自检结束 ═══")

    try:
        rp = os.path.join(settings.BASE_DIR, "自检报告.txt")
        with open(rp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print("\n[INFO] 报告已写入: " + rp)
    except Exception as e:
        print("写入报告失败:", e)


if __name__ == '__main__':
    # 启动时清理损坏文件
    print("[INFO] 启动时扫描缓存目录，清理损坏文件...")
    musiclib.clean_corrupted_files(settings.CACHE_DIR)

    # v1.2.1·需求6：把历史明文配置就地迁移为 DPAPI 加密文件（透明，失败保持原样）
    try:
        import secretstore
        for _p in (settings.CONFIG_FILE, settings.CREDENTIAL_FILE,
                   os.path.join(settings.BASE_DIR, "quota_state.json")):
            if secretstore.migrate_plaintext(_p):
                print(f"[INFO] 已加密迁移: {os.path.basename(_p)}")
    except Exception as _e:
        print(f"[WARN] 配置加密迁移异常（不影响使用）: {_e}")

    settings.load_credential()

    if "--selftest" in sys.argv:
        run_selftest()
        try:
            input("\n按回车键退出...")
        except Exception:
            time.sleep(8)
        sys.exit(0)

    try:
        import secretstore
        config_data = secretstore.read_json(settings.CONFIG_FILE, default=None)
    except Exception:
        config_data = None
    if not isinstance(config_data, dict):
        config_data = {"room_id": "", "bili_cookie": "", "qqmusic_path": ""}

    if not _acquire_single_instance():
        # R-28：优先走"唤醒事件"让已运行实例自己把窗口显示出来（Qt 主线程 show，
        # 不会白屏）。老版本实例没有这个通道时，只对可见窗口置前；窗口藏着又唤不醒
        # → 明确弹提示告诉用户，而不是把人家隐藏窗口强显成白屏死窗。
        woke = False
        try:
            woke = _wake_existing_instance()
        except Exception:
            woke = False
        if not woke:
            woke = _bring_existing_window_front()
        if not woke:
            try:
                _show_already_running()
            except Exception:
                pass   # 无桌面会话等极端情况：静默退出即可
        sys.exit(0)

    # v1.2.9.3：旧版"程序自己下载并替换自己"的续跑分支已整段拆除——
    # 现在点「⬆ 下载」由默认浏览器下 Setup 安装包，装包交给安装程序；
    # 启动时不再有 marker 让位、上次结局弹窗这类残留逻辑。
    launch_main_app(config_data)
