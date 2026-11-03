# -*- coding: utf-8 -*-
"""歌词同步回归测试（v1.1·B1 + B1续）。入库版，长期防回归。
用法: ./.venv/Scripts/python.exe -X utf8 _test_lyric_regression.py

覆盖两个用户实机报告的场景：
  B1  点歌播完恢复 BGM（同一首歌）→ OBS 必须重新抓到歌词，不能整首空白。
      旧 bug：api 期间 system_media_worker 的 last_lyric_key 陈旧，回升 local 时
      判"没换歌"跳过取词，而 active_lrc_lines 已被播放器清空。
  B1续 api 模式按暂停 → 歌词必须冻结，不能继续往后滚。
      旧 bug：lyric_sync 用 player_is_busy() 做门槛，pause 时 busy=False 误落墙钟分支。

设计：B1 用 monkeypatch 伪造 SMTC（CI 的 Windows Server 无真实媒体 API，也能跑）；
B1续 用真 pygame + 自造静音 WAV（get_pos 冻结是 SDL 真实行为，不能伪造）。
"""
import asyncio, os, sys, time, struct, wave, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
import state, mainapp

HERE = os.path.dirname(os.path.abspath(__file__))
results = []
def ck(name, ok, d=""):
    results.append(ok); print(("OK  " if ok else "FAIL"), name, d)

# ───────────────────────── B1：恢复 BGM 重新取词 ─────────────────────────
class _FakeTimeline:
    class position:
        @staticmethod
        def total_seconds(): return 10.0
class _FakeSession:
    def get_playback_info(self):
        class P: playback_status = 4
        return P()
    def get_timeline_properties(self): return _FakeTimeline()
    async def try_get_media_properties_async(self):
        class M: title = "BGM神曲"; artist = "本地歌手"
        return M()
    async def try_toggle_play_pause_async(self): pass
class _FakeMgr:
    def get_sessions(self): return [_FakeSession()]
    def get_current_session(self): return _FakeSession()
class _FakeWmc:
    class GlobalSystemMediaTransportControlsSessionManager:
        @staticmethod
        async def request_async(): return _FakeMgr()

def _mk_media_app(fetch_calls):
    class A:
        def log(self, m): pass
        async def get_best_smtc_session(self, mgr): return mgr.get_current_session()
        async def fetch_lyrics_by_mid_or_keyword(self, song_mid=None, keyword=None):
            fetch_calls.append((song_mid, keyword))
            return [(0.0, "第一行"), (5.0, "第二行"), (10.0, "第三行")]
    return A()

async def test_bgm_resume():
    mainapp.wmc = _FakeWmc   # 伪造 SMTC
    fetch_calls = []
    app = _mk_media_app(fetch_calls)
    state.current_play_mode = "local"
    state.active_lrc_lines = []
    state.system_media_info = {"title": "暂无播放", "artist": ""}
    task = asyncio.create_task(mainapp.MusicApp.system_media_worker(app))
    try:
        await asyncio.sleep(3.5)
        ck("B1-阶段1 local 取词", len(fetch_calls) >= 1 and len(state.active_lrc_lines) == 3)
        n = len(fetch_calls)
        # 模拟播放器接管：切 api + 清歌词
        state.current_play_mode = "api"; state.active_lrc_lines = []
        await asyncio.sleep(3.5)
        ck("B1-阶段2 api 期 worker 不动", len(fetch_calls) == n)
        # 播完回 local，同一首 BGM
        state.current_play_mode = "local"
        await asyncio.sleep(3.5)
        ck("B1-阶段3 回升重新取词(核心)", len(fetch_calls) >= n + 1 and len(state.active_lrc_lines) == 3)
        n2 = len(fetch_calls)
        await asyncio.sleep(5.0)
        ck("B1-阶段4 同曲不重复抓", len(fetch_calls) == n2)
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

# ───────────────────── B1续：api 暂停时歌词冻结 ─────────────────────
def _make_wav():
    wav = os.path.join(HERE, "_probe_tone.wav")
    if os.path.exists(wav): return wav
    w = wave.open(wav, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
    fr = bytearray()
    for i in range(44100 * 40):
        fr += struct.pack("<h", int(1200 * math.sin(2 * math.pi * 220 * i / 44100)))
    w.writeframes(bytes(fr)); w.close()
    return wav

async def test_pause_freeze():
    import pygame
    wav = _make_wav()
    state.active_lrc_lines = [(float(i), "第%d行" % i) for i in range(30)]
    state.current_play_mode = "api"
    state.style_config["lyric"]["lines_prev"] = 2
    state.style_config["lyric"]["lines_next"] = 2
    class A:
        audio_backend = "pygame"
        def log(self, m): pass
        def player_is_busy(self): return bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())
        def player_get_elapsed(self):
            p = pygame.mixer.music.get_pos(); return p / 1000.0 if p >= 0 else 0.0
    app = A()
    idx = lambda: state.current_lyric_info.get("active_idx", -1)
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=2048)
    pygame.mixer.music.load(wav); pygame.mixer.music.set_volume(0.0); pygame.mixer.music.play()
    state.active_song_start_ts = time.time(); state.active_song_base_pos = 0.0
    task = asyncio.create_task(mainapp.MusicApp.lyric_sync_worker(app))
    try:
        await asyncio.sleep(2.5)
        i1 = idx(); ck("B1续-播放中歌词在走", i1 >= 1, "idx=%d" % i1)
        pygame.mixer.music.pause()
        await asyncio.sleep(2.5); i2 = idx()
        await asyncio.sleep(1.5); i3 = idx()
        ck("B1续-暂停歌词冻结(核心)", abs(i3 - i2) <= 1, "暂停中 %d→%d" % (i2, i3))
        pygame.mixer.music.unpause()
        await asyncio.sleep(2.5)
        ck("B1续-恢复后继续走", idx() > i3)
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        pygame.mixer.quit()

async def _all():
    await test_bgm_resume()
    await test_pause_freeze()

if __name__ == "__main__":
    asyncio.run(_all())
    bad = results.count(False)
    print("结论:", "✅ 歌词回归 %d/%d 全过" % (len(results), len(results)) if bad == 0 else "❌ 失败 %d 项" % bad)
    sys.exit(0 if bad == 0 else 1)
