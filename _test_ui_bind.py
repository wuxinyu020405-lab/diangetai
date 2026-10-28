# -*- coding: utf-8 -*-
"""验证 CTkEntry 修复：改输入框 → 配置真的变 → 保存到磁盘。"""
import json
import io
import os
import sys

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

root = ctk.CTk(); root.withdraw()
app = mainapp.MusicApp(root, {"room_id": "", "bili_cookie": "", "qqmusic_path": ""})

ok = 0
bad = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        bad.append(name)
        print(f"  ❌ {name} {detail}")


print("═══ A. 输入框改行数 → 配置联动 ═══")
before = state.style_config["mixed"].get("lines_prev")
app.spin_mix_prev.delete(0, "end")
app.spin_mix_prev.insert(0, "3")
root.update()
after = state.style_config["mixed"].get("lines_prev")
check(f"lines_prev {before}→{after}（应=3）", after == 3, f"实际{after}")

app.spin_mix_next.delete(0, "end")
app.spin_mix_next.insert(0, "4")
root.update()
check("lines_next 应=4", state.style_config["mixed"].get("lines_next") == 4,
      f"实际{state.style_config['mixed'].get('lines_next')}")

print("═══ B. 列表选项联动 ═══")
app.spin_mix_items.delete(0, "end"); app.spin_mix_items.insert(0, "8"); root.update()
check("max_items=8", state.style_config["mixed"].get("max_items") == 8)
app.spin_mix_chars.delete(0, "end"); app.spin_mix_chars.insert(0, "20"); root.update()
check("max_chars=20", state.style_config["mixed"].get("max_chars") == 20)
app.entry_mix_sep.delete(0, "end"); app.entry_mix_sep.insert(0, "·"); root.update()
check("分隔符=·", state.style_config["mixed"].get("requester_sep") == "·")

print("═══ C. 纯歌词输入框联动 ═══")
app.entry_pure_music.delete(0, "end"); app.entry_pure_music.insert(0, "听歌中"); root.update()
check("pure_text=听歌中", state.style_config["lyric"].get("pure_text") == "听歌中")

print("═══ D. 保存到磁盘 ═══")
app.save_style_config()
saved = json.load(io.open("点歌台拆分/config.json", encoding="utf-8"))["style_config"]
check("磁盘 mixed.lines_prev=3", saved["mixed"].get("lines_prev") == 3)
check("磁盘 mixed.lines_next=4", saved["mixed"].get("lines_next") == 4)

print("═══ E. mixed 与 lyric 已彻底解耦 ═══")
app.update_lyric("lines_prev", 0); app.update_lyric("lines_next", 1); root.update()
check("改 lyric 后 mixed 不变", state.style_config["mixed"].get("lines_prev") == 3
      and state.style_config["mixed"].get("lines_next") == 4)

root.destroy()
print(f"\n通过 {ok} | 失败 {len(bad)}" + ("" if not bad else " → " + ", ".join(bad)))
sys.exit(1 if bad else 0)
