"""
程序入口（customtkinter 界面）
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


def _setup_dotnet_for_webview():
    """打包环境下把 .NET Desktop 运行时相关信息准备好。

    pywebview 的 configure_coreclr() 用 __file__ 定位自带 runtimeconfig，
    但在 PyInstaller 的解压目录（_MEIPASS）里可能取不到正确路径，
    导致 coreclr 起得来却没有 WindowsDesktop 共享框架 → 报
    "Could not load file or assembly 'System.Windows.Forms'"。

    这里主动做两件事：
      ① 指到包内自带的 pywebview-runtimeconfig.json（若存在）
      ② 设 DOTNET_ROOT 到真实 dotnet 安装位置，让 hostfxr 能找到共享框架
    """
    try:
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        cfg = os.path.join(base, "webview", "lib", "pywebview-runtimeconfig.json")
        if os.path.exists(cfg):
            os.environ.setdefault("PYTHONNET_CORECLR_RUNTIME_CONFIG", cfg)

        # DOTNET_ROOT：优先 x64 子目录（ARM64 上的 x64 Python 需要它），
        # 否则用标准 Program Files\dotnet
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        for cand in (os.path.join(pf, "dotnet", "x64"), os.path.join(pf, "dotnet")):
            if os.path.isdir(cand):
                os.environ.setdefault("DOTNET_ROOT", cand)
                os.environ.setdefault("DOTNET_ROOT_X64", cand)
                break
    except Exception:
        pass


_setup_dotnet_for_webview()

import customtkinter as ctk

import mainapp
import musiclib
import settings
import state


def launch_main_app(config):
    # 根窗口必须是 ctk.CTk（普通 tk.Tk 不支持 CTk 的配色参数）
    root = ctk.CTk()
    state.app = mainapp.MusicApp(root, config)
    root.mainloop()


def run_selftest():
    """自检模式：验证打包产物完整性（selenium 动态模块、浏览器驱动）。
    用法: 点歌台.exe --selftest
    结果同时打印并写入 自检报告.txt，方便用户直接发回排错。"""
    import importlib

    lines = []

    def out(m):
        print(m)
        lines.append(str(m))

    out("═══ 点歌台 自检报告 ═══")
    out("时间: " + time.strftime("%Y-%m-%d %H:%M:%S"))
    out("程序目录: " + settings.BASE_DIR)
    out("冻结环境(frozen): " + str(getattr(sys, "frozen", False)))
    out("Python: " + sys.version.split()[0])
    out("")

    out("── 关键模块导入 ──")
    for m in ("webview", "clr", "pythonnet",
              "customtkinter", "pygame", "aiohttp", "blivedm",
              "qqmusic_api", "winsdk.windows.media.control"):
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
    settings.load_credential()

    if "--selftest" in sys.argv:
        run_selftest()
        try:
            input("\n按回车键退出...")
        except Exception:
            time.sleep(8)
        sys.exit(0)

    if os.path.exists(settings.CONFIG_FILE):
        with open(settings.CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        launch_main_app(config_data)
    else:
        launch_main_app({"room_id": "", "bili_cookie": "", "qqmusic_path": ""})
