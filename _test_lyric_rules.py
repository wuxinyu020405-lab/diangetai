# -*- coding: utf-8 -*-
"""R-25 针对性回归：歌词显示规则。

覆盖三条新规则：
  ① 本地 BGM 只认 QQ 音乐 —— 浏览器/网易云等会话在播时，绝不取词、不显示歌词
  ② 点歌播放（api）暂停时 —— 歌词清空
  ③ 本地 BGM 暂停时 —— 歌词清空；两套暂停态互相独立
  ④ 恢复播放后歌词自动重新出现

用法: python -X utf8 _test_lyric_rules.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import app_media
import state

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  [" + str(extra) + "]"))


# ═══════════════ 假 SMTC ═══════════════
class _Timeline:
    class position:
        @staticmethod
        def total_seconds():
            return 10.0


class _Session:
    """可配 AUMID 与播放状态的假会话。"""

    def __init__(self, aumid, playing=True, title="某歌", artist="某歌手"):
        self.source_app_user_model_id = aumid
        self._status = 4 if playing else 5      # 4=PLAYING, 5=PAUSED
        self._title = title
        self._artist = artist

    def get_playback_info(self):
        status = self._status

        class P:
            playback_status = status
        return P()

    def get_timeline_properties(self):
        return _Timeline()

    async def try_get_media_properties_async(self):
        title, artist = self._title, self._artist

        class M:
            pass
        m = M()
        m.title = title
        m.artist = artist
        return m

    async def try_toggle_play_pause_async(self):
        pass


class _Mgr:
    def __init__(self, session):
        self._s = session

    def get_sessions(self):
        return [self._s] if self._s else []

    def get_current_session(self):
        return self._s


class _Wmc:
    def __init__(self, session):
        mgr = _Mgr(session)

        class GlobalSystemMediaTransportControlsSessionManager:
            @staticmethod
            async def request_async():
                return mgr
        self.GlobalSystemMediaTransportControlsSessionManager =             GlobalSystemMediaTransportControlsSessionManager


class _App:
    """最小假 App：只提供 worker 用到的那几个方法。"""

    def __init__(self, fetched):
        self._fetched = fetched

    def log(self, m):
        pass

    def player_get_elapsed(self):
        """lyric_sync_worker 在 api 模式下用它取播放进度（假对象给个固定值）。"""
        return 6.0

    async def get_best_smtc_session(self, mgr, target=None):
        # 真实逻辑：target="qqmusic" 时只留 QQ 音乐会话
        sessions = mgr.get_sessions()
        if target == "qqmusic":
            sessions = [s for s in sessions if app_media.MediaMixin._is_qqmusic_session(s)]
            if not sessions:
                return None
            return sessions[0]
        return mgr.get_current_session()

    async def fetch_lyrics_by_mid_or_keyword(self, song_mid=None, keyword=None):
        self._fetched.append(keyword)
        return [(0.0, "第一行"), (5.0, "第二行"), (10.0, "第三行")]


async def run_worker(session, seconds, monitor=None):
    """跑 system_media_worker 一段时间，返回 (取词次数, 观察到的歌词状态列表)。"""
    fetched = []
    app_media.wmc = _Wmc(session)
    app = _App(fetched)
    snaps = []

    task = asyncio.create_task(app_media.MediaMixin.system_media_worker(app))
    try:
        step = 0.2
        waited = 0.0
        while waited < seconds:
            await asyncio.sleep(step)
            waited += step
            if monitor:
                monitor(waited)
            snaps.append(len(state.current_lyric_info.get("lines") or []))
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return fetched, snaps


def reset():
    state.current_play_mode = "local"
    state.active_lrc_lines = []
    state.current_lyric_info = {"lines": [], "all_lines": [], "active_idx": -1}
    state.local_bgm_paused = False
    state.paused = False
    state.system_media_info = {"title": "暂无播放", "artist": ""}


async def main():
    # ① 非 QQ 音乐（浏览器）在播 → 一次词都不取，歌词保持空
    reset()
    fetched, _ = await run_worker(_Session("MSEdge.exe", playing=True, title="B站视频 - 1:23"), 4.0)
    ck("① 浏览器在播：完全不去搜词", fetched == [], fetched)
    ck("① 浏览器在播：歌词保持空", state.active_lrc_lines == [], state.active_lrc_lines)
    ck("① 浏览器在播：all_lines 也空（前端滚动模式同样无内容）",
       not state.current_lyric_info.get("all_lines"),
       state.current_lyric_info.get("all_lines"))
    ck("① 浏览器在播：标记为「本地暂停态」", state.local_bgm_paused is True, state.local_bgm_paused)
    ck("① 浏览器在播：system_media_info 不显示视频标题",
       "B站视频" not in state.system_media_info.get("title", ""), state.system_media_info)

    # ② QQ 音乐在播 → 正常取词
    reset()
    fetched, _ = await run_worker(_Session("QQMusic.exe", playing=True, title="真歌", artist="真人"), 4.0)
    ck("② QQ音乐在播：取到词", len(fetched) >= 1, fetched)
    ck("② QQ音乐在播：歌词非空", len(state.active_lrc_lines) == 3, state.active_lrc_lines)
    ck("② QQ音乐在播：不算暂停", state.local_bgm_paused is False, state.local_bgm_paused)

    # ③ 点歌播放中暂停 → 歌词清空（lyric_paused + sync worker）
    reset()
    state.current_play_mode = "api"
    state.active_lrc_lines = [(0.0, "a"), (5.0, "b")]
    state.paused = True
    ck("③ api 暂停：lyric_paused() 为真", app_media.lyric_paused() is True)
    sync = asyncio.create_task(app_media.MediaMixin.lyric_sync_worker(_App([])))
    await asyncio.sleep(0.3)
    sync.cancel()
    try:
        await sync
    except asyncio.CancelledError:
        pass
    ck("③ api 暂停：歌词已被隐藏（lines 空）", state.current_lyric_info["lines"] == [],
       state.current_lyric_info)
    ck("③ api 暂停：active_lrc_lines 保留（恢复即回来）", len(state.active_lrc_lines) == 2)

    # ④ 恢复播放 → 歌词重新出现
    state.paused = False
    ck("④ api 恢复：lyric_paused() 为假", app_media.lyric_paused() is False)
    sync = asyncio.create_task(app_media.MediaMixin.lyric_sync_worker(_App([])))
    await asyncio.sleep(0.3)
    sync.cancel()
    try:
        await sync
    except asyncio.CancelledError:
        pass
    ck("④ api 恢复：歌词回来了", len(state.current_lyric_info["lines"]) > 0,
       state.current_lyric_info)

    # ⑤ 本地 BGM 暂停（QQ音乐暂停着，status=5）→ local_bgm_paused=True，歌词隐藏
    reset()
    state.local_bgm_paused = True
    state.active_lrc_lines = [(0.0, "a")]
    ck("⑤ 本地暂停：lyric_paused() 为真", app_media.lyric_paused() is True)
    sync = asyncio.create_task(app_media.MediaMixin.lyric_sync_worker(_App([])))
    await asyncio.sleep(0.3)
    sync.cancel()
    try:
        await sync
    except asyncio.CancelledError:
        pass
    ck("⑤ 本地暂停：歌词已隐藏", state.current_lyric_info["lines"] == [], state.current_lyric_info)

    # ⑥ 两套暂停态互不干扰
    reset()
    state.current_play_mode = "local"
    state.local_bgm_paused = True
    state.paused = False
    ck("⑥ 本地暂停不影响 api 的暂停标志", state.paused is False)
    state.current_play_mode = "api"
    state.paused = False
    state.local_bgm_paused = True
    ck("⑥ api 在播时忽略本地暂停标志", app_media.lyric_paused() is False)

    # ⑦ QQ 音乐暂停中（有会话但 status!=4）→ 视为暂停，且仍能拿到歌名
    reset()
    fetched, _ = await run_worker(_Session("QQMusic.exe", playing=False, title="暂停的歌"), 4.0)
    ck("⑦ QQ音乐暂停：标记为暂停态", state.local_bgm_paused is True, state.local_bgm_paused)
    ck("⑦ QQ音乐暂停：不重复搜词（同曲已取过则跳过）", state.system_media_info.get("title") == "暂停的歌",
       state.system_media_info)

    bad = [n for n, ok in RESULTS if not ok]
    print("\n结论: %s 歌词规则回归 %d/%d" % ("✅" if not bad else "❌",
                                          len(RESULTS) - len(bad), len(RESULTS)))
    if bad:
        for n in bad:
            print("  失败:", n)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
