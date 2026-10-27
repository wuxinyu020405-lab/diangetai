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
import time
import winsdk.windows.media.control as wmc
import blivedm
import json
import os
import pygame
from qqmusic_api import Client, Credential
import browserlogin
import danmaku
import lyrics
import musiclib
import overlay
import settings
import smtc
import state

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

        self.root.title(f"控制台 - 房间 {self.config.get('room_id', '未配置')}"); self.root.geometry("780x880")
        self.setup_ui()
        self.download_tasks = {}
        self.last_download_reason = None   # 需求9：单行结论的失败归因标记
        self.thread = threading.Thread(target=self.start_async_loop, daemon=True); self.thread.start()

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

    def update_engine_badge(self, text, color):
        def _update():
            if hasattr(self, "lbl_engine_status"):
                self.lbl_engine_status.config(text=text, fg=color)
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

    async def player_load_and_play(self, file_path):
        def _pg_start():
            try:
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.play()
                return True
            except Exception as e:
                print("pygame 播放异常:", e)
                return False
        success = await asyncio.to_thread(_pg_start)
        await asyncio.sleep(0.4)
        return pygame.mixer.music.get_busy()

    def save_style_config(self):
        self.config["style_config"] = state.style_config
        try:
            with open(settings.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print("保存配置失败:", e)

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
        self.lbl_bili_status.config(text=bili_status, fg=bili_color)

        qq_status = "❌ 未登录"
        qq_color = "red"
        if os.path.exists(settings.CREDENTIAL_FILE):
            try:
                with open(settings.CREDENTIAL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("musicid") and data.get("musickey"):
                        qq_status = f"✅ 已登录 (账号UID: {data['musicid']})"
                        qq_color = "green"
            except Exception:
                pass
        self.lbl_qq_status.config(text=qq_status, fg=qq_color)

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        top_frame = tk.Frame(self.root, bg="#f8f9fa", pady=5, padx=5)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text="📋 浏览器源:", bg="#f8f9fa", font=("微软雅黑", 10, "bold")).pack(side=tk.LEFT, padx=(0,5))
        
        tk.Button(top_frame, text="综合挂件", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080"), bg="#607D8B", fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(top_frame, text="纯歌词", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080/lyric"), bg="#607D8B", fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(top_frame, text="正在播放", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080/playing"), bg="#FF9800", fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(top_frame, text="点歌列表", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080/queue"), bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=2)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # === Tab 1: 运行日志 ===
        tab_log = tk.Frame(notebook)
        notebook.add(tab_log, text="📝 运行日志")
        self.log_text = scrolledtext.ScrolledText(tab_log, font=("Consolas", 10), bg="#1e1e1e", fg="#00ff00", relief=tk.FLAT)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # === Tab 2: 账号与登录 ===
        tab_account = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_account, text="🔐 账号与登录")
        account_inner = tk.Frame(tab_account, bg="#f0f0f0", padx=20, pady=20)
        account_inner.pack(fill=tk.BOTH, expand=True)

        bili_group = tk.LabelFrame(account_inner, text="B站直播间", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        bili_group.pack(fill=tk.X, pady=10)
        self.lbl_bili_status = tk.Label(bili_group, text="⏳ 检测中...", font=("微软雅黑", 11), bg="#f0f0f0")
        self.lbl_bili_status.pack(anchor="w", padx=10, pady=5)
        tk.Button(bili_group, text="🔄 重新登录 B站", bg="#2196F3", fg="white", font=("微软雅黑", 10, "bold"), command=lambda: browserlogin.bilibili_auto_login(self)).pack(anchor="w", padx=10, pady=(0, 10))

        qq_group = tk.LabelFrame(account_inner, text="QQ音乐账号", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        qq_group.pack(fill=tk.X, pady=10)
        self.lbl_qq_status = tk.Label(qq_group, text="⏳ 检测中...", font=("微软雅黑", 11), bg="#f0f0f0")
        self.lbl_qq_status.pack(anchor="w", padx=10, pady=5)
        tk.Button(qq_group, text="📱 扫码登录 QQ 音乐", bg="#FF9800", fg="white", font=("微软雅黑", 10, "bold"), command=lambda: browserlogin.qq_scan_login(self)).pack(anchor="w", padx=10, pady=(0, 10))
        tk.Button(account_inner, text="🔄 刷新状态", bg="#9E9E9E", fg="white", command=self.update_account_status).pack(pady=10)

        # === Tab 3: 音质与缓存 ===
        tab_basic = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_basic, text="🎵 音质与缓存")
        basic_inner = tk.Frame(tab_basic, bg="#f0f0f0", padx=20, pady=20)
        basic_inner.pack(fill=tk.BOTH, expand=True)

        quality_group = tk.LabelFrame(basic_inner, text="点歌音质", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        quality_group.pack(fill=tk.X, pady=5)
        tk.Label(quality_group, text="首选音质:", bg="#f0f0f0").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        self.var_audio_quality = tk.StringVar(value=settings.QUALITY_UI_MAP.get(settings.normalize_quality_key(state.style_config.get("audio_quality", "flac")), "FLAC 无损品质"))
        self.combo_quality_top = ttk.Combobox(quality_group, textvariable=self.var_audio_quality, values=list(settings.QUALITY_UI_MAP.values()), state="readonly", width=25)
        self.combo_quality_top.bind("<<ComboboxSelected>>", self.update_audio_quality)
        self.combo_quality_top.grid(row=0, column=1, sticky="w")

        path_group = tk.LabelFrame(basic_inner, text="本地客户端路径", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        path_group.pack(fill=tk.X, pady=5)
        tk.Label(path_group, text="QQ音乐路径:", bg="#f0f0f0").pack(side=tk.LEFT, padx=10, pady=10)
        self.entry_qq_path = tk.Entry(path_group, width=40, font=("微软雅黑", 9))
        self.entry_qq_path.insert(0, self.config.get("qqmusic_path", ""))
        self.entry_qq_path.pack(side=tk.LEFT, padx=5)
        tk.Button(path_group, text="浏览...", command=self.browse_qq_path, bg="#9E9E9E", fg="white").pack(side=tk.LEFT, padx=5)

        cache_group = tk.LabelFrame(basic_inner, text="缓存自动清理限制", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        cache_group.pack(fill=tk.X, pady=5)
        tk.Label(cache_group, text="最多保留歌曲数:", bg="#f0f0f0").grid(row=0, column=0, padx=10, pady=5, sticky="e")
        self.entry_max_files = tk.Entry(cache_group, width=10)
        self.entry_max_files.insert(0, str(state.style_config.get("max_cache_files", 100)))
        self.entry_max_files.grid(row=0, column=1, sticky="w")
        self.entry_max_files.bind("<KeyRelease>", self.update_cache_settings)
        
        tk.Label(cache_group, text="最大占用体积(MB):", bg="#f0f0f0").grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.entry_max_size = tk.Entry(cache_group, width=10)
        self.entry_max_size.insert(0, str(state.style_config.get("max_cache_size_mb", 500)))
        self.entry_max_size.grid(row=1, column=1, sticky="w")
        self.entry_max_size.bind("<KeyRelease>", self.update_cache_settings)

        # ==========================================
        # Tab 4: 综合挂件设置
        # ==========================================
        tab_mixed = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_mixed, text="🎨 综合挂件")
        mixed_inner = tk.Frame(tab_mixed, bg="#f0f0f0", padx=20, pady=20)
        mixed_inner.pack(fill=tk.BOTH, expand=True)

        self.var_mix_sp = tk.BooleanVar(value=state.style_config['mixed']['show_playing'])
        self.var_mix_sl = tk.BooleanVar(value=state.style_config['mixed']['show_lyric'])
        self.var_mix_sq = tk.BooleanVar(value=state.style_config['mixed']['show_queue'])
        self.var_mix_bp = tk.BooleanVar(value=state.style_config['mixed']['bold_playing'])
        self.var_mix_bl = tk.BooleanVar(value=state.style_config['mixed']['bold_lyric'])
        self.var_mix_bq = tk.BooleanVar(value=state.style_config['mixed']['bold_queue'])

        chk_frame = tk.Frame(mixed_inner, bg="#f0f0f0"); chk_frame.pack(fill=tk.X, pady=5)
        tk.Checkbutton(chk_frame, text="显示【正在播放】", variable=self.var_mix_sp, command=lambda: self.update_mixed("show_playing", self.var_mix_sp.get()), bg="#f0f0f0").pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(chk_frame, text="显示【实时歌词】", variable=self.var_mix_sl, command=lambda: self.update_mixed("show_lyric", self.var_mix_sl.get()), bg="#f0f0f0").pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(chk_frame, text="显示【点歌列表】", variable=self.var_mix_sq, command=lambda: self.update_mixed("show_queue", self.var_mix_sq.get()), bg="#f0f0f0").pack(side=tk.LEFT, padx=5)

        tk.Label(mixed_inner, text="--- 正在播放样式 ---", bg="#f0f0f0", font=("微软雅黑", 9, "bold")).pack(anchor="w", pady=(10,0))
        f1 = tk.Frame(mixed_inner, bg="#f0f0f0"); f1.pack(fill=tk.X, pady=2)
        self.combo_mix_font_playing = ttk.Combobox(f1, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal", width=22)
        self.combo_mix_font_playing.set(state.style_config['mixed']['font_playing'])
        self.combo_mix_font_playing.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("font_playing", self.combo_mix_font_playing.get()))
        self.combo_mix_font_playing.bind("<KeyRelease>", lambda e: self.update_mixed("font_playing", self.combo_mix_font_playing.get()))
        self.combo_mix_font_playing.pack(side=tk.LEFT, padx=2)
        tk.Button(f1, text="颜色", command=lambda: self.pick_mixed("color_playing", "lbl_mix_color_playing"), bg="#e0e0e0").pack(side=tk.LEFT, padx=2)
        self.lbl_mix_color_playing = tk.Label(f1, text=state.style_config['mixed']['color_playing'], bg=state.style_config['mixed']['color_playing'], width=7)
        self.lbl_mix_color_playing.pack(side=tk.LEFT, padx=2)
        tk.Label(f1, text="字号:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(3,1))
        scale_sp = tk.Scale(f1, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_mixed("size_playing", int(e)), length=80, bg="#f0f0f0")
        scale_sp.set(state.style_config['mixed']['size_playing'])
        scale_sp.pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f1, text="加粗", variable=self.var_mix_bp, command=lambda: self.update_mixed("bold_playing", self.var_mix_bp.get()), bg="#f0f0f0").pack(side=tk.LEFT)

        tk.Label(mixed_inner, text="--- 实时歌词样式 ---", bg="#f0f0f0", font=("微软雅黑", 9, "bold")).pack(anchor="w", pady=(10,0))
        f2 = tk.Frame(mixed_inner, bg="#f0f0f0"); f2.pack(fill=tk.X, pady=2)
        self.combo_mix_font_lyric = ttk.Combobox(f2, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal", width=22)
        self.combo_mix_font_lyric.set(state.style_config['mixed']['font_lyric'])
        self.combo_mix_font_lyric.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("font_lyric", self.combo_mix_font_lyric.get()))
        self.combo_mix_font_lyric.bind("<KeyRelease>", lambda e: self.update_mixed("font_lyric", self.combo_mix_font_lyric.get()))
        self.combo_mix_font_lyric.pack(side=tk.LEFT, padx=2)
        tk.Button(f2, text="颜色", command=lambda: self.pick_mixed("color_lyric", "lbl_mix_color_lyric"), bg="#e0e0e0").pack(side=tk.LEFT, padx=2)
        self.lbl_mix_color_lyric = tk.Label(f2, text=state.style_config['mixed']['color_lyric'], bg=state.style_config['mixed']['color_lyric'], width=7)
        self.lbl_mix_color_lyric.pack(side=tk.LEFT, padx=2)
        tk.Label(f2, text="字号:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(3,1))
        scale_sl = tk.Scale(f2, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_mixed("size_lyric", int(e)), length=80, bg="#f0f0f0")
        scale_sl.set(state.style_config['mixed']['size_lyric'])
        scale_sl.pack(side=tk.LEFT, padx=2)
        eff_mix = ttk.Combobox(f2, values=["高清平滑滚动", "苹果景深滚动", "无滚动 (静态)"], state="readonly", width=11)
        eff_mix_map = {"apple_hd": "高清平滑滚动", "apple_blur": "苹果景深滚动", "static": "无滚动 (静态)"}
        eff_mix.set(eff_mix_map.get(state.style_config['mixed']['effect_lyric'], "高清平滑滚动"))
        eff_mix.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("effect_lyric", {"高清平滑滚动":"apple_hd", "苹果景深滚动":"apple_blur", "无滚动 (静态)":"static"}[eff_mix.get()]))
        eff_mix.pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f2, text="加粗", variable=self.var_mix_bl, command=lambda: self.update_mixed("bold_lyric", self.var_mix_bl.get()), bg="#f0f0f0").pack(side=tk.LEFT)

        tk.Label(mixed_inner, text="--- 点歌列表样式 ---", bg="#f0f0f0", font=("微软雅黑", 9, "bold")).pack(anchor="w", pady=(10,0))
        f3 = tk.Frame(mixed_inner, bg="#f0f0f0"); f3.pack(fill=tk.X, pady=2)
        self.combo_mix_font_queue = ttk.Combobox(f3, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal", width=22)
        self.combo_mix_font_queue.set(state.style_config['mixed']['font_queue'])
        self.combo_mix_font_queue.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("font_queue", self.combo_mix_font_queue.get()))
        self.combo_mix_font_queue.bind("<KeyRelease>", lambda e: self.update_mixed("font_queue", self.combo_mix_font_queue.get()))
        self.combo_mix_font_queue.pack(side=tk.LEFT, padx=2)
        tk.Button(f3, text="颜色", command=lambda: self.pick_mixed("color_queue", "lbl_mix_color_queue"), bg="#e0e0e0").pack(side=tk.LEFT, padx=2)
        self.lbl_mix_color_queue = tk.Label(f3, text=state.style_config['mixed']['color_queue'], bg=state.style_config['mixed']['color_queue'], width=7)
        self.lbl_mix_color_queue.pack(side=tk.LEFT, padx=2)
        tk.Label(f3, text="字号:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(3,1))
        scale_sq = tk.Scale(f3, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_mixed("size_queue", int(e)), length=80, bg="#f0f0f0")
        scale_sq.set(state.style_config['mixed']['size_queue'])
        scale_sq.pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f3, text="加粗", variable=self.var_mix_bq, command=lambda: self.update_mixed("bold_queue", self.var_mix_bq.get()), bg="#f0f0f0").pack(side=tk.LEFT)

        # ==========================================
        # Tab 5: 纯歌词源设置（已同步完整对齐参数与动效控制，移除了透明度配置）
        # ==========================================
        tab_lyric = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_lyric, text="🎤 纯歌词源")
        lyric_inner = tk.Frame(tab_lyric, bg="#f0f0f0", padx=20, pady=20)
        lyric_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(lyric_inner, text="字体 (可手动输入):", bg="#f0f0f0").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_lyric_font = ttk.Combobox(lyric_inner, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif", "'KaiTi', sans-serif"], state="normal")
        self.combo_lyric_font.set(state.style_config['lyric']['font'])
        self.combo_lyric_font.bind("<<ComboboxSelected>>", lambda e: self.update_lyric("font", self.combo_lyric_font.get()))
        self.combo_lyric_font.bind("<KeyRelease>", lambda e: self.update_lyric("font", self.combo_lyric_font.get()))
        self.combo_lyric_font.grid(row=0, column=1, pady=5, sticky="w")

        tk.Button(lyric_inner, text="修改歌词颜色", command=lambda: self.pick_lyric("color"), bg="#e0e0e0").grid(row=1, column=0, padx=5, pady=5)
        self.lbl_lyric_color = tk.Label(lyric_inner, text=state.style_config['lyric']['color'], bg=state.style_config['lyric']['color'], width=10)
        self.lbl_lyric_color.grid(row=1, column=1, sticky="w")

        tk.Label(lyric_inner, text="歌词字号:", bg="#f0f0f0").grid(row=2, column=0, padx=5, sticky="e")
        self.scale_lyric_size = tk.Scale(lyric_inner, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_lyric("size", int(e)))
        self.scale_lyric_size.set(state.style_config['lyric']['size'])
        self.scale_lyric_size.grid(row=2, column=1, sticky="w")

        # 部署：对齐方式选择组件
        tk.Label(lyric_inner, text="对齐方式:", bg="#f0f0f0").grid(row=3, column=0, padx=5, sticky="e")
        self.combo_lyric_align = ttk.Combobox(lyric_inner, values=["居中对齐", "左对齐", "右对齐"], state="readonly")
        align_map = {"center": "居中对齐", "left": "左对齐", "right": "右对齐"}
        self.combo_lyric_align.set(align_map.get(state.style_config['lyric'].get("align", "center"), "居中对齐"))
        self.combo_lyric_align.bind("<<ComboboxSelected>>", self.update_lyric_align)
        self.combo_lyric_align.grid(row=3, column=1, sticky="w", pady=5)

        tk.Label(lyric_inner, text="滚动效果:", bg="#f0f0f0").grid(row=4, column=0, padx=5, sticky="e")
        self.combo_effect = ttk.Combobox(lyric_inner, values=["高清平滑滚动 (锐利)", "苹果景深滚动 (柔光)", "无滚动 (经典静态)"], state="readonly")
        eff_map = {"apple_hd": "高清平滑滚动 (锐利)", "apple_blur": "苹果景深滚动 (柔光)", "static": "无滚动 (经典静态)"}
        self.combo_effect.set(eff_map.get(state.style_config['lyric']['effect'], "高清平滑滚动 (锐利)"))
        self.combo_effect.bind("<<ComboboxSelected>>", self.update_effect)
        self.combo_effect.grid(row=4, column=1, sticky="w", pady=5)

        tk.Label(lyric_inner, text="上方已播放行数:", bg="#f0f0f0").grid(row=5, column=0, padx=5, sticky="e")
        self.scale_lyric_prev = tk.Scale(lyric_inner, from_=0, to=5, orient=tk.HORIZONTAL, command=lambda e: self.update_lyric("lines_prev", int(e)))
        self.scale_lyric_prev.set(state.style_config['lyric']['lines_prev'])
        self.scale_lyric_prev.grid(row=5, column=1, sticky="w")

        tk.Label(lyric_inner, text="下方未播放行数:", bg="#f0f0f0").grid(row=6, column=0, padx=5, sticky="e")
        self.scale_lyric_next = tk.Scale(lyric_inner, from_=1, to=8, orient=tk.HORIZONTAL, command=lambda e: self.update_lyric("lines_next", int(e)))
        self.scale_lyric_next.set(state.style_config['lyric']['lines_next'])
        self.scale_lyric_next.grid(row=6, column=1, sticky="w")

        tk.Label(lyric_inner, text="纯音乐提示语:", bg="#f0f0f0").grid(row=7, column=0, padx=5, sticky="e")
        self.entry_pure_music = tk.Entry(lyric_inner, width=25)
        self.entry_pure_music.insert(0, state.style_config['lyric']['pure_text'])
        self.entry_pure_music.grid(row=7, column=1, sticky="w", pady=5)
        self.entry_pure_music.bind("<KeyRelease>", lambda e: self.update_lyric("pure_text", self.entry_pure_music.get()))

        self.var_lyric_bold = tk.BooleanVar(value=state.style_config['lyric']['is_bold'])
        tk.Checkbutton(lyric_inner, text="字体加粗", variable=self.var_lyric_bold, command=lambda: self.update_lyric("is_bold", self.var_lyric_bold.get()), bg="#f0f0f0").grid(row=8, column=1, sticky="w", pady=5)

        # ==========================================
        # Tab 6: 正在播放源设置
        # ==========================================
        tab_playing = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_playing, text="📺 正在播放源")
        playing_inner = tk.Frame(tab_playing, bg="#f0f0f0", padx=20, pady=20)
        playing_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(playing_inner, text="字体 (可手动输入):", bg="#f0f0f0").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_playing_font = ttk.Combobox(playing_inner, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal")
        self.combo_playing_font.set(state.style_config['playing']['font'])
        self.combo_playing_font.bind("<<ComboboxSelected>>", lambda e: self.update_playing("font", self.combo_playing_font.get()))
        self.combo_playing_font.bind("<KeyRelease>", lambda e: self.update_playing("font", self.combo_playing_font.get()))
        self.combo_playing_font.grid(row=0, column=1, pady=5, sticky="w")

        tk.Button(playing_inner, text="修改颜色", command=lambda: self.pick_playing("color"), bg="#e0e0e0").grid(row=1, column=0, padx=5, pady=5)
        self.lbl_playing_color = tk.Label(playing_inner, text=state.style_config['playing']['color'], bg=state.style_config['playing']['color'], width=10)
        self.lbl_playing_color.grid(row=1, column=1, sticky="w")

        tk.Label(playing_inner, text="字号:", bg="#f0f0f0").grid(row=2, column=0, padx=5, sticky="e")
        self.scale_playing_size = tk.Scale(playing_inner, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_playing("size", int(e)))
        self.scale_playing_size.set(state.style_config['playing']['size'])
        self.scale_playing_size.grid(row=2, column=1, sticky="w")

        self.var_show_prefix = tk.BooleanVar(value=state.style_config['playing']['show_prefix'])
        tk.Checkbutton(playing_inner, text="显示“正在播放”前缀", variable=self.var_show_prefix, command=lambda: self.update_playing("show_prefix", self.var_show_prefix.get()), bg="#f0f0f0").grid(row=3, column=0, columnspan=2, sticky="w", pady=5)

        self.var_playing_bold = tk.BooleanVar(value=state.style_config['playing']['is_bold'])
        tk.Checkbutton(playing_inner, text="字体加粗", variable=self.var_playing_bold, command=lambda: self.update_playing("is_bold", self.var_playing_bold.get()), bg="#f0f0f0").grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

        # ==========================================
        # Tab 7: 点歌列表源设置
        # ==========================================
        tab_queue = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_queue, text="📜 点歌列表源")
        queue_inner = tk.Frame(tab_queue, bg="#f0f0f0", padx=20, pady=20)
        queue_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(queue_inner, text="字体 (可手动输入):", bg="#f0f0f0").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_queue_font = ttk.Combobox(queue_inner, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal")
        self.combo_queue_font.set(state.style_config['queue']['font'])
        self.combo_queue_font.bind("<<ComboboxSelected>>", lambda e: self.update_queue("font", self.combo_queue_font.get()))
        self.combo_queue_font.bind("<KeyRelease>", lambda e: self.update_queue("font", self.combo_queue_font.get()))
        self.combo_queue_font.grid(row=0, column=1, pady=5, sticky="w")

        tk.Button(queue_inner, text="修改颜色", command=lambda: self.pick_queue("color"), bg="#e0e0e0").grid(row=1, column=0, padx=5, pady=5)
        self.lbl_queue_color = tk.Label(queue_inner, text=state.style_config['queue']['color'], bg=state.style_config['queue']['color'], width=10)
        self.lbl_queue_color.grid(row=1, column=1, sticky="w")

        tk.Label(queue_inner, text="字号:", bg="#f0f0f0").grid(row=2, column=0, padx=5, sticky="e")
        self.scale_queue_size = tk.Scale(queue_inner, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_queue("size", int(e)))
        self.scale_queue_size.set(state.style_config['queue']['size'])
        self.scale_queue_size.grid(row=2, column=1, sticky="w")

        tk.Label(queue_inner, text="列表最多字数:", bg="#f0f0f0").grid(row=3, column=0, padx=5, sticky="e")
        self.scale_max_chars = tk.Scale(queue_inner, from_=10, to=60, orient=tk.HORIZONTAL, command=lambda e: self.update_queue("max_chars", int(e)))
        self.scale_max_chars.set(state.style_config['queue']['max_chars'])
        self.scale_max_chars.grid(row=3, column=1, sticky="w", pady=5)

        self.var_queue_bold = tk.BooleanVar(value=state.style_config['queue']['is_bold'])
        tk.Checkbutton(queue_inner, text="字体加粗", variable=self.var_queue_bold, command=lambda: self.update_queue("is_bold", self.var_queue_bold.get()), bg="#f0f0f0").grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

        self.update_account_status()
        
        bottom_frame = tk.Frame(self.root, bg="#e0e0e0", pady=5)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.lbl_engine_status = tk.Label(bottom_frame, text="⏳ 正在检测音频驱动...", bg="#e0e0e0", fg="#555555", font=("微软雅黑", 9, "bold"))
        self.lbl_engine_status.pack()

    # === 回调 ===
    def update_mixed(self, key, val): state.style_config["mixed"][key] = val; self.schedule_save_style()
    def update_lyric(self, key, val): state.style_config["lyric"][key] = val; self.schedule_save_style()
    def update_playing(self, key, val): state.style_config["playing"][key] = val; self.schedule_save_style()
    def update_queue(self, key, val): state.style_config["queue"][key] = val; self.schedule_save_style()

    def update_lyric_align(self, event):
        val = self.combo_lyric_align.get()
        m = {"居中对齐": "center", "左对齐": "left", "右对齐": "right"}
        state.style_config["lyric"]["align"] = m.get(val, "center")
        self.schedule_save_style()

    def pick_mixed(self, key, lbl_name):
        c = colorchooser.askcolor(title="选择颜色")[1]
        if c:
            state.style_config["mixed"][key] = c
            getattr(self, lbl_name).config(bg=c, text=c)
            self.schedule_save_style()

    def pick_lyric(self, key):
        c = colorchooser.askcolor(title="选择歌词颜色")[1]
        if c: state.style_config["lyric"][key] = c; self.lbl_lyric_color.config(bg=c, text=c); self.schedule_save_style()

    def pick_playing(self, key):
        c = colorchooser.askcolor(title="选择播放颜色")[1]
        if c: state.style_config["playing"][key] = c; self.lbl_playing_color.config(bg=c, text=c); self.schedule_save_style()

    def pick_queue(self, key):
        c = colorchooser.askcolor(title="选择列表颜色")[1]
        if c: state.style_config["queue"][key] = c; self.lbl_queue_color.config(bg=c, text=c); self.schedule_save_style()

    def update_effect(self, event):
        val = self.combo_effect.get()
        m = {"高清平滑滚动 (锐利)": "apple_hd", "高清平滑滚动": "apple_hd", "苹果景深滚动 (柔光)": "apple_blur", "苹果景深滚动": "apple_blur", "无滚动 (经典静态)": "static", "无滚动 (静态)": "static"}
        state.style_config["lyric"]["effect"] = m.get(val, "apple_hd")
        self.schedule_save_style()

    def update_audio_quality(self, event=None):
        val = self.var_audio_quality.get()
        q_key = settings.UI_QUALITY_MAP.get(val)
        state.style_config["audio_quality"] = settings.normalize_quality_key(q_key)
        self.schedule_save_style()
        self.log(f"🎵 点歌首选音质已切换为: 【{val}】 (无对应音源时自动平滑降级)")
    
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
        self.loop = asyncio.new_event_loop(); asyncio.set_event_loop(self.loop); self.loop.run_until_complete(self.main_async())

    async def main_async(self):
        global skip_event; state.skip_event = asyncio.Event()
        self.log("正在启动 OBS 服务器...")
        web_app = web.Application()
        web_app.router.add_get('/', overlay.handle_index)
        web_app.router.add_get('/lyric', overlay.handle_index)
        web_app.router.add_get('/playing', overlay.handle_index)
        web_app.router.add_get('/queue', overlay.handle_index)
        web_app.router.add_get('/api/data', overlay.handle_api)
        
        runner = web.AppRunner(web_app); await runner.setup(); site = web.TCPSite(runner, '127.0.0.1', 8080); await site.start()
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
                
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Referer": f"https://live.bilibili.com/{self.config.get('room_id', '')}", "Origin": "https://live.bilibili.com"}
        
        async with aiohttp.ClientSession(cookies=cookies, headers=headers, trust_env=False) as http_session:
            if self.config.get('room_id'):
                client = blivedm.BLiveClient(int(self.config['room_id']), session=http_session)
                client.set_handler(danmaku.BiliHandler(self)); client.start(); self.log("✅ 连接 B 站成功！等待弹幕中...")
                try:
                    while True: await asyncio.sleep(3600)
                finally: await client.stop_and_close()
            else:
                self.log("❌ 缺少房间号，请点击顶部登录 B站！")
                while True: await asyncio.sleep(3600)

    async def fetch_lyrics_by_mid_or_keyword(self, song_mid=None, keyword=None):
        try:
            if song_mid and song_mid in state.lyric_cache: return state.lyric_cache[song_mid]
            async with Client(credential=state.qq_credential) as client:
                if not song_mid and keyword:
                    search_res = await client.search.search_by_type(keyword=keyword, num=1)
                    song_mid, _, _, _ = musiclib.extract_song_info(search_res)
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
                    if state.current_play_mode == "api" and self.player_is_busy():
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
        while True:
            try:
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
                        elif smtc_pos is not None and abs(smtc_pos - last_smtc_pos) > 1.5:
                            last_smtc_pos = smtc_pos; state.active_song_base_pos = smtc_pos; state.active_song_start_ts = time.time()
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

        # ===== 首次请求前预热：给CDN和网络连接足够的初始化时间 =====
        self.log(f"[INFO] 开始下载预热，等待网络初始化...")
        await asyncio.sleep(1.5)  # 预热延迟：给CDN节点分配和连接池初始化留时间
        
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

                        if attempt == 0:
                            self.log(f"[INFO] 首次下载 [{tier_label}]: {display_name} (URL有效期字段: {detail.get('expiration')})...")
                        else:
                            self.log(f"[INFO] 重试下载 [{tier_label}] (第{attempt+1}/{retries}次)...")

                        async with aiohttp.ClientSession(trust_env=False, headers=headers) as session:
                            async with session.get(fresh_url, timeout=30) as resp:
                                if resp.status in (200, 206):
                                    data = await resp.read()
                                    if data:
                                        with open(file_path, "wb") as f: f.write(data)
                                        size_mb = len(data) / (1024 * 1024)
                                        self.log(f"[INFO] ✅ 下载完成 [{tier_label}] ({size_mb:.1f} MB): {display_name} | 文件路径: {file_path}")
                                        musiclib.clean_cache_if_needed()
                                        self.last_download_reason = "downloaded"
                                        return file_path, display_name, song_mid
                                elif resp.status == 403:
                                    self.log(f"[{tier_label}] 下载被拦截(403)，将刷新CDN节点和链接后重试...")
                                    retry_delay = 2 + random.uniform(0, 1.5)  # 基础2秒 + 随机抖动0~1.5秒
                                    self.log(f"[INFO] 403等待 {retry_delay:.1f}秒后重试 (CDN刷新+随机抖动避免限流)")
                                    await asyncio.sleep(retry_delay)
                                else:
                                    self.log(f"[{tier_label}] 下载失败: HTTP {resp.status}")
                                    break
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
                self.log(f"▶️ 准备播放: {state.current_song['display_name']}-{requester}")
                song_mid = state.current_song.get("mid")

                preferred_q = settings.normalize_quality_key(state.style_config.get("audio_quality", "flac"))

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
                    state.active_lrc_lines = await self.fetch_lyrics_by_mid_or_keyword(song_mid=song_mid, keyword=state.current_song['display_name'])
                    
                    if not state.active_lrc_lines:
                        state.active_lrc_lines = [(0.0, state.style_config["lyric"].get("pure_text", "纯音乐, 请欣赏.."))]

                    try:
                        started = await self.player_load_and_play(file_path)
                        state.active_song_start_ts = time.time()
                        state.active_song_base_pos = 0.0

                        if not started or not self.player_is_busy():
                            self.log(f"⚠️ 播放瞬间结束，可能是文件损坏或解码异常，自动清理并跳过: {real_name}")
                            try:
                                if os.path.exists(file_path): os.remove(file_path)
                            except Exception as e:
                                print(f"[WARN] 异常已捕获: {e}")

                            state.current_song = None; state.active_lrc_lines = []
                            continue

                        while self.player_is_busy():
                            if state.skip_event.is_set():
                                self.player_stop(); state.skip_event.clear(); break
                            await asyncio.sleep(0.25)
                    except Exception as e:
                        self.log(f"❌ 播放失败: {type(e).__name__}: {e}")
                        try:
                            if os.path.exists(file_path): os.remove(file_path)
                        except Exception as e:
                            print(f"[WARN] 异常已捕获: {e}")


                state.current_song = None; state.active_lrc_lines = []

                if len(state.playlist) == 0 and state.current_play_mode == "api":
                    await asyncio.sleep(0.5)
                    if len(state.playlist) == 0:
                        state.system_media_info = {"title": "暂无播放", "artist": ""}
                        await self.control_local_music(pause=False)
                        state.current_play_mode = "local"
            await asyncio.sleep(0.5)
