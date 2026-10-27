# -*- coding: utf-8 -*-
"""行为级烟测：跨模块的 赋值→读取 必须可见（AST 等价性检查不到的东西）。"""
import asyncio
import importlib
import sys

sys.path.insert(0, "点歌台拆分")

import state
import settings
import lyrics
import musiclib
import overlay

print("=== 1. 模块级状态可见性（模拟 MusicApp.__init__ 的 style_config 合并）===")
old = {"lyric": {"size": 99}}
state.style_config = settings.merge_config(old, state.style_config)
print("   合并后 lyric.size =", state.style_config["lyric"]["size"], "（应为 99）")
assert state.style_config["lyric"]["size"] == 99

print("\n=== 2. 跨 worker 的状态接力（playlist / current_song / skip_event）===")
state.playlist.append({"mid": "X", "display_name": "歌A", "requester": "u1"})
print("   playlist 长度 =", len(state.playlist))
first = state.playlist.pop(0)
state.current_song = first                    # 模拟 music_player_worker 的赋值
print("   current_song.display_name =", state.current_song["display_name"])
assert state.current_song["display_name"] == "歌A"
state.current_song = None
print("   置回 None 后读取 =", state.current_song)

print("\n=== 3. skip_event 跨模块 set/clear（danmaku 写 → player 读）===")
state.skip_event = asyncio.Event()
state.skip_event.set()
print("   is_set =", state.skip_event.is_set())
state.skip_event.clear()
print("   clear 后 =", state.skip_event.is_set())

print("\n=== 4. 歌词链路：musiclib 探测枚举 + lyrics 解析 ===")
ft_hi = musiclib.resolve_song_file_type(None, ("HI_RES", "HIRES", "RS01", "FLAC_HIRES"))
ft_flac = musiclib.resolve_song_file_type(None, ("FLAC", "F000", "SQ"))
print("   hires 枚举 =", ft_hi, "  flac 枚举 =", getattr(ft_flac, "name", ft_flac))
parsed = lyrics.parse_lrc("[00:10.50]第一句\n[00:20.00]第二句")
print("   parse_lrc ->", parsed)
st = lyrics.get_current_lyric_state(parsed, 25)
print("   25s 时 active_idx =", st["active_idx"], "all_lines =", st["all_lines"])

print("\n=== 5. overlay 服务真实起停（读 state）===")
from aiohttp import web


async def t():
    state.system_media_info = {"title": "测试歌", "artist": "测试者"}
    state.current_lyric_info = {"lines": [{"text": "x", "active": True}],
                               "all_lines": ["x"], "active_idx": 0}
    app = web.Application()
    app.router.add_get("/", overlay.handle_index)
    app.router.add_get("/api/data", overlay.handle_api)
    r = web.AppRunner(app)
    await r.setup()
    site = web.TCPSite(r, "127.0.0.1", 8098)
    await site.start()
    import aiohttp
    async with aiohttp.ClientSession() as cs:
        async with cs.get("http://127.0.0.1:8098/api/data") as resp:
            d = await resp.json()
            print("   /api/data system_playing =", d["system_playing"])
            print("   /api/data lyric =", d["lyric"]["lines"])
            assert d["system_playing"] == "测试歌 - 测试者"
        async with cs.get("http://127.0.0.1:8098/") as resp:
            html = await resp.text()
            print("   / ->", resp.status, "含 updateData:", "updateData" in html)
    await r.cleanup()

asyncio.run(t())

print("\n=== 6. mainapp 导入（不实例化 GUI）===")
import mainapp
import danmaku
import browserlogin
import smtc
print("   mainapp.MusicApp =", mainapp.MusicApp.__name__)
print("   danmaku.BiliHandler =", danmaku.BiliHandler.__mro__[1].__module__)
print("   smtc.get_qqmusic_window_song =", callable(smtc.get_qqmusic_window_song))
print("   browserlogin.start_driver =", callable(browserlogin.start_driver))

print("\n全部行为级检查通过 ✅")
