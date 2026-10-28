# -*- coding: utf-8 -*-
"""真实构建 CTk 界面（不启动 worker），验证控件齐全、回调可调。"""
import os
import sys
import traceback

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import customtkinter as ctk
import state
import mainapp

mainapp.MusicApp.start_async_loop = lambda self: None

fails = []
root = ctk.CTk()     # 必须是 CTk 根窗口（与 main.py 一致）
root.withdraw()
try:
    app = mainapp.MusicApp(root, {"room_id": "", "bili_cookie": "", "qqmusic_path": ""})
except Exception:
    traceback.print_exc()
    fails.append("MusicApp 构建失败")

if not fails:
    # 旧版契约里的控件必须都在
    NEED = [
        "log_text", "lbl_bili_status", "lbl_qq_status", "lbl_engine_status",
        "combo_quality_top", "scale_volume", "lbl_volume_pct",
        "entry_qq_path", "entry_max_files", "entry_max_size",
        "var_mix_sp", "var_mix_sl", "var_mix_sq", "var_mix_pfx", "var_mix_icon",
        "var_mix_bp", "var_mix_bl", "var_mix_bq", "var_mix_sidx", "var_mix_sreq",
        "combo_mix_effect", "combo_mix_align", "spin_mix_prev", "spin_mix_next",
        "spin_mix_items", "spin_mix_chars", "entry_mix_sep",
        "combo_mix_font_playing", "combo_mix_font_lyric", "combo_mix_font_queue",
        "lbl_mix_color_playing", "lbl_mix_color_lyric", "lbl_mix_color_queue",
        "combo_lyric_font", "combo_lyric_align", "combo_effect",
        "scale_lyric_size", "scale_lyric_op", "scale_lyric_lh",
        "scale_lyric_prev", "scale_lyric_next", "entry_pure_music",
        "var_lyric_bold", "lbl_lyric_color",
        "combo_playing_font", "scale_playing_size", "var_show_prefix",
        "var_playing_bold", "lbl_playing_color",
        "combo_queue_font", "scale_queue_size", "scale_max_chars",
        "spin_q_items", "entry_q_sep", "var_q_sidx", "var_q_sreq",
        "var_queue_bold", "lbl_queue_color",
    ]
    missing = [n for n in NEED if not hasattr(app, n)]
    if missing:
        fails.append("缺控件: " + ", ".join(missing))

    # 关键回调走一遍
    try:
        app.update_lyric("align", "left")
        app.update_mixed("lines_prev", 0)
        app.update_mixed("lines_next", 1)
        app.update_mixed("align", "left")
        app.update_mixed("effect_lyric", "static")
        app.update_lyric("opacity", 0.8)
        app.update_lyric("line_spacing", 160)
        assert state.style_config["mixed"]["lines_next"] == 1
        assert state.style_config["mixed"]["align"] == "left"
        assert state.style_config["mixed"]["effect_lyric"] == "static"
        assert abs(state.style_config["lyric"]["opacity"] - 0.8) < 1e-9
        assert state.style_config["lyric"]["line_spacing"] == 160
    except Exception as e:
        fails.append(f"回调异常: {type(e).__name__}: {e}")

    # 日志区可写
    try:
        app.log("CTk 界面冒烟测试")
        root.update()
    except Exception as e:
        fails.append(f"log_text 写入失败: {e}")

    # 状态刷新可跑
    try:
        app.update_account_status()
        app.update_engine_badge("✅ 驱动: 冒烟", "#22C55E")
        root.update()
    except Exception as e:
        fails.append(f"状态刷新失败: {e}")

root.update()
root.destroy()

print("═══ CTk 界面冒烟 ═══")
if fails:
    for f in fails:
        print("  ❌", f)
    sys.exit(1)
print("  ✅ 界面构建成功，58 个契约控件齐全，回调与状态刷新均正常")
