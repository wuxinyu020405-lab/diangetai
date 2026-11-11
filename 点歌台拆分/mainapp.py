"""
主程序：tkinter 控制台与 asyncio worker 编排
"""

import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog, colorchooser, ttk
import threading
import asyncio
import random
import aiohttp
from aiohttp import web
import customtkinter as ctk
import time
import winsdk.windows.media.control as wmc
import blivedm
import json
import os
import sys
import pygame
from qqmusic_api import Client, Credential
import browserlogin
import danmaku
import locallib
import lyrics
import musiclib
import overlay
import secretstore
import settings
import smtc
import state
import ui_ctk
import updater
import version


class _BudgetExceeded(Exception):
    """第7步：单首下载时间预算超限的内部信号（档位内流式写盘时抛出）。"""


# v1.2.8 修复用：这些配置键由"登录流程 / 自动探测 / 用户手填"独立管理，
# 不在设置界面的保存范围内。保存设置时必须先以磁盘值为准合并，
# 否则内存里的旧值会把它们抹掉（历史 bug：登录写入的 Cookie 被覆盖成空）。
_EXTERN_KEYS = ("bili_cookie", "room_id", "douyin_room_id",
                "qqmusic_path", "local_songs_dir", "local_match_threshold")


# ================= 主程序类 =================
class MusicApp:
    def __init__(self, root, config):
        self.root = root; self.config = config
        
        old_style = self.config.get("style_config", {})
        global style_config
        state.style_config = settings.merge_config(old_style, state.style_config)
            
        if not self.config.get("qqmusic_path"):
            auto_path = settings.find_qqmusic_path()
            if auto_path: self.config["qqmusic_path"] = auto_path

        self.audio_backend = "none"

        self.root.title(f"控制台 - 房间 {self.config.get('room_id', '未配置')} - {version.DISPLAY}"); self.root.geometry("780x880")
        self._set_window_icon()
        self._tray = None        # 惰性托盘对象；False=本机托盘不可用
        self._exiting = False
        self._quit_event = None  # v1.2.5：外部退出事件的句柄（安装器置位用）
        self._start_quit_watcher()   # v1.2.5：给安装包留一条"优雅退出"通道
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

    def _qm_post(self, fn):
        """把改动投递到 asyncio loop 线程；loop 还没起来时直接拒绝并提示。"""
        loop = getattr(self, "loop", None)
        if loop is None:
            self.log("ℹ️ 播放引擎还没就绪，队列操作稍后再试")
            return False
        try:
            loop.call_soon_threadsafe(fn)
            return True
        except Exception as e:
            self.log(f"❌ 队列操作投递失败: {e}")
            return False

    def qm_remove_pending(self, idx):
        req = dict(state.pending_requests[idx]) if 0 <= idx < len(state.pending_requests) else None
        if req is None:
            return
        def _do():
            if 0 <= idx < len(state.pending_requests):
                r = state.pending_requests.pop(idx)
                self.log(f"🗑️ 已从排队中移除: 《{r.get('song_name','')}》-{r.get('uname','')}")
        self.root.after(0, lambda: (self._qm_post(_do), self.refresh_queue_mgmt()))

    def qm_remove_ready(self, idx):
        def _do():
            if 0 <= idx < len(state.playlist):
                r = state.playlist.pop(idx)
                self.log(f"🗑️ 已移出待播队列: 《{r.get('display_name','')}》-{r.get('requester','')}（本地音频保留）")
        def _ui():
            if self._qm_post(_do):
                self.refresh_queue_mgmt()
        self.root.after(0, _ui)

    def qm_move_top(self, idx):
        def _do():
            if 0 < idx < len(state.playlist):
                r = state.playlist.pop(idx)
                state.playlist.insert(0, r)
                self.log(f"⬆️ 已置顶: 《{r.get('display_name','')}》（下一首就播它）")
        def _ui():
            if self._qm_post(_do):
                self.refresh_queue_mgmt()
        self.root.after(0, _ui)

    @staticmethod
    def _fmt_wait(ts):
        s = max(0, int(time.time() - (ts or time.time())))
        return f"{s//60}分{s%60:02d}秒" if s >= 60 else f"{s}秒"

    def refresh_queue_mgmt(self):
        """重绘队列管理页两段列表。只读快照 + Tk 线程渲染。"""
        if not hasattr(self, "qm_pending_box"):
            return
        try:
            proc = state.processing_request
            pend = [dict(r) for r in state.pending_requests]
            ready = [dict(r) for r in state.playlist]
            cur = state.current_song
        except Exception:
            return
        try:
            self.lbl_qm_summary.configure(
                text=f"正在播放: {cur['display_name'] if cur else '—'}    "
                     f"处理中 {len(pend) + (1 if proc else 0)} 首 · 待播 {len(ready)} 首")
        except Exception:
            pass
        for box in (self.qm_pending_box, self.qm_ready_box):
            for w in box.winfo_children():
                w.destroy()
        _f = ui_ctk._font
        _MUT = ui_ctk.MUTED
        if proc:
            row = ctk_frame = ctk.CTkFrame(self.qm_pending_box, fg_color=("white", "#1E293B"), corner_radius=8)
            row.pack(fill="x", pady=2, padx=2)
            ctk.CTkLabel(row, text="⬇ 正在下载", width=86, anchor="w", font=_f(11, True),
                         text_color="#F59E0B").pack(side="left", padx=8)
            ctk.CTkLabel(row, text=f"《{proc.get('song_name','')}》 - {proc.get('uname','')}",
                         anchor="w", font=_f(11)).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=self._fmt_wait(proc.get("ts")), font=_f(10),
                         text_color=_MUT).pack(side="right", padx=(0, 8))
        for i, r in enumerate(pend):
            row = ctk.CTkFrame(self.qm_pending_box, fg_color=("white", "#1E293B"), corner_radius=8)
            row.pack(fill="x", pady=2, padx=2)
            ctk.CTkLabel(row, text=f"#{i+1} 排队中", width=86, anchor="w", font=_f(11),
                         text_color=_MUT).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=f"《{r.get('song_name','')}》 - {r.get('uname','')}",
                         anchor="w", font=_f(11)).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="删除", width=52, height=22, corner_radius=6, font=_f(10),
                          fg_color=("#EF4444", "#B91C1C"), hover_color="#DC2626", text_color="white",
                          command=lambda k=i: self.qm_remove_pending(k)).pack(side="right", padx=(0, 4))
            ctk.CTkLabel(row, text=self._fmt_wait(r.get("ts")), font=_f(10),
                         text_color=_MUT).pack(side="right")
        if proc is None and not pend:
            ctk.CTkLabel(self.qm_pending_box, text="（空）", font=_f(11), text_color=_MUT).pack(anchor="w", padx=8)
        for i, r in enumerate(ready):
            row = ctk.CTkFrame(self.qm_ready_box, fg_color=("white", "#1E293B"), corner_radius=8)
            row.pack(fill="x", pady=2, padx=2)
            lead = "▶ 下一首" if i == 0 else f"#{i+1}"
            ctk.CTkLabel(row, text=lead, width=70, anchor="w", font=_f(11, i == 0),
                         text_color=("#22C55E" if i == 0 else None)).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=f"《{r.get('display_name','')}》 - {r.get('requester','')}",
                         anchor="w", font=_f(11)).pack(side="left", fill="x", expand=True)
            if i > 0:
                ctk.CTkButton(row, text="置顶", width=52, height=22, corner_radius=6, font=_f(10),
                              fg_color=("#2563EB", "#3B82F6"), hover_color="#1D4ED8", text_color="white",
                              command=lambda k=i: self.qm_move_top(k)).pack(side="right", padx=(0, 4))
            ctk.CTkButton(row, text="删除", width=52, height=22, corner_radius=6, font=_f(10),
                          fg_color=("#EF4444", "#B91C1C"), hover_color="#DC2626", text_color="white",
                          command=lambda k=i: self.qm_remove_ready(k)).pack(side="right", padx=(0, 4))
        if not ready:
            ctk.CTkLabel(self.qm_ready_box, text="（空）", font=_f(11), text_color=_MUT).pack(anchor="w", padx=8)

    def _qm_tick(self):
        """2.5s 自动刷新（页面没建则跳过；异常绝不打断 tick 链）。"""
        try:
            if hasattr(self, "qm_pending_box") and self.qm_pending_box.winfo_exists():
                # 只在窗口可见时重绘，缩到托盘时省资源
                if self.root.state() != "withdrawn":
                    self.refresh_queue_mgmt()
        except Exception:
            pass
        try:
            self.root.after(2500, self._qm_tick)
        except Exception:
            pass

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
    def gui_send_danmaku(self):
        """主播手动发一条 B站弹幕（复用点歌回执的同一个限频发送器）。"""
        try:
            text = (self.entry_send_dm.get() or "").strip()
        except Exception:
            text = ""
        if not text:
            self._set_send_result("⚠️ 内容为空", "#F59E0B")
            return
        # v1.2.6：每次发送前用最新 config 里的 Cookie 热刷新，登录后无需重启
        sender = self.reload_bili_sender()
        if sender is None:
            self._set_send_result("❌ 发弹幕不可用（未登录 B站 或缺 bili_jct）", "#EF4444")
            self.log("❌ 发弹幕失败：发送器未就绪（请先「重新登录 B站」）")
            return
        if not sender.ready():
            self._set_send_result("❌ 未登录 B站（Cookie 缺 bili_jct）——请先「重新登录 B站」", "#EF4444")
            self.log("❌ 发弹幕失败：Cookie 缺 bili_jct/SESSDATA，请在「弹幕」页点重新登录")
            return
        reason = sender.send(text)
        if reason:
            self._set_send_result("⚠️ 未发送：%s" % reason, "#F59E0B")
            self.log("⚠️ 弹幕未发送：%s" % reason)
            return
        self._set_send_result("✅ 已排队发送", "#22C55E")
        self.log("📣 手动发弹幕：%s" % text[:40])
        try:
            self.entry_send_dm.delete(0, "end")
        except Exception:
            pass

    def _set_send_result(self, msg, color):
        try:
            if hasattr(self, "lbl_send_dm_result"):
                self.lbl_send_dm_result.configure(text=msg, text_color=color)
        except Exception:
            pass

    # ═════════ v1.2.6：弹幕发送器热刷新 / 设置即时生效 / 测试发送 ═════════
    def reload_bili_sender(self):
        """用 config 里最新的 Cookie/房间号热刷新发送器，登录后不必重启。"""
        try:
            import bilibili_send
            cfg = self.config
            kwargs = dict(
                room_id=cfg.get('room_id', ''),
                cookie_str=cfg.get('bili_cookie', '') or '',
                enabled=bool(cfg.get('danmaku_send_enabled', True)),
                sends_per_min=cfg.get('danmaku_sends_per_min', 3),
                min_gap_sec=cfg.get('danmaku_min_gap_sec', 3),
            )
            if getattr(self, "danmaku_sender", None) is None:
                self.danmaku_sender = bilibili_send.RateLimitedSender(
                    kwargs['room_id'], kwargs['cookie_str'], log=self.log,
                    enabled=kwargs['enabled'], sends_per_min=kwargs['sends_per_min'],
                    min_gap_sec=kwargs['min_gap_sec'])
            else:
                self.danmaku_sender.refresh(**kwargs)
            return self.danmaku_sender
        except Exception as e:
            self.log("⚠️ 刷新弹幕发送器失败: %s: %s" % (type(e).__name__, e))
            return getattr(self, "danmaku_sender", None)

    def update_danmaku_settings(self, *_a):
        """弹幕设置即时生效：开关 / 每分钟上限 / 最小间隔。"""
        cfg = self.config
        try:
            cfg["danmaku_send_enabled"] = bool(self.sw_dm_enabled.get())
        except Exception:
            pass
        try:
            v = int(float(str(self.entry_dm_per_min.get()).strip() or 3))
            cfg["danmaku_sends_per_min"] = max(1, v)
        except Exception:
            pass
        try:
            v = float(str(self.entry_dm_gap_sec.get()).strip() or 3)
            cfg["danmaku_min_gap_sec"] = max(0.0, v)
        except Exception:
            pass
        sender = getattr(self, "danmaku_sender", None)
        if sender is not None:
            sender.refresh(enabled=cfg.get("danmaku_send_enabled", True),
                           sends_per_min=cfg.get("danmaku_sends_per_min", 3),
                           min_gap_sec=cfg.get("danmaku_min_gap_sec", 3))
        self.schedule_save_style()

    def test_send_danmaku(self):
        """测试发送：真发一条到当前直播间，把 B站返回的原因显示出来。"""
        import threading
        self._set_send_result("⏳ 正在测试发送...", "#64748B")

        def _work():
            try:
                sender = self.reload_bili_sender()
                if sender is None:
                    self.root.after(0, lambda: self._set_send_result("❌ 发送器不可用", "#EF4444"))
                    return
                ok, msg = sender.send_now("点歌台测试弹幕")
                color = "#22C55E" if ok else "#EF4444"
                text = ("✅ 测试成功：" if ok else "❌ 测试失败：") + msg
                self.root.after(0, lambda: self._set_send_result(text, color))
            except Exception as e:
                self.log("⚠️ 测试发送异常: %s: %s" % (type(e).__name__, e))
                self.root.after(0, lambda: self._set_send_result("❌ 测试异常：%s" % e, "#EF4444"))

        threading.Thread(target=_work, daemon=True).start()

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

    # ═════════ 系统托盘（v1.2.2 需求21）═════════════════════════════
    def minimize_to_tray(self):
        """点 X / 托盘"隐藏"时调用：缩进托盘，程序继续跑。
        托盘起不来（缺库/老系统）→ 退回普通最小化，绝不崩、绝不拦关闭。

        v1.2.5（用户口径）：点 X 全程**不出现任何对话框、任何气泡/通知**，
        直接静默缩进托盘。真退出只走托盘菜单「退出点歌台」或外部退出事件。
        """
        if self._tray is None:
            try:
                import tray
                self._tray = tray.Tray(self)
            except Exception as e:
                self.log(f"⚠️ 托盘模块不可用: {e}（本次改为最小化）")
                self._tray = False
        if self._tray is False:
            self.root.iconify()
            return
        if not self._tray.start():
            self._tray = False
            self.root.iconify()
            return
        self.root.withdraw()                       # 藏起窗口但进程活着

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
        # 3) 杀抖音签名可能遗留的 node 子进程（孤儿）
        try:
            import subprocess
            subprocess.run(["taskkill", "/F", "/IM", "node.exe", "/T"],
                           capture_output=True,
                           creationflags=0x08000000, timeout=8)
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
                ui_ctk.set_label(self.lbl_engine_status, text=text, color=color)
        self.root.after(0, _update)

    def player_is_busy(self):
        if self.audio_backend == "pygame" and pygame.mixer.get_init():
            return pygame.mixer.music.get_busy()
        return False

    def player_stop(self):
        if self.audio_backend == "pygame" and pygame.mixer.get_init():
            try: pygame.mixer.music.stop()
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")


    def player_get_elapsed(self):
        if self.audio_backend == "pygame" and pygame.mixer.get_init():
            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms >= 0: return pos_ms / 1000.0
        return max(0.0, time.time() - state.active_song_start_ts)

    def get_volume(self):
        """第6步·高价值2：音量 0~1，脏值回落 1.0（=现状行为）。"""
        try:
            v = float(state.style_config.get("global", {}).get("volume", 1.0))
        except Exception:
            return 1.0
        return min(1.0, max(0.0, v))

    def apply_volume(self, slider_val=None):
        # slider_val 非空 = 滑杆拖动：用它换算并持久化；
        # 为空 = 起播兜底：读已存配置，只施加不写盘。
        # （tk.Scale 的 command 回调参数才是当前滑杆值，不能去读尚未更新的 style_config）
        if slider_val is not None:
            try:
                v = min(1.0, max(0.0, int(slider_val) / 100.0))
            except Exception:
                v = self.get_volume()
            state.style_config.setdefault("global", {})["volume"] = v
            self.schedule_save_style()
            try:
                ui_ctk.set_label(self.lbl_volume_pct, text=f"{int(round(v * 100))}%")
            except Exception:
                pass
        else:
            v = self.get_volume()
        try:
            if self.audio_backend == "pygame" and pygame.mixer.get_init():
                pygame.mixer.music.set_volume(v)
        except Exception as e:
            print(f"[WARN] 设置音量失败: {e}")
        return v

    async def player_load_and_play(self, file_path, wait_busy_secs=3.0):
        """起播并确认真的在播。

        v1.2.9 修复：原来固定只等 0.4 秒就查一次 get_busy()，本地录音
        （尤其大 wav/flac）加载解码慢时会被误判成"文件损坏"，
        进而触发自动删文件。现在改成轮询等待，最多等 wait_busy_secs。
        """
        def _pg_start():
            try:
                pygame.mixer.music.load(file_path)
                # 第6步：load 会把音量重置回满格，必须起播前重新施加设置值
                try:
                    v = self.get_volume()
                    pygame.mixer.music.set_volume(v)
                except Exception as e:
                    print(f"[WARN] 设置音量失败: {e}")
                pygame.mixer.music.play()
                return True
            except Exception as e:
                print("pygame 播放异常:", e)
                return False
        started = await asyncio.to_thread(_pg_start)
        if not started:
            return False
        # 轮询确认：只要在等待窗口内任意一次 busy=True 就算成功
        deadline = time.time() + max(0.4, float(wait_busy_secs))
        while time.time() < deadline:
            try:
                if pygame.mixer.music.get_busy():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.15)
        return False

    # ═════════ v1.2.8：本地曲库（GUI 按钮 + 歌词） ═════════
    def get_local_songs_dir(self):
        """config.json 的 local_songs_dir 可覆盖默认 my_songs/；目录不存在就建好。"""
        folder = (self.config.get("local_songs_dir") or settings.LOCAL_SONGS_DIR)
        if not os.path.isabs(folder):
            folder = os.path.join(settings.BASE_DIR, folder)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            self.log(f"⚠️ 本地曲库目录创建失败: {e}")
        return folder

    def open_local_songs_folder(self):
        """GUI『打开本地曲库文件夹』：建目录并用资源管理器打开，附一句指引。"""
        folder = self.get_local_songs_dir()
        self.log(f"📂 本地曲库：{folder}")
        self.log(locallib.folder_hint(folder))
        try:
            if os.name == "nt":
                os.startfile(folder)      # 资源管理器，零弹窗、零子进程黑窗
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            self.log(f"⚠️ 打开文件夹失败（可手动去这个路径）: {e}")
        try:
            n = len(locallib.list_songs(folder))
            self.log(f"📀 当前本地曲库共 {n} 首（每次点歌现扫，放进去即生效，无需重启）")
        except Exception:
            pass

    def _load_local_lrc(self, audio_path):
        """本地歌的同名 .lrc；没有就返回 []（上层显示'纯音乐'）。"""
        try:
            import lyrics
            lrc = os.path.splitext(audio_path)[0] + ".lrc"
            if os.path.exists(lrc):
                with open(lrc, "r", encoding="utf-8-sig", errors="replace") as f:
                    return lyrics.parse_lrc(f.read())
        except Exception as e:
            self.log(f"⚠️ 本地歌词读取失败: {e}")
        return []

    def save_style_config(self):
        self.config["style_config"] = state.style_config
        try:
            # ① 先读磁盘，把"外部管理的键"合并回来（磁盘有值且内存是空/旧值时以磁盘为准）
            try:
                disk = secretstore.read_json(settings.CONFIG_FILE, default={}) or {}
            except Exception:
                disk = {}
            if isinstance(disk, dict):
                for k in _EXTERN_KEYS:
                    if k in disk:
                        mem = self.config.get(k)
                        dv = disk.get(k)
                        # 磁盘有非空值 → 用磁盘；否则保留内存值（避免把用户新填的清掉）
                        if dv not in (None, "", 0) or mem in (None, "", 0):
                            self.config[k] = dv
            # ② 再整体写回
            secretstore.write_json(settings.CONFIG_FILE, self.config)
        except Exception as e:
            print("保存配置失败:", e)
            try:
                self.log(f"⚠️ 保存配置失败: {e}")
            except Exception:
                pass

    def schedule_save_style(self, event=None):
        if hasattr(self, "_save_timer") and self._save_timer:
            self.root.after_cancel(self._save_timer)
        self._save_timer = self.root.after(500, self.save_style_config)

    def update_account_status(self):
        bili_status = "❌ 未配置 (缺少Cookie或房间号)"
        bili_color = "red"
        if self.config.get("bili_cookie") and self.config.get("room_id"):
            bili_status = f"✅ 已配置 (房间号: {self.config['room_id']})"
            bili_color = "green"
        ui_ctk.set_label(self.lbl_bili_status, text=bili_status, color=bili_color)

        qq_status = "❌ 未登录"
        qq_color = "red"
        try:
            # v1.2.1·需求6：经 secretstore 透明读（密文/明文兼容）
            data = secretstore.read_json(settings.CREDENTIAL_FILE, default=None)
            if data and data.get("musicid") and data.get("musickey"):
                qq_status = f"✅ 已登录 (账号UID: {data['musicid']})"
                qq_color = "green"
        except Exception:
            pass
        ui_ctk.set_label(self.lbl_qq_status, text=qq_status, color=qq_color)

    def setup_ui(self):
        """界面全部交给 ui_ctk（customtkinter 重写）。业务逻辑一律走既有回调。"""
        try:
            ui_ctk.build(self, self.root)
        except Exception as e:
            # 界面构建失败时给出可读错误，而不是静默白屏
            import traceback
            traceback.print_exc()
            try:
                from tkinter import messagebox
                messagebox.showerror("界面初始化失败", f"{type(e).__name__}: {e}")
            except Exception:
                pass
        self.update_account_status()

    # === 回调 ===
    def update_mixed(self, key, val): state.style_config["mixed"][key] = val; self.schedule_save_style()
    def update_lyric(self, key, val): state.style_config["lyric"][key] = val; self.schedule_save_style()
    def update_playing(self, key, val): state.style_config["playing"][key] = val; self.schedule_save_style()
    def update_queue(self, key, val): state.style_config["queue"][key] = val; self.schedule_save_style()

    def _spin_int_or(self, widget, default):
        """Spinbox 取整：非数字/负数回落到 default，避免打字中途把配置写坏。"""
        try:
            v = int(str(widget.get()).strip())
            return v if v >= 0 else default
        except Exception:
            return default

    def update_lyric_align(self, event):
        val = self.combo_lyric_align.get()
        m = {"居中对齐": "center", "左对齐": "left", "右对齐": "right"}
        state.style_config["lyric"]["align"] = m.get(val, "center")
        self.schedule_save_style()

    def update_queue_align(self, event):
        """v1.1·N3：点歌列表挂件对齐。"""
        val = self.combo_queue_align.get()
        m = {"居中对齐": "center", "左对齐": "left", "右对齐": "right"}
        state.style_config["queue"]["align"] = m.get(val, "left")
        self.schedule_save_style()

    def pick_mixed(self, key, lbl_name):
        c = colorchooser.askcolor(title="选择颜色")[1]
        if c:
            state.style_config["mixed"][key] = c
            ui_ctk.set_label(getattr(self, lbl_name), text=c, color=c, bg=c)
            self.schedule_save_style()

    def pick_lyric(self, key):
        c = colorchooser.askcolor(title="选择歌词颜色")[1]
        if c: state.style_config["lyric"][key] = c; ui_ctk.set_label(self.lbl_lyric_color, text=c, color=c, bg=c); self.schedule_save_style()

    def pick_playing(self, key):
        c = colorchooser.askcolor(title="选择播放颜色")[1]
        if c: state.style_config["playing"][key] = c; ui_ctk.set_label(self.lbl_playing_color, text=c, color=c, bg=c); self.schedule_save_style()

    def pick_queue(self, key):
        c = colorchooser.askcolor(title="选择列表颜色")[1]
        if c: state.style_config["queue"][key] = c; ui_ctk.set_label(self.lbl_queue_color, text=c, color=c, bg=c); self.schedule_save_style()

    def update_effect(self, event):
        val = self.combo_effect.get()
        m = {"高清平滑滚动 (锐利)": "apple_hd", "高清平滑滚动": "apple_hd", "苹果景深滚动 (柔光)": "apple_blur", "苹果景深滚动": "apple_blur", "无滚动 (经典静态)": "static", "无滚动 (静态)": "static"}
        state.style_config["lyric"]["effect"] = m.get(val, "apple_hd")
        self.schedule_save_style()

    def update_audio_quality(self, event=None, value=None):
        """切换首选音质。

        v1.2.8 修复：原来只读 self.var_audio_quality，而 CTkComboBox 的 command
        回调**不会**自动更新那个 StringVar —— 结果界面上选什么都好，写进配置的
        永远是初始化时的旧值（选「默认品质」实际仍按 flac 下载）。
        现在优先用回调传进来的值，找不到才回退到 var。
        """
        val = value if value else self.var_audio_quality.get()
        # 同步 var，保持界面与配置一致（其它地方还会读它回填）
        try:
            if val and self.var_audio_quality.get() != val:
                self.var_audio_quality.set(val)
        except Exception:
            pass
        q_key = settings.UI_QUALITY_MAP.get(val)
        new_q = settings.normalize_quality_key(q_key)
        state.style_config["audio_quality"] = new_q
        self.schedule_save_style()
        self.log(f"🎵 点歌首选音质已切换为: 【{val}】→ 实际档位 {new_q} (无对应音源时自动平滑降级)")
        return new_q
    
    def browse_qq_path(self):
        path = filedialog.askopenfilename(title="选择 QQMusic.exe", filetypes=[("Executable", "*.exe")])
        if path:
            path = path.replace("/", "\\")
            self.entry_qq_path.delete(0, tk.END)
            self.entry_qq_path.insert(0, path)
            self.config["qqmusic_path"] = path
            self.save_style_config()
            self.log(f"✅ QQ音乐路径已更新并保存: {path}")

    def copy_to_clipboard(self, text):
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.log(f"📋 已复制到剪贴板: {text}")

    def update_cache_settings(self, event=None):
        try:
            files = int(self.entry_max_files.get().strip())
            if files > 0: state.style_config["max_cache_files"] = files
        except ValueError as e:
            print(f"[WARN] 值解析失败: {e}")

        try:
            size = int(self.entry_max_size.get().strip())
            if size > 0: state.style_config["max_cache_size_mb"] = size
        except ValueError as e:
            print(f"[WARN] 值解析失败: {e}")

        self.schedule_save_style()

    def log(self, msg):
        def _log(): self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n"); self.log_text.see(tk.END)
        self.root.after(0, _log)

    def start_async_loop(self):
        # 窗口模式(console=False)下线程崩溃的 traceback 无处显示，用户只能看到
        # "正在启动 OBS 服务器..." 就没了下文。这里兜住异常：写进 GUI 日志 + 落盘。
        try:
            self.loop = asyncio.new_event_loop(); asyncio.set_event_loop(self.loop); self.loop.run_until_complete(self.main_async())
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                self.log(f"❌ 后台服务启动失败: {type(e).__name__}: {e}（详见 启动日志.txt）")
            except Exception:
                pass
            try:
                settings.save_startup_log(tb, "启动日志.txt")
            except Exception:
                pass

    async def main_async(self):
        global skip_event; state.skip_event = asyncio.Event()
        state.pause_event = asyncio.Event()   # v1.1·N1
        self.log("正在启动 OBS 服务器...")
        web_app = web.Application()
        web_app.router.add_get('/', overlay.handle_index)
        web_app.router.add_get('/lyric', overlay.handle_index)
        web_app.router.add_get('/playing', overlay.handle_index)
        web_app.router.add_get('/queue', overlay.handle_index)
        web_app.router.add_get('/api/data', overlay.handle_api)

        runner = web.AppRunner(web_app); await runner.setup()
        # 端口自动顺延：8080 被别的程序占着时，依次试 8081~8090，
        # 并把实际端口写回 state.overlay_port 供 GUI 复制挂件地址用。
        bound = None
        for port in range(8080, 8091):
            try:
                site = web.TCPSite(runner, '127.0.0.1', port); await site.start(); bound = port; break
            except OSError as e:
                import errno as _errno
                if e.errno in (_errno.EADDRINUSE, 10048):   # 10048 = Windows 端口被占
                    self.log(f"[INFO] 端口 {port} 已被占用，尝试下一个...")
                    continue
                self.log(f"❌ OBS 服务器启动失败: {type(e).__name__}: {e}"); break
        if bound is None:
            self.log("❌ 8080~8090 全部不可用，OBS 挂件无法启动（点歌播放不受影响）")
        else:
            state.overlay_port = bound
            if bound != 8080:
                self.log(f"⚠️ 默认端口 8080 被占用，已自动改用 {bound}，OBS 源地址请用 http://127.0.0.1:{bound}/")
            self.log("✅ OBS 网页服务器已启动")
        musiclib.load_quota_state()   # 第5步：跨重启恢复当日配额记账（跨日自动归零）
        self.init_audio_engine()

        asyncio.create_task(self.music_player_worker()); asyncio.create_task(self.system_media_worker()); asyncio.create_task(self.lyric_sync_worker())
        # 需求3：点歌串行处理 worker（pending_requests → 逐首出结论）
        asyncio.create_task(danmaku.song_request_worker(self))
        
        cookies = {}
        bili_cookie = self.config.get('bili_cookie', '')
        if not bili_cookie:
            self.log("❌ 缺少 B站 Cookie，请在顶部点击重新登录！")
        else:
            for item in bili_cookie.split(';'):
                if '=' in item: k, v = item.split('=', 1); cookies[k.strip()] = v.strip()
        # v1.1·#8/#1：点歌失败回执通道（带限频）。房间号/ Cookie 齐了才启用。
        import bilibili_send
        self.danmaku_sender = bilibili_send.RateLimitedSender(
            self.config.get('room_id', ''), bili_cookie, log=self.log,
            enabled=bool(self.config.get('danmaku_send_enabled', True)),
            sends_per_min=self.config.get('danmaku_sends_per_min', 3),
            min_gap_sec=self.config.get('danmaku_min_gap_sec', 3))
        self.log("📣 弹幕发送：%s，限频 %s 条/分钟、间隔 %ss" % (
            "已就绪" if self.danmaku_sender.ready() else "未登录/缺 Cookie",
            self.danmaku_sender.sends_per_min, int(self.danmaku_sender.min_gap_sec)))
                
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Referer": f"https://live.bilibili.com/{self.config.get('room_id', '')}", "Origin": "https://live.bilibili.com"}
        
        async with aiohttp.ClientSession(cookies=cookies, headers=headers, trust_env=False) as http_session:
            self._bili_session = http_session
            # v1.2.8：B站监听改成可热重启（登录后不用重启程序）。
            # 连接持有在实例上，restart_bili_listener() 可随时拆掉重建。
            await self._start_bili_listener()
            # v1.2·抖音双平台：配置了 douyin_room_id 就并起一路匿名弹幕
            dy_room = str(self.config.get('douyin_room_id', '') or '').strip()
            if dy_room:
                import queue as _q
                from live_providers.douyin import DouyinProvider
                self._dy_q = _q.Queue()
                self._dy = DouyinProvider(dy_room, log=self.log)
                asyncio.create_task(self._dy.run(self._dy_q))
                asyncio.create_task(self._douyin_dispatcher())
                self.log("🎙️ 抖音通道启动中（房间 %s，匿名）" % dy_room)
            try:
                while True: await asyncio.sleep(3600)
            finally:
                await self._stop_bili_listener()
                self._bili_session = None

    # ═════════ v1.2.8：B站弹幕监听热重启（登录后免重启程序）═════════
    async def _start_bili_listener(self):
        """(重)建 B站弹幕监听。必须在 asyncio loop 线程里调用。

        为什么要有这个方法：原来 BLiveClient 只在 main_async 里建一次，
        登录后拿到的新 Cookie/房间号根本不会被它看到，必须重启程序才收得到弹幕。
        拆出来之后，restart_bili_listener() 可以在登录成功时拆旧建新。
        """
        room = str(self.config.get("room_id") or "").strip()
        if not room:
            self.log("❌ 缺少 B站 房间号，请点击顶部登录 B站！")
            self._bili_client = None
            self._bili_room = None
            return False
        try:
            session = getattr(self, "_bili_session", None)
            if session is None:
                self.log("⚠️ 弹幕监听重建失败：HTTP 会话未就绪")
                return False
            # v1.2.8：cookie 每次从 config 现取，不再用启动时那份
            cookie_str = str(self.config.get("bili_cookie") or "")
            cookies = {}
            for item in cookie_str.split(";"):
                if "=" in item:
                    k, v = item.split("=", 1)
                    cookies[k.strip()] = v.strip()
            client = blivedm.BLiveClient(int(room), session=session)
            # 把最新 Cookie 灌进共享会话（blivedm 用这个 session 的 cookie 鉴权）
            try:
                session.cookie_jar.update_cookies(cookies)
            except Exception as e:
                self.log(f"⚠️ 更新 Cookie 到弹幕会话失败（可能影响身份相关弹幕）: {e}")
            client.set_handler(danmaku.BiliHandler(self))
            client.start()
            self._bili_client = client
            self._bili_room = room
            self.log(f"✅ 连接 B 站成功！等待弹幕中...（房间 {room}）")
            return True
        except Exception as e:
            self.log(f"❌ 连接 B 站失败: {type(e).__name__}: {e}")
            self._bili_client = None
            return False

    async def _stop_bili_listener(self):
        """停掉现有 B站监听（尽力而为，异常不影响后续重建）。"""
        client = getattr(self, "_bili_client", None)
        self._bili_client = None
        if client is None:
            return
        try:
            await client.stop_and_close()
        except Exception as e:
            print(f"[WARN] 停止 B站弹幕连接异常(已忽略): {e}")

    async def _restart_bili_listener_async(self):
        """拆旧建新。加锁防重入（连点两次登录不会建出两条连接）。"""
        if getattr(self, "_bili_restarting", False):
            self.log("ℹ️ 弹幕监听正在重连中，稍候…")
            return
        self._bili_restarting = True
        try:
            old_room = getattr(self, "_bili_room", None)
            await self._stop_bili_listener()
            ok = await self._start_bili_listener()
            new_room = getattr(self, "_bili_room", None)
            if ok:
                if old_room and new_room and old_room != new_room:
                    self.log(f"🔁 弹幕监听已切换房间：{old_room} → {new_room}")
                else:
                    self.log("🔁 弹幕监听已重连（新的登录信息已生效，无需重启程序）")
            else:
                self.log("⚠️ 弹幕监听重连失败，可点「重连弹幕」重试")
        finally:
            self._bili_restarting = False

    def restart_bili_listener(self, notify_ui=False):
        """对外入口（可从 Tk 线程调用）：把重连投递到 asyncio loop 线程执行。"""
        loop = getattr(self, "loop", None)
        if loop is None or loop.is_closed():
            self.log("⚠️ 播放引擎还没就绪，弹幕监听稍后再重连")
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._restart_bili_listener_async(), loop)
            return True
        except Exception as e:
            self.log(f"❌ 弹幕监听重连投递失败: {e}")
            return False

    def gui_restart_bili_listener(self):
        """GUI『重连弹幕』按钮：手动兜底，帮用户看到结果。"""
        if self.restart_bili_listener():
            try:
                self.log("🔄 正在重连 B站弹幕监听…")
            except Exception:
                pass

    async def _douyin_dispatcher(self):
        """抖音消息队列 → 统一指令入口 handle_message（与 B 站同一行为）。
        chat 进指令解析；member/social/gift 只记日志（v1 不做进场播报）。"""
        import queue as _q
        while True:
            try:
                msg = await asyncio.to_thread(self._dy_q.get, True, 1)
            except _q.Empty:
                await asyncio.sleep(0.2)
                continue
            except Exception:
                await asyncio.sleep(1)
                continue
            try:
                if msg.type == "chat":
                    danmaku.handle_message(self, msg.text, msg.uname, "douyin")
                elif msg.type == "gift":
                    self.log("🎁 [douyin] %s 送 %s" % (msg.uname, msg.extra))
                elif msg.type == "member":
                    self.log("🚪 [douyin] %s 进入直播间" % msg.uname)
            except Exception as e:
                print(f"[WARN] 抖音消息分发异常: {e}")

    async def fetch_lyrics_by_mid_or_keyword(self, song_mid=None, keyword=None):
        try:
            if song_mid and song_mid in state.lyric_cache: return state.lyric_cache[song_mid]
            async with Client(credential=state.qq_credential) as client:
                if not song_mid and keyword:
                    search_res = await client.search.search_by_type(keyword=keyword, num=1)
                    song_mid, _, _, _, _ = musiclib.extract_song_info(search_res)   # 5元组（step2起）
                if not song_mid: return []
                if song_mid in state.lyric_cache: return state.lyric_cache[song_mid]
                lyric_res = await client.lyric.get_lyric(value=song_mid)
                raw_lrc = getattr(lyric_res, 'lyric', None)
                if not raw_lrc and isinstance(lyric_res, dict): raw_lrc = lyric_res.get('lyric')
                parsed = lyrics.parse_lrc(raw_lrc)
                if parsed: state.lyric_cache[song_mid] = parsed
                return parsed
        except Exception: return []

    async def lyric_sync_worker(self):
        global current_lyric_info
        while True:
            try:
                if state.active_lrc_lines:
                    if state.current_play_mode == "api":
                        # v1.1·B1续：不能用 player_is_busy() 做门槛——SDL 在 pause 期间
                        # busy=False，旧逻辑会误落墙钟推算分支，导致"暂停时歌词继续跑"。
                        # get_pos() 在暂停期间天然冻结（实测），正是我们要的行为；
                        # 未播放时返回 -1，player_get_elapsed 内部已回落到墙钟。
                        elapsed = self.player_get_elapsed()
                    else:
                        elapsed = state.active_song_base_pos + (time.time() - state.active_song_start_ts)
                    
                    state.current_lyric_info = lyrics.get_current_lyric_state(state.active_lrc_lines, elapsed)
                else: 
                    state.current_lyric_info = {"lines": [], "all_lines": [], "active_idx": -1}
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

            await asyncio.sleep(0.08)

    async def get_best_smtc_session(self, sessions_mgr):
        if not sessions_mgr: return None
        try:
            all_sessions = sessions_mgr.get_sessions(); fallback_session = None
            for s in all_sessions:
                try:
                    pinfo = s.get_playback_info()
                    if pinfo and pinfo.playback_status == 4: return s
                    if fallback_session is None: fallback_session = s
                except Exception: continue
            return sessions_mgr.get_current_session() or fallback_session
        except Exception:
            try: return sessions_mgr.get_current_session()
            except Exception: return None

    async def control_local_music(self, pause=True):
        global is_local_playing, bgm_paused_by_bot
        try:
            sessions_mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async(); session = await self.get_best_smtc_session(sessions_mgr)
            if session:
                playback_info = session.get_playback_info()
                if pause and playback_info.playback_status == 4: 
                    await session.try_toggle_play_pause_async(); self.log("⏸️ 暂停本地 BGM"); state.is_local_playing = False; state.bgm_paused_by_bot = True
                elif not pause and state.bgm_paused_by_bot and playback_info.playback_status != 4:
                    await session.try_toggle_play_pause_async(); self.log("▶️ 恢复本地 BGM"); state.is_local_playing = True; state.bgm_paused_by_bot = False
        except Exception as e: self.log(f"控制本地音乐失败: {e}")

    async def system_media_worker(self):
        global system_media_info, active_lrc_lines, active_song_start_ts, active_song_base_pos
        sessions_mgr = None
        try: sessions_mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
        except Exception as e:
            print(f"[WARN] 异常已捕获: {e}")

        last_logged_key = ""; last_lyric_key = ""; last_smtc_pos = -1.0
        prev_play_mode = state.current_play_mode   # v1.1·BGM回归无歌词修复
        while True:
            try:
                # v1.1 修复：点歌播完恢复 BGM 时，本地播放器从暂停处继续=同一首歌，
                # last_lyric_key 在 api 期间是陈旧的 → 旧逻辑判"没换歌"跳过取词，
                # 而 active_lrc_lines 已被播放器清空 → 这一整首 OBS 没有歌词。
                # 检测 api→local 回升，强制按"新歌"重走取词路径（位置由 SMTC 校准）。
                if prev_play_mode != "local" and state.current_play_mode == "local":
                    last_lyric_key = ""
                prev_play_mode = state.current_play_mode
                if state.current_play_mode == "local":
                    title, artist = "", ""; smtc_pos = None
                    if sessions_mgr:
                        session = await self.get_best_smtc_session(sessions_mgr)
                        if session:
                            info = await session.try_get_media_properties_async()
                            if info and info.title: title = (info.title or "").strip(); artist = (info.artist or "").strip()
                            try:
                                timeline = session.get_timeline_properties()
                                if timeline and timeline.position:
                                    pos_sec = timeline.position.total_seconds()
                                    if pos_sec > 0: smtc_pos = pos_sec
                            except Exception as e:
                                print(f"[WARN] 异常已捕获: {e}")

                    if not title:
                        win_title, win_artist = smtc.get_qqmusic_window_song()
                        if win_title: title, artist = win_title, (win_artist or "")
                    if title:
                        state.system_media_info = {"title": title, "artist": artist}; track_key = f"{title}|{artist}"
                        if track_key != last_logged_key: last_logged_key = track_key; self.log(f"🎵 正在播放(本地/网页): {title}" + (f" - {artist}" if artist else ""))
                        if track_key != last_lyric_key:
                            last_lyric_key = track_key; state.active_song_start_ts = time.time()
                            state.active_song_base_pos = smtc_pos if (smtc_pos is not None) else 0.0; last_smtc_pos = smtc_pos if (smtc_pos is not None) else -1.0
                            state.active_lrc_lines = []; search_kw = f"{title} {artist}".strip(); lines = await self.fetch_lyrics_by_mid_or_keyword(keyword=search_kw)
                            if not lines:
                                lines = [(0.0, state.style_config["lyric"].get("pure_text", "纯音乐, 请欣赏.."))]
                            if state.current_play_mode == "local" and last_lyric_key == track_key: state.active_lrc_lines = lines
                        elif smtc_pos is not None:
                            # v1.1·B1续：持续用 SMTC 真实位置校准墙钟推算。旧逻辑只在
                            # smtc_pos 自身跳变>1.5s 时重同步，检测不到"外部暂停/拖进度条"
                            # 造成的墙钟跑赢 SMTC（用户在 QQ音乐里暂停 BGM → 歌词跑飞）。
                            est = state.active_song_base_pos + (time.time() - state.active_song_start_ts)
                            if abs(smtc_pos - est) > 1.5:
                                state.active_song_base_pos = smtc_pos; state.active_song_start_ts = time.time()
                    else:
                        state.system_media_info = {"title": "暂无播放", "artist": ""}
                        if last_lyric_key != "": last_lyric_key = ""; state.active_lrc_lines = []
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

            await asyncio.sleep(1.5)

    async def download_audio_qq(self, song_info, retries=3):
        self.last_download_reason = None
        song_mid = song_info.get("mid")
        display_name = song_info.get("display_name", "")
        # 第7步：单首总时间预算（串行管线的排队时长上界，23:49拍板 45s）
        dl_deadline = time.time() + settings.SONG_DOWNLOAD_BUDGET_SEC

        # 需求2·本地优先（置于凭证检查之前）：缓存命中即可播放，不需要下载，
        # 因此凭证过期/缺失时老缓存照样能用。
        any_cached = musiclib.find_any_cached_file(song_mid)
        if any_cached:
            self.last_download_reason = "cached"
            try: os.utime(any_cached, None)
            except Exception as e:
                print(f"[WARN] 缓存文件时间戳更新失败: {e}")
            return any_cached, display_name, song_mid

        if not state.qq_credential:
            self.last_download_reason = "no_credential"
            return None, None, None
        preferred_q = settings.normalize_quality_key(state.style_config.get("audio_quality", "flac"))
        chain = settings.QUALITY_FALLBACK_CHAINS.get(preferred_q, settings.QUALITY_FALLBACK_CHAINS["flac"])

        # 需求5：size_flac 预检（前置到所有网络动作之前）——
        # 搜索结果明确报无 FLAC(=0) 时，直接把 FLAC 档从链里剔掉，
        # 连 1.5s 预热和 CDN 请求都不用为它花。None=未知，保留该档（宁可多试不可漏放）。
        if song_info.get("flac_size") == 0:
            pruned = [t for t in chain if t[0] != "flac"]
            if pruned:
                self.log(f"[INFO] 搜索结果标记无 FLAC 音源(size_flac=0)，本首仅尝试: {[t[1] for t in pruned]}")
                chain = pruned

        # （本地优先缓存检索已置于函数顶部、凭证检查之前，避免在此重复）

        # 辅助函数：每次重试时重新获取CDN分发信息（避免使用过期的CDN节点）
        async def fetch_cdn():
            try:
                async with Client(credential=state.qq_credential) as client:
                    cdn_dispatch = await client.song.get_cdn_dispatch()
                    if hasattr(cdn_dispatch, 'sip') and cdn_dispatch.sip:
                        return random.choice(cdn_dispatch.sip)
            except Exception as e:
                print(f"[WARN] CDN分发信息获取失败: {e}")
            return ""

        # #4：原"下载前固定预热 1.5s"已移除。
        # 实测（2026-10-28，真实取址各 3 轮）：不预热 3/3 成功、预热后 3/3 成功，
        # result 码均为 0 —— 预热对成功率零贡献，纯属白白增加每次下载 1.5 秒延迟。
        if time.time() > dl_deadline:
            self.log(f"[{display_name}] 预算内未及开始取址（{settings.SONG_DOWNLOAD_BUDGET_SEC}s），本首放弃")
            self.last_download_reason = "budget"
            return None, display_name, song_mid

        # 首次获取CDN
        cdn = await fetch_cdn()
        if cdn:
            print(f"[INFO] 已获取CDN分发节点: {cdn}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://y.qq.com/", "Origin": "https://y.qq.com",
            "Cookie": f"uin=o{state.qq_credential.musicid}; qm_keyst={state.qq_credential.musickey};"
        }

        for idx, (tier_key, tier_label, enum_names, default_ext, needs_enum) in enumerate(chain):
            # 第7步：单首预算——档位级检查，超时立即放弃整首（不再逐档烧时间）
            if time.time() > dl_deadline:
                self.log(f"[{display_name}] 超出单首预算({settings.SONG_DOWNLOAD_BUDGET_SEC}s)，放弃剩余档位")
                self.last_download_reason = "budget"
                return None, display_name, song_mid
            cached_tier_file = musiclib.find_cached_file_for_tier(song_mid, tier_key)
            if cached_tier_file:
                if idx > 0: self.log(f"无 {chain[0][1]} 音源，已使用本地缓存 [{tier_label}]")
                self.last_download_reason = "cached"
                try: os.utime(cached_tier_file, None)
                except Exception as e:
                    print(f"[WARN] 缓存文件时间戳更新失败: {e}")
                return cached_tier_file, display_name, song_mid

            # 每次音质降级时重新获取CDN
            cdn = await fetch_cdn()
            if cdn:
                self.log(f"已刷新CDN节点: {cdn}")

            # 使用 retries 参数控制重试次数（默认3次）
            cred_refreshed = False   # 本档位是否已尝试过凭证续期（最多1次）
            for attempt in range(retries):
                if time.time() > dl_deadline:
                    self.log(f"[{display_name}] 超出单首预算({settings.SONG_DOWNLOAD_BUDGET_SEC}s)，放弃剩余重试")
                    self.last_download_reason = "budget"
                    return None, display_name, song_mid
                try:
                    # 每次重试重新获取CDN节点（确保不复用过期节点）
                    if attempt > 0:
                        fresh_cdn = await fetch_cdn()
                        if fresh_cdn:
                            cdn = fresh_cdn
                            self.log(f"[INFO] 重试 [{tier_label}] (第{attempt+1}/{retries}次)，已刷新CDN节点: {fresh_cdn}")
                        else:
                            self.log(f"[WARN] 重试 [{tier_label}] (第{attempt+1}/{retries}次)，CDN刷新失败")

                    async with Client(credential=state.qq_credential) as client:
                        ft_enum = musiclib.resolve_song_file_type(client, enum_names) if needs_enum else None
                        if needs_enum and ft_enum is None:
                            self.log(f"[{tier_label}] 无法探测音质枚举类型，跳过此档位")
                            break

                        url_res = await musiclib.request_song_url_with_type(client, song_mid, ft_enum, state.qq_credential)
                        detail = musiclib.extract_url_detail(url_res, cdn=cdn)
                        fresh_url = detail["url"]
                        if attempt > 0 and fresh_url:
                            self.log(f"[INFO] 重试获取到新的下载URL (音质={tier_label})")

                        if not fresh_url:
                            code = detail.get("result")
                            why = detail.get("result_text") or "未知原因"
                            if code == 104013:
                                self.log(f"[{tier_label}] 播放设备受限(104013)，整首放弃，请重新扫码登录 QQ音乐")
                                self.last_download_reason = "device_limited"
                                return None, display_name, song_mid
                            if code == 104003:
                                self.log(f"[{tier_label}] 无该档位权限({why})，直接跳下一档")
                                break
                            if code == 104004 and not cred_refreshed:
                                cred_refreshed = True
                                new_cred = await musiclib.try_refresh_credential(state.qq_credential)
                                if new_cred:
                                    state.qq_credential = new_cred
                                    settings.save_credential(new_cred)
                                    self.log(f"[{tier_label}] VKey获取失败({why})，凭证已自动续期，重试本档")
                                    continue
                                self.log(f"[{tier_label}] VKey获取失败({why})，且凭证续期失败，跳档")
                                break
                            self.log(f"[{tier_label}] 未能获取下载URL：{why} (result={code})，跳过此档位")
                            break

                        selected_ext = musiclib.detect_ext_from_url(fresh_url, default_ext)
                        file_path = os.path.join(settings.CACHE_DIR, f"{song_mid}_{tier_key}{selected_ext}")
                        tmp_path = file_path + ".part"   # 第7步：半包防护，写完才改名

                        if attempt == 0:
                            self.log(f"[INFO] 首次下载 [{tier_label}]: {display_name} (URL有效期字段: {detail.get('expiration')})...")
                        else:
                            self.log(f"[INFO] 重试下载 [{tier_label}] (第{attempt+1}/{retries}次)...")

                        async with aiohttp.ClientSession(trust_env=False, headers=headers) as session:
                            async with session.get(fresh_url, timeout=aiohttp.ClientTimeout(total=30, connect=10)) as resp:
                                if resp.status in (200, 206):
                                    # 第7步：流式边读边写（不再整块进内存），边写边查单首预算
                                    total = 0
                                    try:
                                        with open(tmp_path, "wb") as f:
                                            async for chunk in resp.content.iter_chunked(64 * 1024):
                                                f.write(chunk)
                                                total += len(chunk)
                                                if time.time() > dl_deadline:
                                                    raise _BudgetExceeded()
                                    except _BudgetExceeded:
                                        try: os.remove(tmp_path)
                                        except OSError: pass
                                        raise
                                    except Exception:
                                        try: os.remove(tmp_path)
                                        except OSError: pass
                                        raise
                                    if total > musiclib.MIN_CACHE_BYTES:
                                        os.replace(tmp_path, file_path)   # 原子改名，其他读者永不见半包
                                        size_mb = total / (1024 * 1024)
                                        self.log(f"[INFO] ✅ 下载完成 [{tier_label}] ({size_mb:.1f} MB): {display_name} | 文件路径: {file_path}")
                                        musiclib.clean_cache_if_needed()
                                        self.last_download_reason = "downloaded"
                                        return file_path, display_name, song_mid
                                    else:
                                        try: os.remove(tmp_path)
                                        except OSError: pass
                                        self.log(f"[{tier_label}] 下载体过小({total}B)，判为无效并丢弃")
                                        break   # 该档放弃，走降级
                                elif resp.status == 403:
                                    self.log(f"[{tier_label}] 下载被拦截(403)，将刷新CDN节点和链接后重试...")
                                    retry_delay = 2 + random.uniform(0, 1.5)  # 基础2秒 + 随机抖动0~1.5秒
                                    self.log(f"[INFO] 403等待 {retry_delay:.1f}秒后重试 (CDN刷新+随机抖动避免限流)")
                                    await asyncio.sleep(retry_delay)
                                else:
                                    self.log(f"[{tier_label}] 下载失败: HTTP {resp.status}")
                                    break
                except _BudgetExceeded:
                    self.log(f"[{display_name}] 流式下载中途超出单首预算({settings.SONG_DOWNLOAD_BUDGET_SEC}s)，放弃")
                    self.last_download_reason = "budget"
                    return None, display_name, song_mid
                except Exception as e:
                    action, reason = musiclib.classify_api_exception(e)
                    if action == "quota":
                        self.log(f"[{tier_label}] ⛔ {reason} ({type(e).__name__})，停止本首后续尝试")
                        self.last_download_reason = "quota"
                        return None, display_name, song_mid
                    if action == "refresh_cred" and not cred_refreshed:
                        cred_refreshed = True
                        new_cred = await musiclib.try_refresh_credential(state.qq_credential)
                        if new_cred:
                            state.qq_credential = new_cred
                            settings.save_credential(new_cred)
                            self.log(f"[{tier_label}] {reason}，已自动续期凭证并重试本档")
                            continue
                        self.log(f"[{tier_label}] {reason}，且自动续期失败，请重新扫码登录 QQ音乐；跳过此档位")
                        break
                    if action == "skip":
                        self.log(f"[{tier_label}] 上游拒绝({reason}: {type(e).__name__})，不重试，跳过此档位")
                        break
                    self.log(f"[{tier_label}] 网络异常({reason}: {type(e).__name__})，退避后重试")
                    retry_delay = 2 + random.uniform(0, 1.5)  # 基础2秒 + 随机抖动
                    await asyncio.sleep(retry_delay)

            if idx < len(chain) - 1:
                self.log(f"当前音质 [{tier_label}] 全部失败，降级为 [{chain[idx+1][1]}] 尝试下载...")
                # 降级前等待更久，给服务器更多恢复时间
                fallback_delay = 3 + random.uniform(0, 2)
                self.log(f"[INFO] 降级前等待 {fallback_delay:.1f}秒，确保服务器状态恢复")
                await asyncio.sleep(fallback_delay)

        self.log(f"彻底无法下载《{display_name}》，所有音质均失败")
        self.last_download_reason = "all_failed"
        return None, display_name, song_mid

    # predownload_song / _download_and_cleanup 已随需求1+3移除：
    # 下载不再是"乐观入列 + 后台预取"，而是串行处理流程内同步完成，
    # 成功后才入 playlist（见 danmaku.process_one_request）。
    # self.download_tasks 保留为空字典（不再写入），避免其他旧引用出错。

    async def music_player_worker(self):
        global current_song, current_play_mode, system_media_info, active_lrc_lines, active_song_start_ts, active_song_base_pos
        while True:
            if state.current_song is None and len(state.playlist) > 0:
                state.current_song = state.playlist.pop(0)
                requester = state.current_song.get("requester", "神秘观众")
                # v1.2.9 双保险：新歌开播前先消化掉残留的切歌意图。
                # 入口（弹幕/按钮/API）已经拦住空闲切歌，这里再兜一层：
                # 万一还有历史残留，也不能让用户刚点的歌一开口就被切走。
                if state.skip_event is not None and state.skip_event.is_set():
                    state.skip_event.clear()
                    self.log("ℹ️ 已清除残留的切歌意图，本首正常播放")
                self.log(f"▶️ 准备播放: {state.current_song['display_name']}-{requester}")
                song_mid = state.current_song.get("mid")

                preferred_q = settings.normalize_quality_key(state.style_config.get("audio_quality", "flac"))

                # v1.2.8：本地曲库条目自带 file_path，直接用，不再按 mid 查缓存。
                # 普通 QQ 音乐条目没有该字段，回退到原有的缓存检索逻辑，行为不变。
                file_path = state.current_song.get("file_path")
                if not file_path:
                    # 需求2·本地优先：任意有效档命中即用（与下载侧同一判据）
                    file_path = musiclib.find_any_cached_file(song_mid)

                has_file = bool(file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0)

                # （原"等待后台预下载"块已随需求1+3移除：playlist 只含就绪歌曲，
                #   串行处理在入列前已同步完成下载，播放器无需再等。）

                real_name = state.current_song.get("display_name", "")
                
                if not has_file:
                    self.log(f"⏭️ 跳过无法播放的歌曲 (无版权或下载失败): {state.current_song['display_name']}")
                    state.current_song = None; state.active_lrc_lines = []
                    await asyncio.sleep(1)
                    continue

                if state.current_play_mode == "local":
                    await self.control_local_music(pause=True)
                    state.current_play_mode = "api"

                if file_path and os.path.exists(file_path):
                    ext_tag = os.path.splitext(file_path)[1].lstrip(".").upper() or "AUDIO"
                    self.log(f"✅ 开始独立播放 [Pygame | {ext_tag}]: {real_name}")
                    state.system_media_info = {"title": f"{state.current_song['display_name']}-{requester}", "artist": ""}
                    # v1.2.8：本地曲库条目没有 mid，不能按歌名去 QQ 搜歌词（会抓到别人的）。
                    # 有同名 .lrc 就读它，否则显示"纯音乐"。普通条目走原逻辑不变。
                    if state.current_song.get("file_path"):
                        state.active_lrc_lines = self._load_local_lrc(state.current_song["file_path"])
                    else:
                        state.active_lrc_lines = await self.fetch_lyrics_by_mid_or_keyword(song_mid=song_mid, keyword=state.current_song['display_name'])

                    if not state.active_lrc_lines:
                        state.active_lrc_lines = [(0.0, state.style_config["lyric"].get("pure_text", "纯音乐, 请欣赏.."))]

                    try:
                        started = await self.player_load_and_play(file_path)
                        state.active_song_start_ts = time.time()
                        state.active_song_base_pos = 0.0

                        # v1.1·N1：load_and_play 内部起播后确认 busy；若这期间用户已按暂停，
                        # busy=False 属正常而非"文件损坏"——必须排除暂停态，否则会误删缓存文件。
                        if (not started or not self.player_is_busy()) and not state.pause_event.is_set():
                            # v1.2.9：本地曲库是用户自己录的资料，**永远不自动删除**。
                            # 起播失败最多只是"这首没放出来"，绝不能把源文件删掉。
                            is_local_lib = (state.current_song or {}).get("source") == "local" \
                                or bool((state.current_song or {}).get("file_path"))
                            if is_local_lib:
                                self.log(f"⚠️ 本地文件没能正常起播（可能是加载慢/格式问题），已跳过；"
                                         f"文件保留未删: {real_name}")
                            else:
                                self.log(f"⚠️ 播放瞬间结束，可能是文件损坏或解码异常，自动清理并跳过: {real_name}")
                                try:
                                    if os.path.exists(file_path): os.remove(file_path)
                                except Exception as e:
                                    print(f"[WARN] 异常已捕获: {e}")

                            state.current_song = None; state.active_lrc_lines = []
                            continue

                        # v1.1·N1 暂停状态机（实测 SDL：pause 期间 get_pos 冻结、get_busy=False）
                        # 规则：暂停只停当前歌播放；下载/收队列不受影响；切歌优先并自动解除暂停。
                        state.paused = False
                        busy_false_streak = 0      # v1.2.9：连续 False 计数
                        _dbg_said = False
                        while True:
                            if state.pause_event.is_set():
                                if not state.paused:
                                    try: pygame.mixer.music.pause()
                                    except Exception as e: print(f"[WARN] 暂停失败: {e}")
                                    state.paused = True
                                    self.log("⏸️ 已暂停播放（点歌与下载照常排队；发【继续】或【切歌】恢复）")
                                    self.update_pause_button()
                                # 暂停中 busy=False，若不加这层保护会被当"播完"→提前恢复 BGM（实测坑）
                                if state.skip_event.is_set():
                                    state.skip_event.clear()
                                    try: pygame.mixer.music.unpause()
                                    except Exception: pass
                                    self.player_stop()
                                    state.paused = False
                                    self.update_pause_button()
                                    break
                                await asyncio.sleep(0.25)
                                continue
                            if state.paused:   # 暂停态收到解除意图
                                try: pygame.mixer.music.unpause()
                                except Exception as e: print(f"[WARN] 恢复播放失败: {e}")
                                state.paused = False
                                self.log("▶️ 已恢复播放")
                                self.update_pause_button()
                            if state.skip_event.is_set():
                                self.player_stop(); state.skip_event.clear(); break

                            # v1.2.9 修复「点歌后自动切歌」：原来单次 get_busy()==False 就当播完。
                            # 现在要求**连续 20 次（约 5 秒）都 False** 才认播完。
                            # 直播时 SMTC 暂停/恢复主播 BGM 会引起音频设备切换，
                            # 实测会让 get_busy 瞬时变 False，5 秒容忍足以挡住这种抖动。
                            if not self.player_is_busy():
                                busy_false_streak += 1
                                if not _dbg_said:
                                    _dbg_said = True
                                    try:
                                        pos = pygame.mixer.music.get_pos()
                                        init_ok = bool(pygame.mixer.get_init())
                                    except Exception:
                                        pos, init_ok = "?", False
                                    self.log(f"🔍 [诊断] get_busy 首次为 False（pos={pos}ms, "
                                             f"mixer_init={init_ok}, backend={self.audio_backend}）")
                                if busy_false_streak >= 20:
                                    self.log(f"🔍 [诊断] 连续 {busy_false_streak} 次 False（约5秒），判定本首播完")
                                    break
                                # 中途恢复过就清掉标记，下次再 False 可再报一次
                            else:
                                if busy_false_streak:
                                    self.log(f"🔍 [诊断] 播放恢复（曾连续 {busy_false_streak} 次 False，已忽略）")
                                    _dbg_said = False
                                busy_false_streak = 0
                            await asyncio.sleep(0.25)
                    except Exception as e:
                        self.log(f"❌ 播放失败: {type(e).__name__}: {e}")
                        # v1.2.9：本地曲库文件是用户资料，出任何异常都只跳过、不删文件
                        if not ((state.current_song or {}).get("source") == "local"
                                or (state.current_song or {}).get("file_path")):
                            try:
                                if os.path.exists(file_path): os.remove(file_path)
                            except Exception as e2:
                                print(f"[WARN] 异常已捕获: {e2}")
                        else:
                            self.log(f"ℹ️ 本地文件保留未删: {real_name}")


                state.current_song = None; state.active_lrc_lines = []

                if len(state.playlist) == 0 and state.current_play_mode == "api":
                    await asyncio.sleep(0.5)
                    if len(state.playlist) == 0:
                        state.system_media_info = {"title": "暂无播放", "artist": ""}
                        await self.control_local_music(pause=False)
                        state.current_play_mode = "local"
            await asyncio.sleep(0.5)
