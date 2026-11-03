# -*- coding: utf-8 -*-
"""v1.1 回归：pygame 暂停语义 + 暂停状态机端到端。
本文件是 _test_pause.py 的入库版（静音、自造 WAV、跑完自清理）。
覆盖 SDL 的两个反直觉事实（2026-11 实测）：
  ① pause 期间 get_pos() 冻结 → 歌词进度天然同步，无需补偿
  ② pause 期间 get_busy() 返回 False → 播放循环若只信 busy 会误判"播完"
     （提前恢复 BGM / 误删缓存文件），状态机必须自带 paused 保护。
用法: ./.venv\\Scripts\\python.exe -X utf8 _test_pause_regression.py
"""
import asyncio, os, sys, struct, wave, math, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
import pygame
import state, mainapp, settings

CACHE = settings.CACHE_DIR
MID = "ZZTEST"
tier_file = os.path.join(CACHE, MID + "_default.wav")
WAVSRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_tone.wav")

def make_wav():
    if os.path.exists(WAVSRC): return
    w = wave.open(WAVSRC, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
    fr = bytearray()
    for i in range(44100 * 40):
        fr += struct.pack("<h", int(1200 * math.sin(2 * math.pi * 220 * i / 44100)))
    w.writeframes(bytes(fr)); w.close()

logs = []
class StubRoot:
    def after(self, _ms, fn=None, *a):
        if fn: fn(*a)
class FakeApp:
    root = StubRoot()
    audio_backend = "pygame"
    def log(self, m): logs.append(m)
    def update_pause_button(self): pass
    def get_volume(self): return 0.0
    def apply_volume(self, v=None):
        try: pygame.mixer.music.set_volume(0.0)
        except Exception: pass
        return 0.0
    async def player_load_and_play(self, fp):
        def _s():
            pygame.mixer.music.load(fp); pygame.mixer.music.set_volume(0.0); pygame.mixer.music.play()
            return True
        await asyncio.to_thread(_s)
        await asyncio.sleep(0.3)
        return pygame.mixer.music.get_busy()
    def player_is_busy(self):
        return bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())
    def player_stop(self):
        try: pygame.mixer.music.stop()
        except Exception: pass
    def player_get_elapsed(self):
        p = pygame.mixer.music.get_pos()
        return p / 1000.0 if p >= 0 else 0.0
    async def fetch_lyrics_by_mid_or_keyword(self, song_mid=None, keyword=None):
        return [(0.0, "测试行一"), (1.0, "测试行二")]
    async def control_local_music(self, pause=True):
        logs.append(("BGM", pause))
    request_pause = mainapp.MusicApp.request_pause
    toggle_pause = mainapp.MusicApp.toggle_pause

results = []
def ck(name, ok, d=""):
    results.append(ok); print(("OK  " if ok else "FAIL"), name, d)

async def main():
    app = FakeApp()
    state.style_config.setdefault("global", {})["volume"] = 0.0
    state.pause_event = asyncio.Event()
    state.skip_event = asyncio.Event()
    state.playlist = [{"name": "测试歌", "display_name": "测试歌 歌手", "mid": MID, "requester": "小白"}]
    state.current_song = None
    state.current_play_mode = "api"

    task = asyncio.create_task(mainapp.MusicApp.music_player_worker(app))
    for _ in range(20):
        await asyncio.sleep(0.2)
        if state.current_song and app.player_is_busy(): break
    ck("起播", bool(state.current_song) and app.player_is_busy())
    if not state.current_song:
        task.cancel(); return

    app.request_pause(True); await asyncio.sleep(0.6)
    ck("暂停 paused=True", state.paused is True)
    p1 = pygame.mixer.music.get_pos() / 1000.0
    await asyncio.sleep(1.2)
    p2 = pygame.mixer.music.get_pos() / 1000.0
    ck("① get_pos 冻结(歌词无需补偿)", abs(p2 - p1) < 0.35, "漂移%.2fs" % (p2 - p1))
    ck("②保护生效: 暂停中 current_song 保持", state.current_song is not None)
    ck("②保护生效: 缓存文件未被误删", os.path.exists(tier_file))

    app.request_pause(False); await asyncio.sleep(0.6)
    ck("恢复 paused=False", state.paused is False)
    p3 = pygame.mixer.music.get_pos() / 1000.0
    await asyncio.sleep(1.0)
    p4 = pygame.mixer.music.get_pos() / 1000.0
    ck("恢复后 get_pos 继续走", (p4 - p3) > 0.6, "增量%.2fs" % (p4 - p3))

    app.request_pause(True); await asyncio.sleep(0.5)
    state.skip_event.set(); await asyncio.sleep(0.8)
    ck("暂停中切歌: 解除暂停", state.paused is False)
    ck("暂停中切歌: 停止播放", not app.player_is_busy())
    ck("暂停中切歌: 文件未误删", os.path.exists(tier_file))
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass

def run():
    make_wav()
    shutil.copy(WAVSRC, tier_file)
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=2048)
    try:
        asyncio.run(main())
    finally:
        pygame.mixer.quit()
        if os.path.exists(tier_file): os.remove(tier_file)
    bad = results.count(False)
    print("结论:", "✅ %d/%d 全过" % (len(results), len(results)) if bad == 0 else "❌ 失败 %d 项" % bad)
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(run())
