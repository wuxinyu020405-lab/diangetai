# -*- coding: utf-8 -*-
"""系统媒体识别（SMTC）+ 歌词获取与同步。

R-23 从 mainapp.py 搬出来的，逻辑一行没改。"""

import asyncio
import time

import winsdk.windows.media.control as wmc
from qqmusic_api import Client

import lyrics
import musiclib
import smtc
import state


# v1.2.10：QQ 音乐在 SMTC 里的 SourceAppUserModelId 实测就是 "QQMusic.exe"
# （本机 2026-11-19 实测：AUMID=[QQMusic.exe] / 浏览器是 MSEdge）
# R-23：随 _is_qqmusic_session 一起搬过来，mainapp 里保留同名类属性当引用。
QQMUSIC_AUMID_HINTS = ("qqmusic", "tencent")


def lyric_paused():
    """R-25：当前是否处于"暂停态"（暂停时歌词一律不显示）。

    两套暂停态各看各的：
      · 点歌播放（api）    → state.paused（pygame pause 时置 True）
      · 本地 BGM（local）  → state.local_bgm_paused（SMTC playback_status != 4）
    恢复播放后自动重新出现，不需要额外动作。

    写成模块级函数而不是方法：它只读 state，跟实例无关，
    回归测试里的假对象也能直接调用。
    """
    try:
        if state.current_play_mode == "api":
            return bool(state.paused)
        return bool(state.local_bgm_paused)
    except Exception:
        return False


class MediaMixin:
    """R-23：从 mainapp.MusicApp 拆出的方法块，靠多重继承合回同一个类。"""

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
                if lyric_paused():
                    # R-25：暂停时直接不出歌词。不清 active_lrc_lines，恢复后立刻接上。
                    state.current_lyric_info = {"lines": [], "all_lines": [], "active_idx": -1}
                elif state.active_lrc_lines:
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

    @staticmethod
    def _is_qqmusic_session(s):
        """会话是否来自 QQ 音乐（兼容 AUMID 带包名的长串写法）。"""
        try:
            aumid = (s.source_app_user_model_id or "").lower()
        except Exception:
            return False
        # R-23：原来写 MusicApp._QQMUSIC_AUMID_HINTS，搬出来后改成本模块常量，值完全一样。
        return any(h in aumid for h in QQMUSIC_AUMID_HINTS)

    async def get_best_smtc_session(self, sessions_mgr, target=None):
        """挑一个媒体会话。

        target: None/"auto" 谁在放歌就用谁（老行为，歌词读取也用这个）；
                "qqmusic"   只认 QQ 音乐（点歌暂停 BGM 用）；
                "off"       不接管（返回 None）。
        """
        if target == "off":
            return None
        if not sessions_mgr: return None
        try:
            all_sessions = sessions_mgr.get_sessions()
            if target == "qqmusic":
                all_sessions = [s for s in all_sessions if self._is_qqmusic_session(s)]
                if not all_sessions:
                    return None
            fallback_session = None
            for s in all_sessions:
                try:
                    pinfo = s.get_playback_info()
                    if pinfo and pinfo.playback_status == 4: return s
                    if fallback_session is None: fallback_session = s
                except Exception: continue
            if target == "qqmusic":
                return fallback_session        # QQ 音乐暂停着也算目标，下一首还要恢复它
            return sessions_mgr.get_current_session() or fallback_session
        except Exception:
            try: return sessions_mgr.get_current_session()
            except Exception: return None

    async def control_local_music(self, pause=True):
        global is_local_playing, bgm_paused_by_bot
        # v1.2.10：按用户选项决定暂停谁——auto 自动识别 / qqmusic 只暂停 QQ音乐 / off 不接管
        target = (self.config.get("bgm_target") or "auto").strip().lower()
        if target == "off":
            self.log("⏸️ 已设置不暂停 BGM，跳过")
            return
        try:
            sessions_mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async(); session = await self.get_best_smtc_session(sessions_mgr, target)
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
                    playing = False
                    session_ok = False        # 有没有拿到 QQ 音乐的 SMTC 会话
                    session = None
                    if sessions_mgr:
                        # ★R-25：只认 QQ 音乐。之前是"谁在播就用谁"，浏览器视频/网易云
                        # 也会被当成播放源拿标题去 QQ 音乐搜词；视频标题每秒在变
                        # （"xxx - 1:23"），于是每秒一次搜索 + 歌词整段换掉 → 疯狂抖动。
                        # 现在非 QQ 音乐的会话一律不取词、不显示歌词。
                        session = await self.get_best_smtc_session(sessions_mgr, "qqmusic")
                        session_ok = session is not None
                        if session:
                            info = await session.try_get_media_properties_async()
                            if info and info.title: title = (info.title or "").strip(); artist = (info.artist or "").strip()
                            try:
                                pinfo = session.get_playback_info()
                                playing = bool(pinfo and pinfo.playback_status == 4)
                            except Exception as e:
                                print(f"[WARN] 异常已捕获: {e}")
                            try:
                                timeline = session.get_timeline_properties()
                                if timeline and timeline.position:
                                    pos_sec = timeline.position.total_seconds()
                                    if pos_sec > 0: smtc_pos = pos_sec
                            except Exception as e:
                                print(f"[WARN] 异常已捕获: {e}")

                    # 窗口标题兜底只在"没拿到 SMTC 会话"时用（QQ 音乐最小化等）。
                    # SMTC 有会话但暂停着 → 保持歌名，不再去猜别的窗口。
                    if not title and not session_ok:
                        win_title, win_artist = smtc.get_qqmusic_window_song()
                        if win_title: title, artist = win_title, (win_artist or "")
                    # R-25：本地 BGM 暂停态 = 不是 QQ 音乐正在播（含暂停/停止/没会话）
                    state.local_bgm_paused = not playing
                    if title:
                        state.system_media_info = {"title": title, "artist": artist}; track_key = f"{title}|{artist}"
                        if track_key != last_logged_key: last_logged_key = track_key; self.log(f"🎵 正在播放(本地): {title}" + (f" - {artist}" if artist else ""))
                        if track_key != last_lyric_key:
                            last_lyric_key = track_key; state.active_song_start_ts = time.time()
                            state.active_song_base_pos = smtc_pos if (smtc_pos is not None) else 0.0; last_smtc_pos = smtc_pos if (smtc_pos is not None) else -1.0
                            # ★R-25：先搜词、搜到了再一次性替换。旧逻辑先清空再搜，
                            # 搜的 1~3 秒里歌词是空的 → 挂件上一秒有下一秒没，也是抖动来源。
                            search_kw = f"{title} {artist}".strip(); lines = await self.fetch_lyrics_by_mid_or_keyword(keyword=search_kw)
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
