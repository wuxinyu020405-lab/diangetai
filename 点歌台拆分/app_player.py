# -*- coding: utf-8 -*-
"""播放层：pygame 音量、起播确认、播放/暂停/切歌意图、播放器 worker。

R-23 从 mainapp.py 搬出来的，逻辑一行没改。"""

import asyncio
import os
import time

import pygame

import musiclib
import qtapp
import settings
import state


class PlayerMixin:
    """R-23：从 mainapp.MusicApp 拆出的方法块，靠多重继承合回同一个类。"""

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

    def get_volume(self):
        """第6步·高价值2：音量 0~1，脏值回落 1.0（=现状行为）。"""
        try:
            v = float(state.style_config.get("global", {}).get("volume", 1.0))
        except Exception:
            return 1.0
        return min(1.0, max(0.0, v))

    def apply_volume(self, slider_val=None):
        # slider_val 非空 = 滑杆拖动：用它换算并持久化；
        # 为空 = 起播兜底：读已存配置，只施加不写盘。
        # （tk.Scale 的 command 回调参数才是当前滑杆值，不能去读尚未更新的 style_config）
        if slider_val is not None:
            try:
                v = min(1.0, max(0.0, int(slider_val) / 100.0))
            except Exception:
                v = self.get_volume()
            state.style_config.setdefault("global", {})["volume"] = v
            self.schedule_save_style()
            try:
                qtapp.set_label(self.lbl_volume_pct, text=f"{int(round(v * 100))}%")
            except Exception:
                pass
        else:
            v = self.get_volume()
        try:
            if self.audio_backend == "pygame" and pygame.mixer.get_init():
                pygame.mixer.music.set_volume(v)
        except Exception as e:
            print(f"[WARN] 设置音量失败: {e}")
        return v

    async def player_load_and_play(self, file_path, wait_busy_secs=3.0):
        """起播并确认真的在播。

        v1.2.9 修复：原来固定只等 0.4 秒就查一次 get_busy()，本地录音
        （尤其大 wav/flac）加载解码慢时会被误判成"文件损坏"，
        进而触发自动删文件。现在改成轮询等待，最多等 wait_busy_secs。
        """
        def _pg_start():
            try:
                pygame.mixer.music.load(file_path)
                # 第6步：load 会把音量重置回满格，必须起播前重新施加设置值
                try:
                    v = self.get_volume()
                    pygame.mixer.music.set_volume(v)
                except Exception as e:
                    print(f"[WARN] 设置音量失败: {e}")
                pygame.mixer.music.play()
                return True
            except Exception as e:
                print("pygame 播放异常:", e)
                return False
        started = await asyncio.to_thread(_pg_start)
        if not started:
            return False
        # 轮询确认：只要在等待窗口内任意一次 busy=True 就算成功
        deadline = time.time() + max(0.4, float(wait_busy_secs))
        while time.time() < deadline:
            try:
                if pygame.mixer.music.get_busy():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.15)
        return False

    async def music_player_worker(self):
        global current_song, current_play_mode, system_media_info, active_lrc_lines, active_song_start_ts, active_song_base_pos
        while True:
            if state.current_song is None and len(state.playlist) > 0:
                state.current_song = state.playlist.pop(0)
                requester = state.current_song.get("requester", "神秘观众")
                # v1.2.9 双保险：新歌开播前先消化掉残留的切歌意图。
                # 入口（弹幕/按钮/API）已经拦住空闲切歌，这里再兜一层：
                # 万一还有历史残留，也不能让用户刚点的歌一开口就被切走。
                if state.skip_event is not None and state.skip_event.is_set():
                    state.skip_event.clear()
                    self.log("ℹ️ 已清除残留的切歌意图，本首正常播放")
                self.log(f"▶️ 准备播放: {state.current_song['display_name']}-{requester}")
                song_mid = state.current_song.get("mid")

                preferred_q = settings.normalize_quality_key(state.style_config.get("audio_quality", "flac"))

                # v1.2.8：本地曲库条目自带 file_path，直接用，不再按 mid 查缓存。
                # 普通 QQ 音乐条目没有该字段，回退到原有的缓存检索逻辑，行为不变。
                file_path = state.current_song.get("file_path")
                if not file_path:
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
                    # v1.2.8：本地曲库条目没有 mid，不能按歌名去 QQ 搜歌词（会抓到别人的）。
                    # 有同名 .lrc 就读它，否则显示"纯音乐"。普通条目走原逻辑不变。
                    if state.current_song.get("file_path"):
                        state.active_lrc_lines = self._load_local_lrc(state.current_song["file_path"])
                    else:
                        state.active_lrc_lines = await self.fetch_lyrics_by_mid_or_keyword(song_mid=song_mid, keyword=state.current_song['display_name'])

                    if not state.active_lrc_lines:
                        state.active_lrc_lines = [(0.0, state.style_config["lyric"].get("pure_text", "纯音乐, 请欣赏.."))]

                    try:
                        started = await self.player_load_and_play(file_path)
                        state.active_song_start_ts = time.time()
                        state.active_song_base_pos = 0.0

                        # v1.1·N1：load_and_play 内部起播后确认 busy；若这期间用户已按暂停，
                        # busy=False 属正常而非"文件损坏"——必须排除暂停态，否则会误删缓存文件。
                        if (not started or not self.player_is_busy()) and not state.pause_event.is_set():
                            # v1.2.9：本地曲库是用户自己录的资料，**永远不自动删除**。
                            # 起播失败最多只是"这首没放出来"，绝不能把源文件删掉。
                            is_local_lib = (state.current_song or {}).get("source") == "local" \
                                or bool((state.current_song or {}).get("file_path"))
                            if is_local_lib:
                                self.log(f"⚠️ 本地文件没能正常起播（可能是加载慢/格式问题），已跳过；"
                                         f"文件保留未删: {real_name}")
                            else:
                                self.log(f"⚠️ 播放瞬间结束，可能是文件损坏或解码异常，自动清理并跳过: {real_name}")
                                try:
                                    if os.path.exists(file_path): os.remove(file_path)
                                except Exception as e:
                                    print(f"[WARN] 异常已捕获: {e}")

                            state.current_song = None; state.active_lrc_lines = []
                            continue

                        # v1.1·N1 暂停状态机（实测 SDL：pause 期间 get_pos 冻结、get_busy=False）
                        # 规则：暂停只停当前歌播放；下载/收队列不受影响；切歌优先并自动解除暂停。
                        state.paused = False
                        busy_false_streak = 0      # v1.2.9：连续 False 计数
                        _dbg_said = False
                        while True:
                            if state.pause_event.is_set():
                                if not state.paused:
                                    try: pygame.mixer.music.pause()
                                    except Exception as e: print(f"[WARN] 暂停失败: {e}")
                                    state.paused = True
                                    self.log("⏸️ 已暂停播放（点歌与下载照常排队；发【继续】或【切歌】恢复）")
                                    self.update_pause_button()
                                # 暂停中 busy=False，若不加这层保护会被当"播完"→提前恢复 BGM（实测坑）
                                if state.skip_event.is_set():
                                    state.skip_event.clear()
                                    try: pygame.mixer.music.unpause()
                                    except Exception: pass
                                    self.player_stop()
                                    state.paused = False
                                    self.update_pause_button()
                                    break
                                await asyncio.sleep(0.25)
                                continue
                            if state.paused:   # 暂停态收到解除意图
                                try: pygame.mixer.music.unpause()
                                except Exception as e: print(f"[WARN] 恢复播放失败: {e}")
                                state.paused = False
                                self.log("▶️ 已恢复播放")
                                self.update_pause_button()
                            if state.skip_event.is_set():
                                self.player_stop(); state.skip_event.clear(); break

                            # v1.2.9 修复「点歌后自动切歌」：原来单次 get_busy()==False 就当播完。
                            # 现在要求**连续 20 次（约 5 秒）都 False** 才认播完。
                            # 直播时 SMTC 暂停/恢复主播 BGM 会引起音频设备切换，
                            # 实测会让 get_busy 瞬时变 False，5 秒容忍足以挡住这种抖动。
                            if not self.player_is_busy():
                                busy_false_streak += 1
                                if not _dbg_said:
                                    _dbg_said = True
                                    try:
                                        pos = pygame.mixer.music.get_pos()
                                        init_ok = bool(pygame.mixer.get_init())
                                    except Exception:
                                        pos, init_ok = "?", False
                                    self.log(f"🔍 [诊断] get_busy 首次为 False（pos={pos}ms, "
                                             f"mixer_init={init_ok}, backend={self.audio_backend}）")
                                if busy_false_streak >= 20:
                                    self.log(f"🔍 [诊断] 连续 {busy_false_streak} 次 False（约5秒），判定本首播完")
                                    break
                                # 中途恢复过就清掉标记，下次再 False 可再报一次
                            else:
                                if busy_false_streak:
                                    self.log(f"🔍 [诊断] 播放恢复（曾连续 {busy_false_streak} 次 False，已忽略）")
                                    _dbg_said = False
                                busy_false_streak = 0
                            await asyncio.sleep(0.25)
                    except Exception as e:
                        self.log(f"❌ 播放失败: {type(e).__name__}: {e}")
                        # v1.2.9：本地曲库文件是用户资料，出任何异常都只跳过、不删文件
                        if not ((state.current_song or {}).get("source") == "local"
                                or (state.current_song or {}).get("file_path")):
                            try:
                                if os.path.exists(file_path): os.remove(file_path)
                            except Exception as e2:
                                print(f"[WARN] 异常已捕获: {e2}")
                        else:
                            self.log(f"ℹ️ 本地文件保留未删: {real_name}")


                state.current_song = None; state.active_lrc_lines = []

                if len(state.playlist) == 0 and state.current_play_mode == "api":
                    await asyncio.sleep(0.5)
                    if len(state.playlist) == 0:
                        state.system_media_info = {"title": "暂无播放", "artist": ""}
                        await self.control_local_music(pause=False)
                        state.current_play_mode = "local"
            await asyncio.sleep(0.5)
