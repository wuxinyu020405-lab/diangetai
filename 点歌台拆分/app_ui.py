# -*- coding: utf-8 -*-
"""界面回调层：设置项写入、取色/选字体、队列管理页渲染、配置落盘。

R-23 从 mainapp.py 搬出来的，逻辑一行没改。"""

import os
import time

import tkinter as tk          # 只为了 tk.END 这个常量（输入框 delete(0, tk.END)）
from qtshim import colorchooser, filedialog

import locallib
import secretstore
import settings
import state
import qtapp


# v1.2.8 修复用：这些配置键由"登录流程 / 自动探测 / 用户手填"独立管理，
# 不在设置界面的保存范围内。保存设置时必须先以磁盘值为准合并，
# 否则内存里的旧值会把它们抹掉（历史 bug：登录写入的 Cookie 被覆盖成空）。
# R-23：随 save_style_config 一起从 mainapp 搬过来。
_EXTERN_KEYS = ("bili_cookie", "room_id", "douyin_room_id",
                "qqmusic_path", "local_songs_dir", "local_match_threshold")


class UiMixin:
    """R-23：从 mainapp.MusicApp 拆出的方法块，靠多重继承合回同一个类。"""

    def _qm_post(self, fn):
        """把改动投递到 asyncio loop 线程；loop 还没起来时直接拒绝并提示。"""
        loop = getattr(self, "loop", None)
        if loop is None:
            self.log("ℹ️ 播放引擎还没就绪，队列操作稍后再试")
            return False
        try:
            loop.call_soon_threadsafe(fn)
            return True
        except Exception as e:
            self.log(f"❌ 队列操作投递失败: {e}")
            return False

    def qm_remove_pending(self, idx):
        req = dict(state.pending_requests[idx]) if 0 <= idx < len(state.pending_requests) else None
        if req is None:
            return
        def _do():
            if 0 <= idx < len(state.pending_requests):
                r = state.pending_requests.pop(idx)
                self.log(f"🗑️ 已从排队中移除: 《{r.get('song_name','')}》-{r.get('uname','')}")
        self.root.after(0, lambda: (self._qm_post(_do), self.refresh_queue_mgmt()))

    def qm_remove_ready(self, idx):
        def _do():
            if 0 <= idx < len(state.playlist):
                r = state.playlist.pop(idx)
                self.log(f"🗑️ 已移出待播队列: 《{r.get('display_name','')}》-{r.get('requester','')}（本地音频保留）")
        def _ui():
            if self._qm_post(_do):
                self.refresh_queue_mgmt()
        self.root.after(0, _ui)

    def qm_move_top(self, idx):
        def _do():
            if 0 < idx < len(state.playlist):
                r = state.playlist.pop(idx)
                state.playlist.insert(0, r)
                self.log(f"⬆️ 已置顶: 《{r.get('display_name','')}》（下一首就播它）")
        def _ui():
            if self._qm_post(_do):
                self.refresh_queue_mgmt()
        self.root.after(0, _ui)

    @staticmethod
    def _fmt_wait(ts):
        s = max(0, int(time.time() - (ts or time.time())))
        return f"{s//60}分{s%60:02d}秒" if s >= 60 else f"{s}秒"

    def refresh_queue_mgmt(self):
        """重绘队列两段（R-15：渲染交给 qtapp.render_queue，这里只更新汇总文字）。"""
        if not hasattr(self, "lbl_qm_summary"):
            return
        try:
            proc = state.processing_request
            pend = list(state.pending_requests)
            ready = list(state.playlist)
            cur = state.current_song
        except Exception:
            return
        try:
            qtapp.set_label(
                self.lbl_qm_summary,
                text="正在播放: %s    处理中 %d 首 · 待播 %d 首"
                     % ((cur.get("display_name") if cur else "—"),
                        len(pend) + (1 if proc else 0), len(ready)))
        except Exception:
            pass
        try:
            qtapp.render_queue(self)
        except Exception:
            pass

    def _qm_tick(self):
        """2.5s 自动刷新（页面没建则跳过；异常绝不打断 tick 链）。"""
        try:
            if hasattr(self, "qm_pending_box") and self.qm_pending_box.isVisible():
                # 只在窗口可见时重绘，缩到托盘时省资源
                if self.root.state() != "withdrawn":
                    self.refresh_queue_mgmt()
        except Exception:
            pass
        try:
            self.root.after(2500, self._qm_tick)
        except Exception:
            pass

    def get_local_songs_dir(self):
        """config.json 的 local_songs_dir 可覆盖默认 my_songs/；目录不存在就建好。"""
        folder = (self.config.get("local_songs_dir") or settings.LOCAL_SONGS_DIR)
        if not os.path.isabs(folder):
            folder = os.path.join(settings.BASE_DIR, folder)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            self.log(f"⚠️ 本地曲库目录创建失败: {e}")
        return folder

    def open_local_songs_folder(self):
        """GUI『打开本地曲库文件夹』：建目录并用资源管理器打开，附一句指引。"""
        folder = self.get_local_songs_dir()
        self.log(f"📂 本地曲库：{folder}")
        self.log(locallib.folder_hint(folder))
        try:
            if os.name == "nt":
                os.startfile(folder)      # 资源管理器，零弹窗、零子进程黑窗
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            self.log(f"⚠️ 打开文件夹失败（可手动去这个路径）: {e}")
        try:
            n = len(locallib.list_songs(folder))
            self.log(f"📀 当前本地曲库共 {n} 首（每次点歌现扫，放进去即生效，无需重启）")
        except Exception:
            pass

    def _load_local_lrc(self, audio_path):
        """本地歌的同名 .lrc；没有就返回 []（上层显示'纯音乐'）。"""
        try:
            import lyrics
            lrc = os.path.splitext(audio_path)[0] + ".lrc"
            if os.path.exists(lrc):
                with open(lrc, "r", encoding="utf-8-sig", errors="replace") as f:
                    return lyrics.parse_lrc(f.read())
        except Exception as e:
            self.log(f"⚠️ 本地歌词读取失败: {e}")
        return []

    def save_style_config(self):
        self.config["style_config"] = state.style_config
        try:
            # ① 先读磁盘，把"外部管理的键"合并回来（磁盘有值且内存是空/旧值时以磁盘为准）
            try:
                disk = secretstore.read_json(settings.CONFIG_FILE, default={}) or {}
            except Exception:
                disk = {}
            if isinstance(disk, dict):
                for k in _EXTERN_KEYS:
                    if k in disk:
                        mem = self.config.get(k)
                        dv = disk.get(k)
                        # 磁盘有非空值 → 用磁盘；否则保留内存值（避免把用户新填的清掉）
                        if dv not in (None, "", 0) or mem in (None, "", 0):
                            self.config[k] = dv
            # ② 再整体写回
            secretstore.write_json(settings.CONFIG_FILE, self.config)
        except Exception as e:
            print("保存配置失败:", e)
            try:
                self.log(f"⚠️ 保存配置失败: {e}")
            except Exception:
                pass

    def schedule_save_style(self, event=None):
        if hasattr(self, "_save_timer") and self._save_timer:
            self.root.after_cancel(self._save_timer)
        self._save_timer = self.root.after(500, self.save_style_config)

    def update_account_status(self):
        bili_status = "❌ 未配置 (缺少Cookie或房间号)"
        bili_color = "red"
        if self.config.get("bili_cookie") and self.config.get("room_id"):
            bili_status = f"✅ 已配置 (房间号: {self.config['room_id']})"
            bili_color = "green"
        qtapp.set_label(self.lbl_bili_status, text=bili_status, color=bili_color)

        qq_status = "❌ 未登录"
        qq_color = "red"
        try:
            # v1.2.1·需求6：经 secretstore 透明读（密文/明文兼容）
            data = secretstore.read_json(settings.CREDENTIAL_FILE, default=None)
            if data and data.get("musicid") and data.get("musickey"):
                qq_status = f"✅ 已登录 (账号UID: {data['musicid']})"
                qq_color = "green"
        except Exception:
            pass
        qtapp.set_label(self.lbl_qq_status, text=qq_status, color=qq_color)

    def update_mixed(self, key, val): state.style_config["mixed"][key] = val; self.schedule_save_style()

    def update_lyric(self, key, val): state.style_config["lyric"][key] = val; self.schedule_save_style()

    def update_playing(self, key, val): state.style_config["playing"][key] = val; self.schedule_save_style()

    def update_queue(self, key, val): state.style_config["queue"][key] = val; self.schedule_save_style()

    def _spin_int_or(self, widget, default):
        """Spinbox 取整：非数字/负数回落到 default，避免打字中途把配置写坏。"""
        try:
            v = int(str(widget.get()).strip())
            return v if v >= 0 else default
        except Exception:
            return default

    def update_lyric_align(self, event):
        val = self.combo_lyric_align.get()
        m = {"居中对齐": "center", "左对齐": "left", "右对齐": "right"}
        state.style_config["lyric"]["align"] = m.get(val, "center")
        self.schedule_save_style()

    def update_queue_align(self, event):
        """v1.1·N3：点歌列表挂件对齐。"""
        val = self.combo_queue_align.get()
        m = {"居中对齐": "center", "左对齐": "left", "右对齐": "right"}
        state.style_config["queue"]["align"] = m.get(val, "left")
        self.schedule_save_style()

    def pick_mixed(self, key, lbl_name):
        c = colorchooser.askcolor(title="选择颜色")[1]
        if c:
            state.style_config["mixed"][key] = c
            qtapp.set_label(getattr(self, lbl_name), text=c, color=c, bg=c)
            self.schedule_save_style()

    def pick_lyric(self, key):
        c = colorchooser.askcolor(title="选择歌词颜色")[1]
        if c: state.style_config["lyric"][key] = c; qtapp.set_label(self.lbl_lyric_color, text=c, color=c, bg=c); self.schedule_save_style()

    def pick_playing(self, key):
        c = colorchooser.askcolor(title="选择播放颜色")[1]
        if c: state.style_config["playing"][key] = c; qtapp.set_label(self.lbl_playing_color, text=c, color=c, bg=c); self.schedule_save_style()

    def pick_queue(self, key):
        c = colorchooser.askcolor(title="选择列表颜色")[1]
        if c: state.style_config["queue"][key] = c; qtapp.set_label(self.lbl_queue_color, text=c, color=c, bg=c); self.schedule_save_style()

    def update_effect(self, event):
        val = self.combo_effect.get()
        m = {"高清平滑滚动 (锐利)": "apple_hd", "高清平滑滚动": "apple_hd", "苹果景深滚动 (柔光)": "apple_blur", "苹果景深滚动": "apple_blur", "无滚动 (经典静态)": "static", "无滚动 (静态)": "static"}
        state.style_config["lyric"]["effect"] = m.get(val, "apple_hd")
        self.schedule_save_style()

    def update_audio_quality(self, event=None, value=None):
        """切换首选音质。

        v1.2.8 修复：原来只读 self.var_audio_quality，而 CTkComboBox 的 command
        回调**不会**自动更新那个 StringVar —— 结果界面上选什么都好，写进配置的
        永远是初始化时的旧值（选「默认品质」实际仍按 flac 下载）。
        现在优先用回调传进来的值，找不到才回退到 var。
        """
        val = value if value else self.var_audio_quality.get()
        # 同步 var，保持界面与配置一致（其它地方还会读它回填）
        try:
            if val and self.var_audio_quality.get() != val:
                self.var_audio_quality.set(val)
        except Exception:
            pass
        q_key = settings.UI_QUALITY_MAP.get(val)
        new_q = settings.normalize_quality_key(q_key)
        state.style_config["audio_quality"] = new_q
        self.schedule_save_style()
        self.log(f"🎵 点歌首选音质已切换为: 【{val}】→ 实际档位 {new_q} (无对应音源时自动平滑降级)")
        return new_q

    def browse_qq_path(self):
        path = filedialog.askopenfilename(title="选择 QQMusic.exe", filetypes=[("Executable", "*.exe")])
        if path:
            path = path.replace("/", "\\")
            self.entry_qq_path.delete(0, tk.END)
            self.entry_qq_path.insert(0, path)
            self.config["qqmusic_path"] = path
            self.save_style_config()
            self.log(f"✅ QQ音乐路径已更新并保存: {path}")

    def update_bgm_target(self, event=None, value=None):
        """v1.2.10：点歌时暂停谁的 BGM。CTkComboBox 不会自动写 var，必须用参数。"""
        _REV = {"自动识别": "auto", "只暂停 QQ音乐": "qqmusic", "不暂停": "off"}
        val = value if value else (self.combo_bgm_target.get() if hasattr(self, "combo_bgm_target") else "")
        key = _REV.get((val or "").strip())
        if not key:
            return
        self.config["bgm_target"] = key
        self.save_style_config()
        self.log("✅ 点歌暂停对象已设为：%s" % val)

    def copy_to_clipboard(self, text):
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.log(f"📋 已复制到剪贴板: {text}")

    def update_cache_settings(self, event=None):
        try:
            files = int(self.entry_max_files.get().strip())
            if files > 0: state.style_config["max_cache_files"] = files
        except ValueError as e:
            print(f"[WARN] 值解析失败: {e}")

        try:
            size = int(self.entry_max_size.get().strip())
            if size > 0: state.style_config["max_cache_size_mb"] = size
        except ValueError as e:
            print(f"[WARN] 值解析失败: {e}")

        self.schedule_save_style()
