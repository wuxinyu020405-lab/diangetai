"""
程序入口（customtkinter 界面）
"""

import json
import os
import sys
import time

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
    for m in ("selenium.webdriver.edge.webdriver",
              "selenium.webdriver.chrome.webdriver",
              "selenium.webdriver.common.selenium_manager",
              "selenium.webdriver.remote.webdriver",
              "customtkinter", "pygame", "aiohttp", "blivedm",
              "qqmusic_api", "winsdk.windows.media.control"):
        try:
            importlib.import_module(m)
            out("  OK   " + m)
        except Exception as e:
            out(f"  FAIL {m}: {type(e).__name__}: {e}")
    out("")

    out("── 浏览器与驱动 ──")
    b = settings.get_default_browser_path()
    out("  浏览器: " + (str(b) if b else "未找到 Edge/Chrome"))
    if b:
        out("  浏览器版本: v" + str(settings.get_browser_version(b[1])))
    for name, drv in (("Edge", "msedgedriver.exe"), ("Chrome", "chromedriver.exe")):
        p = os.path.join(settings.BASE_DIR, drv)
        if os.path.exists(p):
            out(f"  {name} 驱动: 存在 v{settings.get_driver_version(p)}")
        else:
            out(f"  {name} 驱动: 不存在")
    out("")

    out("── 浏览器真实启动测试 ──")
    try:
        import browserlogin
        drv = browserlogin.start_driver(out)
        if drv:
            out("  OK 启动成功: " + str(drv.capabilities.get("browserVersion")))
            try:
                drv.quit()
                out("  OK 已关闭")
            except Exception as e:
                out("  警告 关闭异常: " + str(e))
        else:
            out("  FAIL 启动失败（见上方日志与 启动日志.txt）")
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
