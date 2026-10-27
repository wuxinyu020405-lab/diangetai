# -*- coding: utf-8 -*-
"""真实 tkinter 冒烟：真正 setup_ui（新控件全走一遍）后自动关闭。
不跑 asyncio 循环、不连直播间——只验证控件构建与初值不报错。"""
import os
import sys

sys.path.insert(0, "点歌台拆分")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import tkinter as tk
import state
import mainapp

# 屏蔽真副作用：不起 aiohttp 服务（会抢 8080）、不连直播间、不起音频线程。
# 本冒烟只验 GUI 控件构建与回调。
mainapp.MusicApp.start_async_loop = lambda self: None

fails = []

root = tk.Tk()
root.withdraw()   # 无桌面可见窗口；控件仍完整构建

# 用最小 config，避免读用户真实配置
config = {"room_id": "", "bili_cookie": "", "qqmusic_path": ""}
try:
    app = mainapp.MusicApp(root, config)
except Exception as e:
    import traceback
    traceback.print_exc()
    fails.append(f"MusicApp 构建失败: {e}")

if not fails:
    # 断言新控件都建出来了
    for attr in ("scale_volume", "lbl_volume_pct", "scale_lyric_op",
                 "var_mix_pfx", "combo_mix_align", "spin_mix_items",
                 "var_mix_sidx", "var_mix_sreq", "entry_mix_sep", "spin_mix_chars",
                 "spin_q_items", "var_q_sidx", "var_q_sreq", "entry_q_sep"):
        if not hasattr(app, attr):
            fails.append(f"缺控件属性: {attr}")
    # 音量初值一致性
    try:
        got = app.scale_volume.get()
        want = int(round(app.get_volume() * 100))
        if got != want:
            fails.append(f"音量滑杆初值 {got} != {want}")
    except Exception as e:
        fails.append(f"音量读取异常: {e}")
    # 透明度滑杆初值
    try:
        o = app.scale_lyric_op.get()
        if o != int(round(state.style_config['lyric']['opacity'] * 100)):
            fails.append(f"透明度滑杆 {o} 与配置不符")
    except Exception as e:
        fails.append(f"透明度读取异常: {e}")
    # 模拟一次拖音量：tk.Scale 的 set() 不触发 command（那是用户手势专属），
    # 真实拖动= command(str值) → apply_volume(slider_val=e)，这里直接调同一入口。
    try:
        state.style_config["global"]["volume"] = 1.0
        app.scale_volume.set(42)
        v = app.apply_volume(slider_val=app.scale_volume.get())
        if abs(v - 0.42) > 1e-6:
            fails.append(f"音量返回 {v} != 0.42")
        if abs(state.style_config["global"]["volume"] - 0.42) > 1e-6:
            fails.append(f"配置={state.style_config['global']['volume']} 应为0.42")
        if app.lbl_volume_pct.cget("text") != "42%":
            fails.append(f"百分比标签={app.lbl_volume_pct.cget('text')!r}")
    except Exception as e:
        fails.append(f"滑杆联动异常: {e}")
    # 透明度写入
    try:
        app.update_lyric("opacity", 0.6)
        if abs(state.style_config['lyric']['opacity'] - 0.6) > 1e-9:
            fails.append("opacity 写入 style_config 失败")
    except Exception as e:
        fails.append(f"update_lyric(opacity) 异常: {e}")

root.update()   # 跑一轮事件循环让回调落定
root.destroy()

print("═══ GUI 冒烟结果 ═══")
if fails:
    for f in fails:
        print("  ❌", f)
    sys.exit(1)
print("  ✅ MusicApp 完整构建，全部新控件就位，初值一致，交互回调无异常")
