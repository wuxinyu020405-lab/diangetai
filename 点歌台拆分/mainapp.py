"""
主程序：业务逻辑与 asyncio worker 编排（界面在 qtapp，PySide6）
"""

import os
import sys
import threading
import time

import tkinter as tk          # 只为了 tk.END 这个常量（日志框 insert/see 的"末尾"哨兵）

import pygame              # init_audio_engine 建混音器要用
import settings
import state
import qtapp
import updater
import version
from qtshim import messagebox

# R-23：按职责拆出来的 6 个 mixin。方法都还挂在同一个 self 上，
# 这里只是把它们合回一个类，调用方（qtapp / updater / 回归脚本）一行不用改。
import app_danmaku
import app_download
import app_listener
import app_media
import app_player
import app_ui


# ================= 主程序类 =================
class MusicApp(app_download.DownloadMixin, app_player.PlayerMixin,
                app_media.MediaMixin, app_listener.ListenerMixin,
                app_ui.UiMixin, app_danmaku.DanmakuMixin):
    """点歌台主类。

    R-23：按职责拆成 6 个 mixin（下载 / 播放 / 媒体识别+歌词 / 监听 / 界面回调 /
    弹幕发送），这里只留类核心（__init__、setup_ui、log、托盘与退出）和总装。
    方法都还挂在同一个 self 上，调用点一行没改。
    """
    def __init__(self, root, config):
        self.root = root; self.config = config
        
        old_style = self.config.get("style_config", {})
        global style_config
        state.style_config = settings.merge_config(old_style, state.style_config)
            
        if not self.config.get("qqmusic_path"):
            auto_path = settings.find_qqmusic_path()
            if auto_path: self.config["qqmusic_path"] = auto_path

        self.audio_backend = "none"

        # R-26 问题3：窗口尺寸/位置统一由 qtapp 决定（默认居中最小高度）。
        # 这里原来写死 geometry("780x880")，在 Qt 版上会把 qtapp 设好的
        # "最小高度"覆盖成 880 → 用户看到的是比最小值高一截的窗口。
        self.root.title(f"控制台 - 房间 {self.config.get('room_id', '未配置')} - {version.DISPLAY}")
        self._set_window_icon()
        self._tray = None        # 惰性托盘对象；False=本机托盘不可用
        self._exiting = False
        self._quit_event = None  # v1.2.5：外部退出事件的句柄（安装器置位用）
        self._show_event = None  # R-28：外部唤窗事件的句柄（二次启动置位用）
        self._start_quit_watcher()   # v1.2.5：给安装包留一条"优雅退出"通道
        self._start_show_watcher()   # R-28：给二次启动留一条"合法唤窗"通道
        self.setup_ui()
        # v1.2.2·需求21：点 X = 缩到托盘（拍板方案 a）；真退出只走托盘菜单
        try:
            self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        except Exception:
            pass
        self.download_tasks = {}
        self.last_download_reason = None   # 需求9：单行结论的失败归因标记
        self.thread = threading.Thread(target=self.start_async_loop, daemon=True); self.thread.start()
        updater.start_background_check(self)   # 启动 20s 后静默检查一次更新
        self.root.after(3000, self._qm_tick)   # v1.2.2·队列管理页自动刷新

    def init_audio_engine(self):
        try:
            pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048)
            self.audio_backend = "pygame"
            self.log("✅ 内置无损音频引擎 (Pygame 稳定通道) 已就绪")
            self.update_engine_badge("✅ 驱动: Pygame 本地稳定版", "#2E7D32")
        except Exception as e:
            self.audio_backend = "none"
            self.log(f"❌ 音频通道初始化失败: {e}")
            self.update_engine_badge("❌ 音频驱动未就绪", "#C62828")

    def _set_window_icon(self):
        """标题栏/Alt+Tab 图标。打包版从 _MEIPASS 取（spec 已带 app.ico），
        源码版从模块目录取。找不到就安静跳过，用系统默认图标。"""
        try:
            base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
            ico = os.path.join(base, "app.ico")
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
        except Exception as e:
            print(f"[WARN] 窗口图标设置失败: {e}")

    # ═════════ 队列管理页（v1.2.2）═══════════════════════════════════
    # 线程约定：state.playlist / pending_requests 由 asyncio 线程读写，
    # 所有修改必须经 self.loop.call_soon_threadsafe 投递到 loop 线程执行；
    # 渲染只在 Tk 线程做（读快照跨线程仅做浅拷贝，展示数据无害竞态）。








    def request_pause(self, on):
        """v1.1·N1：显式设置暂停意图（弹幕【暂停】/【继续】与 GUI 共用）。
        语义（用户拍板）：只暂停当前这首歌的播放；下载与收队列照常。
        必须在 Tk 线程调用（弹幕侧用 root.after 编组过来）。"""
        if state.pause_event is None:
            self.log("ℹ️ 播放引擎还没就绪，暂无法暂停")
            return
        if on:
            if not state.current_song:
                self.log("ℹ️ 当前没有在播的歌（暂停只对正在播放的歌曲生效）")
                return
            if not state.pause_event.is_set():
                state.pause_event.set()
        else:
            # 无条件 clear：即使此刻没在播，解除意图也无害且符合"继续"预期
            state.pause_event.clear()

    def toggle_pause(self):
        """GUI 按钮入口：按当前实际状态取反。"""
        self.request_pause(not state.pause_event.is_set() if state.pause_event else True)

    def request_skip(self):
        """切歌：复用弹幕同一入口逻辑（Tk 线程 set asyncio.Event）。

        v1.2.9 修复：完全空闲时（没在播、队列也空）不接受切歌。
        原来空闲时点切歌会把 skip_event 置位，而 clear 只在播放循环里做，
        于是这个意图一直残留 —— 之后点第一首歌，刚开始播就被这里撞掉、
        表现为「点歌后自动切了一次歌」。
        """
        if not state.skip_event:
            return
        if state.current_song is None and not state.playlist:
            self.log("ℹ️ 当前没有在播的歌，忽略切歌")
            return
        if not state.skip_event.is_set():
            self.log("⏭️ 切歌！")
            state.skip_event.set()

    # ═════════ GUI 发弹幕（v1.2.4）═════════════════════════════════


    # ═════════ v1.2.6：弹幕发送器热刷新 / 设置即时生效 / 测试发送 ═════════



    # ═════════ v1.2.5：外部优雅退出通道（安装包覆盖升级用）══════════
    def _start_quit_watcher(self):
        """监听命名事件 state.QUIT_EVENT_NAME，收到就走 quit_app 真退出。

        为什么不用"关窗口"（WM_CLOSE）当通道：用户点 X 的既有语义是**缩托盘**，
        安装器（Restart Manager 之类）关窗口只会把它缩进托盘、进程还在，
        正是 v1.2.4 实测"安装时 GUI 关了却卡在托盘"的根因。
        独立事件通道把"用户点 X"和"安装器要求退出"彻底分开：
        - 用户点 X  → minimize_to_tray（不弹窗、不退出）
        - 安装器置位 → quit_app（落盘 → 停托盘 → 清 node 子进程 → 退出）
        """
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateEventW.restype = wintypes.HANDLE
            kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                              wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        except Exception:
            return

        def _watch():
            try:
                h = kernel32.CreateEventW(None, True, False, state.QUIT_EVENT_NAME)
                if not h:
                    return
                self._quit_event = h
                if kernel32.WaitForSingleObject(h, 0xFFFFFFFF) == 0:   # WAIT_OBJECT_0
                    try:
                        self.log("⏹ 收到外部退出请求（安装/升级），正在落盘并退出…")
                    except Exception:
                        pass
                    try:
                        self.root.after(0, self.quit_app)
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            threading.Thread(target=_watch, daemon=True).start()
        except Exception:
            pass

    # ═════════ R-28：外部唤窗通道（二次启动用）═════════════════════
    def _start_show_watcher(self):
        """监听命名事件 state.SHOW_EVENT_NAME，收到就在 **Qt 主线程**里把窗口
        正常显示出来。

        为什么必须走事件、不能让二次启动的进程直接 ShowWindow（旧做法）：
        实例缩托盘时窗口是 Qt 的 hide() 状态。别的进程用裸 Win32 SW_SHOW 强行
        显示，Qt 内部不知情、不触发重绘 → 屏幕上就是一块**白屏死窗口**（R-28
        用户实测：二次打开 exe 白屏彻底卡死）。由窗口自己的进程在主线程调
        showNormal/lift，才会走 Qt 完整的显示+重绘流程。
        """
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateEventW.restype = wintypes.HANDLE
            kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                              wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        except Exception:
            return

        def _watch():
            try:
                h = kernel32.CreateEventW(None, True, False, state.SHOW_EVENT_NAME)
                if not h:
                    return
                self._show_event = h
                while kernel32.WaitForSingleObject(h, 0xFFFFFFFF) == 0:   # WAIT_OBJECT_0
                    kernel32.ResetEvent(h)
                    if self._exiting:
                        return
                    try:
                        # 编组到 Qt 主线程再动窗口（与托盘菜单同一套规矩）
                        self.root.after(0, self.show_from_tray)
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            threading.Thread(target=_watch, daemon=True).start()
        except Exception:
            pass

    # ═════════ 系统托盘（v1.2.2 需求21）═════════════════════════════
    def minimize_to_tray(self):
        """点 X / 托盘"隐藏"时调用：缩进托盘，程序继续跑。
        托盘起不来（缺库/老系统）→ 退回普通最小化，绝不崩、绝不拦关闭。

        v1.2.5（用户口径）：点 X 全程**不出现任何对话框、任何气泡/通知**，
        直接静默缩进托盘。真退出只走托盘菜单「退出点歌台」或外部退出事件。
        """
        # R-27：先看用户选的是"缩托盘"还是"直接退出"（默认缩托盘）
        try:
            action = str((self.config or {}).get("close_action") or "tray").lower()
        except Exception:
            action = "tray"
        if action == "quit":
            self.log("⏹ 关闭行为=直接退出，正在退出…")
            self.quit_app()
            return

        if self._tray is None:
            try:
                import tray
                self._tray = tray.Tray(self)
            except Exception as e:
                self.log(f"⚠️ 托盘模块不可用: {e}（本次改为最小化）")
                self._tray = False
        if self._tray is False:
            self._fallback_minimize()
            return
        if not self._tray.start():
            self._tray = False
            self._fallback_minimize()
            return
        self.root.withdraw()                       # 藏起窗口但进程活着

    def _fallback_minimize(self):
        """托盘不可用时的降级出口。R-26：降级也必须能用，绝不让用户只能强杀。

        优先最小化到任务栏；连最小化都失败就直接隐藏（隐藏后仍可从任务栏/
        Alt+Tab 唤回，比"点了没反应"强）。
        """
        try:
            self.root.iconify()
        except Exception as e:
            self.log(f"⚠️ 最小化失败，改为隐藏窗口: {type(e).__name__}: {e}")
            try:
                self.root.withdraw()
            except Exception:
                pass

    def show_from_tray(self):
        """托盘"显示主界面" / 双击图标：从托盘唤回窗口。"""
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def quit_app(self):
        """托盘"退出" / 唯一的真退出路径：落盘配置 → 停托盘 → 清子进程 → os._exit。
        这条正是 #18（残留进程致二次打不开）的修法：保证一次退干净。"""
        try:
            self._exiting = True
        except Exception:
            pass
        # 1) 先落盘设置/凭据（os._exit 不走 atexit，必须显式存）
        try:
            self.save_style_config()
        except Exception:
            pass
        # 2) 停托盘图标（否则图标残影留在通知区）
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        # 3) 收割本进程派生的子进程（node 签名等）。R-28：不再 taskkill /IM node.exe
        #    ——那是无差别杀机上**所有** node，会误伤用户自己开的（VSCode/前端脚本）。
        #    改成只杀自己进程树里的后代 + childproc 登记句柄。
        try:
            import childproc
            childproc.kill_own_descendants()
        except Exception:
            pass
        # 4) 停播放器，让音频设备释放（尽力，超时也强退）
        try:
            self.player_stop()
        except Exception:
            pass
        # 5) 单实例互斥体随进程自动释放；os._exit 立即终结全部线程
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        os._exit(0)

    def update_pause_button(self):
        """按钮文案跟随实际状态（在播放器线程里调用，after 回主线程）。"""
        def _u():
            if hasattr(self, "btn_pause"):
                try:
                    self.btn_pause.configure(text="▶ 继续播放" if state.paused else "⏸ 暂停播放")
                except Exception:
                    pass
        try:
            self.root.after(0, _u)
        except Exception:
            pass

    def update_engine_badge(self, text, color):
        def _update():
            if hasattr(self, "lbl_engine_status"):
                qtapp.set_label(self.lbl_engine_status, text=text, color=color)
        self.root.after(0, _update)








    # ═════════ v1.2.8：本地曲库（GUI 按钮 + 歌词） ═════════






    def setup_ui(self):
        """界面全部交给 qtapp（PySide6 + qfluentwidgets）。业务逻辑一律走既有回调。"""
        try:
            qtapp.build(self, self.root)
        except Exception as e:
            # 界面构建失败时给出可读错误，而不是静默白屏
            import traceback
            traceback.print_exc()
            try:
                messagebox.showerror("界面初始化失败", f"{type(e).__name__}: {e}")
            except Exception:
                pass
        self.update_account_status()

    # === 回调 ===









    




    def log(self, msg):
        def _log(): self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n"); self.log_text.see(tk.END)
        self.root.after(0, _log)



    # ═════════ v1.2.8：B站弹幕监听热重启（登录后免重启程序）═════════








    # v1.2.10：QQ 音乐在 SMTC 里的 SourceAppUserModelId 实测就是 "QQMusic.exe"
    # （本机 2026-11-19 实测：AUMID=[QQMusic.exe] / 浏览器是 MSEdge）
    # R-23：真身在 app_media.QQMUSIC_AUMID_HINTS，这里留同名类属性兼容老引用。
    _QQMUSIC_AUMID_HINTS = app_media.QQMUSIC_AUMID_HINTS







    # predownload_song / _download_and_cleanup 已随需求1+3移除：
    # 下载不再是"乐观入列 + 后台预取"，而是串行处理流程内同步完成，
    # 成功后才入 playlist（见 danmaku.process_one_request）。
    # self.download_tasks 保留为空字典（不再写入），避免其他旧引用出错。

