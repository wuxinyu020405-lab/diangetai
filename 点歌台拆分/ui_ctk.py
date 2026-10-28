# -*- coding: utf-8 -*-
"""customtkinter 界面层：只负责"长得好看 + 把值写进 style_config"。

设计约束（与 mainapp.py 的契约，不能破）：
- 所有控件属性名沿用旧版（self.lbl_bili_status / self.scale_volume / self.log_text …），
  因为 mainapp 的回调、状态刷新、日志输出都直接引用它们。
- 回调统一走 self.update_mixed / update_lyric / update_playing / update_queue /
  update_audio_quality / update_cache_settings / pick_* 等既有方法，界面不自己写配置。
- 本模块不 import mainapp，避免循环依赖：由 MusicApp 调用 build(self, root)。
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import colorchooser, messagebox

import browserlogin
import state
import settings


# ── 主题 ────────────────────────────────────────────────────────────
ACCENT = ("#2563EB", "#3B82F6")      # 主色（浅色模式, 深色模式）
OK = "#22C55E"
WARN = "#F59E0B"
ERR = "#EF4444"
MUTED = ("#64748B", "#94A3B8")


def _font(size=13, bold=False):
    return ctk.CTkFont(family="Microsoft YaHei UI", size=size, weight="bold" if bold else "normal")


def _section(parent, title, desc=None):
    """一个卡片区块：标题 + 可选说明 + 内容容器。"""
    card = ctk.CTkFrame(parent, corner_radius=10, fg_color=("white", "#1E293B"))
    card.pack(fill="x", padx=4, pady=(0, 10))
    head = ctk.CTkFrame(card, fg_color="transparent")
    head.pack(fill="x", padx=14, pady=(12, 0))
    ctk.CTkLabel(head, text=title, font=_font(13, True), anchor="w").pack(side="left")
    if desc:
        ctk.CTkLabel(head, text=desc, font=_font(11), text_color=MUTED, anchor="w").pack(side="left", padx=(8, 0))
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="x", padx=14, pady=(6, 12))
    return body


def _row(parent, label, hint=None):
    """一行：左标签 + 右容器（返回容器供放控件）。"""
    r = ctk.CTkFrame(parent, fg_color="transparent")
    r.pack(fill="x", pady=4)
    box = ctk.CTkFrame(r, fg_color="transparent")
    box.pack(side="left", anchor="w", padx=(0, 10))
    ctk.CTkLabel(box, text=label, width=110, anchor="w", font=_font(12)).pack(side="left")
    if hint:
        ctk.CTkLabel(box, text=hint, font=_font(10), text_color=MUTED, anchor="w").pack(side="left", padx=(4, 0))
    holder = ctk.CTkFrame(r, fg_color="transparent")
    holder.pack(side="left", fill="x", expand=True)
    return holder


def live_entry(entry, on_change):
    """CTkEntry 的可靠"内容变化"绑定。
    实测：CTkEntry 不响应 event_generate('<KeyRelease>')（触发 0 次），
    因此改用 tk.StringVar + trace_add 接管；on_change(当前文本) 每次变化触发。"""
    var = tk.StringVar(value=entry.get())
    try:
        entry.configure(textvariable=var)
    except Exception:
        pass

    def _fire(*_a):
        try:
            on_change(var.get())
        except Exception:
            pass

    var.trace_add("write", _fire)
    try:
        entry.bind("<KeyRelease>", lambda _e: _fire())
    except Exception:
        pass
    return var


def build(app, root):
    """把整个界面建出来，并回填所有 self.xxx 控件属性。
    注意：root 必须是 ctk.CTk()（普通 tk.Tk 不支持 fg_color 等参数）。"""
    cfg = state.style_config

    # ── 全局主题 ──
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    try:
        root.configure(fg_color=("#F1F5F9", "#0F172A"))
    except Exception:
        pass    # 万一传入的是普通 tk.Tk，退化为默认外观而非崩溃
    root.title(f"点歌台控制台 · 房间 {app.config.get('room_id') or '未配置'}")
    root.geometry("880x820")
    root.minsize(760, 640)

    # ── 顶部：品牌 + 状态灯 + 复制源地址 ──
    top = ctk.CTkFrame(root, corner_radius=0, height=64, fg_color=("#FFFFFF", "#111C33"))
    top.pack(fill="x")
    top.pack_propagate(False)
    brand = ctk.CTkFrame(top, fg_color="transparent")
    brand.pack(side="left", padx=16)
    ctk.CTkLabel(brand, text="🎤 点歌台", font=_font(18, True)).pack(side="left")
    ctk.CTkLabel(brand, text="B站直播 · QQ音乐 · OBS 挂件", font=_font(11),
                 text_color=MUTED).pack(side="left", padx=(10, 0))

    src_bar = ctk.CTkFrame(top, fg_color="transparent")
    src_bar.pack(side="right", padx=12)
    for text, path, color in [
        ("综合挂件", "", ("#334155", "#1E293B")),
        ("纯歌词", "/lyric", ("#334155", "#1E293B")),
        ("正在播放", "/playing", ("#334155", "#1E293B")),
        ("点歌列表", "/queue", ("#334155", "#1E293B")),
    ]:
        # 端口在点击时才读 state.overlay_port：8080 被占时程序会自动顺延，
        # 构建界面那一刻端口还没定，不能提前把 8080 拼死。
        ctk.CTkButton(src_bar, text=text, width=76, height=30, corner_radius=8,
                      fg_color=color, hover_color=ACCENT, font=_font(11),
                      command=lambda p=path: app.copy_to_clipboard(
                          f"http://127.0.0.1:{state.overlay_port}{p}")).pack(side="left", padx=3)

    # ── 标签页（标准 CTkTabview，不做自定义切换优化）──
    name_log = "运行日志"
    name_acct = "账号登录"
    name_basic = "音质缓存"
    name_mix = "综合挂件"
    name_lyric = "纯歌词"
    name_play = "正在播放"
    name_queue = "点歌列表"
    PAGE_NAMES = [name_log, name_acct, name_basic, name_mix, name_lyric, name_play, name_queue]

    tabs = ctk.CTkTabview(
        root,
        corner_radius=10,
        fg_color=("#FFFFFF", "#0B1220"),
        segmented_button_fg_color=("#E2E8F0", "#1E293B"),
        segmented_button_selected_color=ACCENT,
        segmented_button_selected_hover_color=ACCENT,
        segmented_button_unselected_color=("#E2E8F0", "#1E293B"),
        segmented_button_unselected_hover_color=("#CBD5E1", "#334155"),
        text_color=("#0F172A", "#E2E8F0"),
    )
    tabs.pack(fill="both", expand=True, padx=12, pady=(10, 6))
    for n in PAGE_NAMES:
        tabs.add(n)

    pages = {n: tabs.tab(n) for n in PAGE_NAMES}

    def scroller(page):
        # 不用 CTkScrollableFrame（每次切换要重算滚动区域，首建也慢）。
        # 内容按 880x820 窗口高度设计，无需滚动；真需要时再换回。
        f = ctk.CTkFrame(page, fg_color="transparent")
        f.pack(fill="both", expand=True, padx=2, pady=2)
        return f

    # ══════════════════ 运行日志 ══════════════════
    # 用原生 tk.Text 而非 CTkTextbox：CTkTextbox 内部包了 tk.Text + Canvas，
    # 每次 unmap/map 要重建结构，实测切换来回 ~110ms（是卡顿主因）。
    # tk.Text 直接映射，切换 ~4ms。外观用配色贴近深色终端即可。
    log_page = pages[name_log]
    log_wrap = ctk.CTkFrame(log_page, corner_radius=8, fg_color="#0B1220")
    log_wrap.pack(fill="both", expand=True, padx=6, pady=6)
    app.log_text = tk.Text(log_wrap, bg="#0B1220", fg="#7DE38B", insertbackground="#7DE38B",
                           relief="flat", borderwidth=0, wrap="word", padx=10, pady=8,
                           font=("Cascadia Mono", 11), selectbackground="#1E3A5F")
    _log_sb = tk.Scrollbar(log_wrap, command=app.log_text.yview, width=10)
    app.log_text.configure(yscrollcommand=_log_sb.set)
    _log_sb.pack(side="right", fill="y")
    app.log_text.pack(side="left", fill="both", expand=True)
    # 兼容旧调用 app.log_text.insert(tk.END, ...) / .see(tk.END) —— 原生 Text 都支持

    # ══════════════════ 账号登录 ══════════════════
    acct_page = pages[name_acct]
    acct_sc = scroller(acct_page)

    b = _section(acct_sc, "B站直播间", "弹幕来源")
    app.lbl_bili_status = ctk.CTkLabel(b, text="⏳ 检测中...", font=_font(12), anchor="w")
    app.lbl_bili_status.pack(anchor="w", pady=(0, 8))
    ctk.CTkButton(b, text="🔄 重新登录 B站", height=34, corner_radius=8, font=_font(12, True),
                  fg_color=ACCENT, hover_color=("#1D4ED8", "#60A5FA"),
                  command=lambda: browserlogin.bilibili_auto_login(app)).pack(anchor="w")

    b = _section(acct_sc, "QQ音乐账号", "VIP 音质所需")
    app.lbl_qq_status = ctk.CTkLabel(b, text="⏳ 检测中...", font=_font(12), anchor="w")
    app.lbl_qq_status.pack(anchor="w", pady=(0, 8))
    ctk.CTkButton(b, text="📱 扫码登录 QQ音乐", height=34, corner_radius=8, font=_font(12, True),
                  fg_color=WARN, hover_color="#D97706",
                  command=lambda: browserlogin.qq_scan_login(app)).pack(anchor="w")

    b = _section(acct_sc, "状态")
    ctk.CTkButton(b, text="🔄 刷新账号状态", width=140, height=30, corner_radius=8,
                  fg_color=("#64748B", "#475569"), font=_font(12),
                  command=app.update_account_status).pack(anchor="w")

    # ══════════════════ 音质缓存 ══════════════════
    basic_page = pages[name_basic]
    basic_sc = scroller(basic_page)

    b = _section(basic_sc, "点歌音质", "无对应音源时自动降级")
    h = _row(b, "首选音质")
    app.var_audio_quality = tk.StringVar(
        value=settings.QUALITY_UI_MAP.get(
            settings.normalize_quality_key(cfg.get("audio_quality", "flac")), "FLAC 无损品质"))
    app.combo_quality_top = ctk.CTkComboBox(h, values=list(settings.QUALITY_UI_MAP.values()),
                                            width=200, font=_font(12), state="readonly",
                                            command=lambda v: app.update_audio_quality())
    app.combo_quality_top.set(app.var_audio_quality.get())
    app.combo_quality_top.pack(side="left")

    h = _row(b, "点歌音量", "作用于 pygame 播放")
    app.scale_volume = ctk.CTkSlider(h, from_=0, to=100, width=220, number_of_steps=100,
                                     command=lambda v: app.apply_volume(slider_val=int(v)))
    app.scale_volume.set(int(round(app.get_volume() * 100)))
    app.scale_volume.pack(side="left")
    app.lbl_volume_pct = ctk.CTkLabel(h, text=f"{int(round(app.get_volume()*100))}%",
                                      width=52, font=_font(12, True))
    app.lbl_volume_pct.pack(side="left", padx=(8, 0))

    b = _section(basic_sc, "本地客户端路径")
    h = _row(b, "QQ音乐路径")
    app.entry_qq_path = ctk.CTkEntry(h, width=300, font=_font(12))
    app.entry_qq_path.insert(0, app.config.get("qqmusic_path", ""))
    app.entry_qq_path.pack(side="left")
    ctk.CTkButton(h, text="浏览", width=64, height=28, corner_radius=8,
                  fg_color=("#64748B", "#475569"), font=_font(11),
                  command=app.browse_qq_path).pack(side="left", padx=(8, 0))

    b = _section(basic_sc, "缓存清理上限", "超出后按最旧优先删除")
    h = _row(b, "最多保留歌曲数")
    app.entry_max_files = ctk.CTkEntry(h, width=100, font=_font(12))
    app.entry_max_files.insert(0, str(cfg.get("max_cache_files", 100)))
    app.entry_max_files.pack(side="left")
    live_entry(app.entry_max_files, lambda v: app.update_cache_settings())
    h = _row(b, "最大占用(MB)")
    app.entry_max_size = ctk.CTkEntry(h, width=100, font=_font(12))
    app.entry_max_size.insert(0, str(cfg.get("max_cache_size_mb", 500)))
    app.entry_max_size.pack(side="left")
    live_entry(app.entry_max_size, lambda v: app.update_cache_settings())

    # ══════════════════ 综合挂件 ══════════════════
    mix_page = pages[name_mix]
    mix_sc = scroller(mix_page)
    mx = cfg["mixed"]

    b = _section(mix_sc, "显示内容")
    hz = ctk.CTkFrame(b, fg_color="transparent"); hz.pack(fill="x")
    app.var_mix_sp = tk.BooleanVar(value=mx.get("show_playing", True))
    app.var_mix_sl = tk.BooleanVar(value=mx.get("show_lyric", True))
    app.var_mix_sq = tk.BooleanVar(value=mx.get("show_queue", True))
    for txt, var, key in [("正在播放", app.var_mix_sp, "show_playing"),
                          ("实时歌词", app.var_mix_sl, "show_lyric"),
                          ("点歌列表", app.var_mix_sq, "show_queue")]:
        ctk.CTkCheckBox(hz, text=txt, variable=var, font=_font(12), checkbox_width=18,
                        checkbox_height=18, corner_radius=4,
                        command=lambda k=key, v=var: app.update_mixed(k, v.get())).pack(side="left", padx=(0, 18))

    b = _section(mix_sc, "歌词", "默认两行：当前行 + 下一行")
    h = _row(b, "滚动效果")
    app.combo_mix_effect = ctk.CTkComboBox(
        h, values=["无滚动 (静态)", "高清平滑滚动", "苹果景深滚动"], width=150,
        font=_font(12), state="readonly",
        command=lambda v: app.update_mixed("effect_lyric",
            {"无滚动 (静态)": "static", "高清平滑滚动": "apple_hd", "苹果景深滚动": "apple_blur"}[v]))
    app.combo_mix_effect.set({"static": "无滚动 (静态)", "apple_hd": "高清平滑滚动",
                              "apple_blur": "苹果景深滚动"}.get(mx.get("effect_lyric"), "无滚动 (静态)"))
    app.combo_mix_effect.pack(side="left")

    h = _row(b, "对齐")
    app.combo_mix_align = ctk.CTkComboBox(
        h, values=["左", "居中", "右"], width=100, font=_font(12), state="readonly",
        command=lambda v: app.update_mixed("align", {"左": "left", "居中": "center", "右": "right"}[v]))
    app.combo_mix_align.set({"left": "左", "center": "居中", "right": "右"}.get(mx.get("align", "left"), "左"))
    app.combo_mix_align.pack(side="left")

    h = _row(b, "上方已播行数")
    app.spin_mix_prev = ctk.CTkEntry(h, width=70, font=_font(12))
    app.spin_mix_prev.insert(0, str(mx.get("lines_prev", 0)))
    app.spin_mix_prev.pack(side="left")
    live_entry(app.spin_mix_prev, lambda v: app.update_mixed("lines_prev", app._spin_int_or(app.spin_mix_prev, 0)))
    h = _row(b, "下方未播行数")
    app.spin_mix_next = ctk.CTkEntry(h, width=70, font=_font(12))
    app.spin_mix_next.insert(0, str(mx.get("lines_next", 1)))
    app.spin_mix_next.pack(side="left")
    live_entry(app.spin_mix_next, lambda v: app.update_mixed("lines_next", app._spin_int_or(app.spin_mix_next, 1)))

    h = _row(b, "字号")
    ctk.CTkLabel(h, text="字号", width=0).pack_forget()
    app.scale_mix_lyric_size = ctk.CTkSlider(h, from_=15, to=80, width=200, number_of_steps=65,
        command=lambda v: app.update_mixed("size_lyric", int(v)))
    app.scale_mix_lyric_size.set(mx.get("size_lyric", 28))
    app.scale_mix_lyric_size.pack(side="left")

    hz = ctk.CTkFrame(b, fg_color="transparent"); hz.pack(fill="x", pady=(4, 0))
    app.var_mix_bl = tk.BooleanVar(value=mx.get("bold_lyric", False))
    ctk.CTkCheckBox(hz, text="歌词加粗", variable=app.var_mix_bl, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_mixed("bold_lyric", app.var_mix_bl.get())).pack(side="left", padx=(0, 16))
    app.combo_mix_font_lyric = ctk.CTkComboBox(hz, values=["'PingFang SC', 'Microsoft YaHei', sans-serif",
                                                          "'Microsoft YaHei', sans-serif"], width=250,
        font=_font(11), command=lambda v: app.update_mixed("font_lyric", v))
    app.combo_mix_font_lyric.set(mx.get("font_lyric", "'Microsoft YaHei', sans-serif"))
    app.combo_mix_font_lyric.pack(side="left")
    ctk.CTkButton(hz, text="颜色", width=56, height=26, corner_radius=8,
                  fg_color=mx.get("color_lyric", "#FFE600"), font=_font(11),
                  command=lambda: app.pick_mixed("color_lyric", "lbl_mix_color_lyric")).pack(side="left", padx=(8, 0))
    app.lbl_mix_color_lyric = ctk.CTkLabel(hz, text=mx.get("color_lyric", "#FFE600"),
        text_color=mx.get("color_lyric", "#FFE600"), width=72, font=_font(11))
    app.lbl_mix_color_lyric.pack(side="left", padx=(6, 0))

    b = _section(mix_sc, "正在播放", "可分别隐藏图标与文字")
    hz = ctk.CTkFrame(b, fg_color="transparent"); hz.pack(fill="x")
    app.var_mix_icon = tk.BooleanVar(value=mx.get("show_icon", True))
    ctk.CTkCheckBox(hz, text="🎵 图标", variable=app.var_mix_icon, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_mixed("show_icon", app.var_mix_icon.get())).pack(side="left", padx=(0, 16))
    app.var_mix_pfx = tk.BooleanVar(value=mx.get("show_prefix", True))
    ctk.CTkCheckBox(hz, text="“正在播放”文字", variable=app.var_mix_pfx, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_mixed("show_prefix", app.var_mix_pfx.get())).pack(side="left", padx=(0, 16))
    app.var_mix_bp = tk.BooleanVar(value=mx.get("bold_playing", False))
    ctk.CTkCheckBox(hz, text="加粗", variable=app.var_mix_bp, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_mixed("bold_playing", app.var_mix_bp.get())).pack(side="left")
    h = _row(b, "字号")
    app.scale_mix_playing_size = ctk.CTkSlider(h, from_=15, to=80, width=200, number_of_steps=65,
        command=lambda v: app.update_mixed("size_playing", int(v)))
    app.scale_mix_playing_size.set(mx.get("size_playing", 32))
    app.scale_mix_playing_size.pack(side="left")

    hz = ctk.CTkFrame(b, fg_color="transparent"); hz.pack(fill="x", pady=(4, 0))
    app.combo_mix_font_playing = ctk.CTkComboBox(hz, values=["'PingFang SC', 'Microsoft YaHei', sans-serif",
                                                            "'Microsoft YaHei', sans-serif"], width=250,
        font=_font(11), command=lambda v: app.update_mixed("font_playing", v))
    app.combo_mix_font_playing.set(mx.get("font_playing", "'Microsoft YaHei', sans-serif"))
    app.combo_mix_font_playing.pack(side="left")
    ctk.CTkButton(hz, text="颜色", width=56, height=26, corner_radius=8,
                  fg_color=mx.get("color_playing", "#00FFFF"), font=_font(11),
                  command=lambda: app.pick_mixed("color_playing", "lbl_mix_color_playing")).pack(side="left", padx=(8, 0))
    app.lbl_mix_color_playing = ctk.CTkLabel(hz, text=mx.get("color_playing", "#00FFFF"),
        text_color=mx.get("color_playing", "#00FFFF"), width=72, font=_font(11))
    app.lbl_mix_color_playing.pack(side="left", padx=(6, 0))

    b = _section(mix_sc, "点歌列表")
    h = _row(b, "最多显示条数", "0 = 不限")
    app.spin_mix_items = ctk.CTkEntry(h, width=70, font=_font(12))
    app.spin_mix_items.insert(0, str(mx.get("max_items", 0)))
    app.spin_mix_items.pack(side="left")
    live_entry(app.spin_mix_items, lambda v: app.update_mixed("max_items", app._spin_int_or(app.spin_mix_items, 0)))
    h = _row(b, "单行最长字数", "0 = 不截断")
    app.spin_mix_chars = ctk.CTkEntry(h, width=70, font=_font(12))
    app.spin_mix_chars.insert(0, str(mx.get("max_chars", 0)))
    app.spin_mix_chars.pack(side="left")
    live_entry(app.spin_mix_chars, lambda v: app.update_mixed("max_chars", app._spin_int_or(app.spin_mix_chars, 0)))

    hz = ctk.CTkFrame(b, fg_color="transparent"); hz.pack(fill="x", pady=(4, 0))
    app.var_mix_sidx = tk.BooleanVar(value=mx.get("show_index", True))
    ctk.CTkCheckBox(hz, text="序号", variable=app.var_mix_sidx, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_mixed("show_index", app.var_mix_sidx.get())).pack(side="left", padx=(0, 16))
    app.var_mix_sreq = tk.BooleanVar(value=mx.get("show_requester", True))
    ctk.CTkCheckBox(hz, text="请求者", variable=app.var_mix_sreq, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_mixed("show_requester", app.var_mix_sreq.get())).pack(side="left", padx=(0, 16))
    app.var_mix_bq = tk.BooleanVar(value=mx.get("bold_queue", False))
    ctk.CTkCheckBox(hz, text="加粗", variable=app.var_mix_bq, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_mixed("bold_queue", app.var_mix_bq.get())).pack(side="left", padx=(0, 16))
    ctk.CTkLabel(hz, text="分隔符", font=_font(11), text_color=MUTED).pack(side="left")
    app.entry_mix_sep = ctk.CTkEntry(hz, width=48, font=_font(12))
    app.entry_mix_sep.insert(0, mx.get("requester_sep", "-"))
    app.entry_mix_sep.pack(side="left", padx=(4, 0))
    live_entry(app.entry_mix_sep, lambda v: app.update_mixed("requester_sep", v or "-"))

    h = _row(b, "字号")
    app.scale_mix_queue_size = ctk.CTkSlider(h, from_=15, to=80, width=200, number_of_steps=65,
        command=lambda v: app.update_mixed("size_queue", int(v)))
    app.scale_mix_queue_size.set(mx.get("size_queue", 36))
    app.scale_mix_queue_size.pack(side="left")

    hz = ctk.CTkFrame(b, fg_color="transparent"); hz.pack(fill="x", pady=(4, 0))
    app.combo_mix_font_queue = ctk.CTkComboBox(hz, values=["'PingFang SC', 'Microsoft YaHei', sans-serif",
                                                          "'Microsoft YaHei', sans-serif"], width=250,
        font=_font(11), command=lambda v: app.update_mixed("font_queue", v))
    app.combo_mix_font_queue.set(mx.get("font_queue", "'Microsoft YaHei', sans-serif"))
    app.combo_mix_font_queue.pack(side="left")
    ctk.CTkButton(hz, text="颜色", width=56, height=26, corner_radius=8,
                  fg_color=mx.get("color_queue", "#FFFFFF"), font=_font(11),
                  command=lambda: app.pick_mixed("color_queue", "lbl_mix_color_queue")).pack(side="left", padx=(8, 0))
    app.lbl_mix_color_queue = ctk.CTkLabel(hz, text=mx.get("color_queue", "#FFFFFF"),
        text_color=mx.get("color_queue", "#FFFFFF"), width=72, font=_font(11))
    app.lbl_mix_color_queue.pack(side="left", padx=(6, 0))

    # ══════════════════ 纯歌词 ══════════════════
    lp = pages[name_lyric]
    lsc = scroller(lp)
    ly = cfg["lyric"]

    b = _section(lsc, "字体与颜色")
    h = _row(b, "字体")
    app.combo_lyric_font = ctk.CTkComboBox(h, values=["'PingFang SC', 'Microsoft YaHei', sans-serif",
                                                      "'Microsoft YaHei', sans-serif", "'KaiTi', sans-serif"],
        width=300, font=_font(11), command=lambda v: app.update_lyric("font", v))
    app.combo_lyric_font.set(ly.get("font", "'Microsoft YaHei', sans-serif"))
    app.combo_lyric_font.pack(side="left")
    h = _row(b, "颜色")
    ctk.CTkButton(h, text="选择颜色", width=88, height=28, corner_radius=8, font=_font(11),
                  fg_color=ly.get("color", "#FFE600"),
                  command=lambda: app.pick_lyric("color")).pack(side="left")
    app.lbl_lyric_color = ctk.CTkLabel(h, text=ly.get("color", "#FFE600"),
        text_color=ly.get("color", "#FFE600"), width=80, font=_font(11))
    app.lbl_lyric_color.pack(side="left", padx=(8, 0))

    b = _section(lsc, "排版")
    h = _row(b, "字号")
    app.scale_lyric_size = ctk.CTkSlider(h, from_=15, to=80, width=220, number_of_steps=65,
        command=lambda v: app.update_lyric("size", int(v)))
    app.scale_lyric_size.set(ly.get("size", 28)); app.scale_lyric_size.pack(side="left")

    h = _row(b, "明暗", "100% = 原始，>100% 提亮暗行")
    app.scale_lyric_op = ctk.CTkSlider(h, from_=10, to=200, width=220, number_of_steps=190,
        command=lambda v: app.update_lyric("opacity", int(v) / 100.0))
    app.scale_lyric_op.set(int(round(ly.get("opacity", 1.0) * 100))); app.scale_lyric_op.pack(side="left")

    h = _row(b, "行间距", "142% = 原始")
    app.scale_lyric_lh = ctk.CTkSlider(h, from_=100, to=400, width=220, number_of_steps=300,
        command=lambda v: app.update_lyric("line_spacing", int(v)))
    app.scale_lyric_lh.set(int(ly.get("line_spacing", 142))); app.scale_lyric_lh.pack(side="left")

    h = _row(b, "对齐")
    app.combo_lyric_align = ctk.CTkComboBox(h, values=["居中对齐", "左对齐", "右对齐"], width=120,
        font=_font(12), state="readonly", command=app.update_lyric_align)
    app.combo_lyric_align.set({"center": "居中对齐", "left": "左对齐", "right": "右对齐"}.get(
        ly.get("align", "center"), "居中对齐"))
    app.combo_lyric_align.pack(side="left")

    h = _row(b, "滚动效果")
    app.combo_effect = ctk.CTkComboBox(h, values=["高清平滑滚动 (锐利)", "苹果景深滚动 (柔光)", "无滚动 (经典静态)"],
        width=180, font=_font(12), state="readonly", command=app.update_effect)
    app.combo_effect.set({"apple_hd": "高清平滑滚动 (锐利)", "apple_blur": "苹果景深滚动 (柔光)",
                          "static": "无滚动 (经典静态)"}.get(ly.get("effect", "apple_hd"), "高清平滑滚动 (锐利)"))
    app.combo_effect.pack(side="left")

    h = _row(b, "上方已播行数")
    app.scale_lyric_prev = ctk.CTkSlider(h, from_=0, to=5, width=180, number_of_steps=5,
        command=lambda v: app.update_lyric("lines_prev", int(v)))
    app.scale_lyric_prev.set(ly.get("lines_prev", 2)); app.scale_lyric_prev.pack(side="left")
    h = _row(b, "下方未播行数")
    app.scale_lyric_next = ctk.CTkSlider(h, from_=1, to=8, width=180, number_of_steps=7,
        command=lambda v: app.update_lyric("lines_next", int(v)))
    app.scale_lyric_next.set(ly.get("lines_next", 2)); app.scale_lyric_next.pack(side="left")

    b = _section(lsc, "其他")
    h = _row(b, "纯音乐提示语")
    app.entry_pure_music = ctk.CTkEntry(h, width=240, font=_font(12))
    app.entry_pure_music.insert(0, ly.get("pure_text", "纯音乐, 请欣赏.."))
    app.entry_pure_music.pack(side="left")
    live_entry(app.entry_pure_music, lambda v: app.update_lyric("pure_text", v))
    app.var_lyric_bold = tk.BooleanVar(value=ly.get("is_bold", False))
    ctk.CTkCheckBox(b, text="字体加粗", variable=app.var_lyric_bold, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_lyric("is_bold", app.var_lyric_bold.get())).pack(anchor="w", pady=(4, 0))

    # ══════════════════ 正在播放 ══════════════════
    pp = pages[name_play]
    psc = scroller(pp)
    pl = cfg["playing"]
    b = _section(psc, "样式")
    h = _row(b, "字体")
    app.combo_playing_font = ctk.CTkComboBox(h, values=["'PingFang SC', 'Microsoft YaHei', sans-serif",
                                                        "'Microsoft YaHei', sans-serif"], width=300,
        font=_font(11), command=lambda v: app.update_playing("font", v))
    app.combo_playing_font.set(pl.get("font", "'Microsoft YaHei', sans-serif")); app.combo_playing_font.pack(side="left")
    h = _row(b, "颜色")
    ctk.CTkButton(h, text="选择颜色", width=88, height=28, corner_radius=8, font=_font(11),
                  fg_color=pl.get("color", "#00FFFF"),
                  command=lambda: app.pick_playing("color")).pack(side="left")
    app.lbl_playing_color = ctk.CTkLabel(h, text=pl.get("color", "#00FFFF"),
        text_color=pl.get("color", "#00FFFF"), width=80, font=_font(11))
    app.lbl_playing_color.pack(side="left", padx=(8, 0))
    h = _row(b, "字号")
    app.scale_playing_size = ctk.CTkSlider(h, from_=15, to=80, width=220, number_of_steps=65,
        command=lambda v: app.update_playing("size", int(v)))
    app.scale_playing_size.set(pl.get("size", 32)); app.scale_playing_size.pack(side="left")
    app.var_show_prefix = tk.BooleanVar(value=pl.get("show_prefix", True))
    ctk.CTkCheckBox(b, text="显示“正在播放”前缀", variable=app.var_show_prefix, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_playing("show_prefix", app.var_show_prefix.get())).pack(anchor="w", pady=(6, 0))
    app.var_playing_bold = tk.BooleanVar(value=pl.get("is_bold", False))
    ctk.CTkCheckBox(b, text="字体加粗", variable=app.var_playing_bold, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_playing("is_bold", app.var_playing_bold.get())).pack(anchor="w", pady=(4, 0))

    # ══════════════════ 点歌列表 ══════════════════
    qp = pages[name_queue]
    qsc = scroller(qp)
    qu = cfg["queue"]
    b = _section(qsc, "样式")
    h = _row(b, "字体")
    app.combo_queue_font = ctk.CTkComboBox(h, values=["'PingFang SC', 'Microsoft YaHei', sans-serif",
                                                      "'Microsoft YaHei', sans-serif"], width=300,
        font=_font(11), command=lambda v: app.update_queue("font", v))
    app.combo_queue_font.set(qu.get("font", "'Microsoft YaHei', sans-serif")); app.combo_queue_font.pack(side="left")
    h = _row(b, "颜色")
    ctk.CTkButton(h, text="选择颜色", width=88, height=28, corner_radius=8, font=_font(11),
                  fg_color=qu.get("color", "#FFFFFF"),
                  command=lambda: app.pick_queue("color")).pack(side="left")
    app.lbl_queue_color = ctk.CTkLabel(h, text=qu.get("color", "#FFFFFF"),
        text_color=qu.get("color", "#FFFFFF"), width=80, font=_font(11))
    app.lbl_queue_color.pack(side="left", padx=(8, 0))
    h = _row(b, "字号")
    app.scale_queue_size = ctk.CTkSlider(h, from_=15, to=80, width=220, number_of_steps=65,
        command=lambda v: app.update_queue("size", int(v)))
    app.scale_queue_size.set(qu.get("size", 36)); app.scale_queue_size.pack(side="left")

    b = _section(qsc, "内容")
    h = _row(b, "最多显示条数", "0 = 不限")
    app.spin_q_items = ctk.CTkEntry(h, width=70, font=_font(12))
    app.spin_q_items.insert(0, str(qu.get("max_items", 0)))
    app.spin_q_items.pack(side="left")
    live_entry(app.spin_q_items, lambda v: app.update_queue("max_items", app._spin_int_or(app.spin_q_items, 0)))
    h = _row(b, "单行最长字数")
    app.scale_max_chars = ctk.CTkSlider(h, from_=10, to=60, width=200, number_of_steps=50,
        command=lambda v: app.update_queue("max_chars", int(v)))
    app.scale_max_chars.set(qu.get("max_chars", 30)); app.scale_max_chars.pack(side="left")
    hz = ctk.CTkFrame(b, fg_color="transparent"); hz.pack(fill="x", pady=(4, 0))
    app.var_q_sidx = tk.BooleanVar(value=qu.get("show_index", True))
    ctk.CTkCheckBox(hz, text="序号", variable=app.var_q_sidx, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_queue("show_index", app.var_q_sidx.get())).pack(side="left", padx=(0, 16))
    app.var_q_sreq = tk.BooleanVar(value=qu.get("show_requester", True))
    ctk.CTkCheckBox(hz, text="请求者", variable=app.var_q_sreq, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_queue("show_requester", app.var_q_sreq.get())).pack(side="left", padx=(0, 16))
    app.var_queue_bold = tk.BooleanVar(value=qu.get("is_bold", False))
    ctk.CTkCheckBox(hz, text="加粗", variable=app.var_queue_bold, font=_font(12),
                    checkbox_width=18, checkbox_height=18, corner_radius=4,
                    command=lambda: app.update_queue("is_bold", app.var_queue_bold.get())).pack(side="left", padx=(0, 16))
    ctk.CTkLabel(hz, text="分隔符", font=_font(11), text_color=MUTED).pack(side="left")
    app.entry_q_sep = ctk.CTkEntry(hz, width=48, font=_font(12))
    app.entry_q_sep.insert(0, qu.get("requester_sep", "-"))
    app.entry_q_sep.pack(side="left", padx=(4, 0))
    live_entry(app.entry_q_sep, lambda v: app.update_queue("requester_sep", v or "-"))

    # ── 底部状态栏 ──
    bottom = ctk.CTkFrame(root, corner_radius=0, height=34, fg_color=("#E2E8F0", "#111C33"))
    bottom.pack(fill="x", side="bottom")
    bottom.pack_propagate(False)
    app.lbl_engine_status = ctk.CTkLabel(bottom, text="⏳ 正在检测音频驱动...",
                                         font=_font(11), text_color=MUTED)
    app.lbl_engine_status.pack(side="left", padx=14)
    ctk.CTkLabel(bottom, text="OBS 源: http://127.0.0.1:8080",
                 font=_font(11), text_color=MUTED).pack(side="right", padx=14)

    # 首屏固定在日志页（CTkTabview 默认停在最后添加的那一页）
    tabs.set(name_log)



def set_label(widget, text=None, color=None, bg=None):
    """兼容 tk.Label 与 CTkLabel 的统一改字/改色入口。
    tk:  fg=<color>, bg=<bg>
    CTk: text_color=<color>, fg_color=<bg>
    """
    if widget is None:
        return
    kw = {}
    if text is not None:
        kw["text"] = text
    is_ctk = hasattr(widget, "_text_label") or widget.__class__.__module__.startswith("customtkinter")
    if color is not None:
        kw["text_color" if is_ctk else "fg"] = color
    if bg is not None:
        kw["fg_color" if is_ctk else "bg"] = bg
    try:
        widget.configure(**kw)
    except Exception:
        # 兜底：逐项尝试，避免一个参数不支持就整条失败
        for k, v in kw.items():
            try:
                widget.configure(**{k: v})
            except Exception:
                pass
