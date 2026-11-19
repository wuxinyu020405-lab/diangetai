# -*- coding: utf-8 -*-
"""主播侧弹幕发送：手动发、热刷新发送器、设置即时生效、测试发送。

R-23 从 mainapp.py 搬出来的，逻辑一行没改。"""

import threading
import time

import bilibili_send
import state


class DanmakuMixin:
    """R-23：从 mainapp.MusicApp 拆出的方法块，靠多重继承合回同一个类。"""

    def gui_send_danmaku(self):
        """主播手动发一条 B站弹幕（复用点歌回执的同一个限频发送器）。"""
        try:
            text = (self.entry_send_dm.get() or "").strip()
        except Exception:
            text = ""
        if not text:
            self._set_send_result("⚠️ 内容为空", "#F59E0B")
            return
        # v1.2.6：每次发送前用最新 config 里的 Cookie 热刷新，登录后无需重启
        sender = self.reload_bili_sender()
        if sender is None:
            self._set_send_result("❌ 发弹幕不可用（未登录 B站 或缺 bili_jct）", "#EF4444")
            self.log("❌ 发弹幕失败：发送器未就绪（请先「重新登录 B站」）")
            return
        if not sender.ready():
            self._set_send_result("❌ 未登录 B站（Cookie 缺 bili_jct）——请先「重新登录 B站」", "#EF4444")
            self.log("❌ 发弹幕失败：Cookie 缺 bili_jct/SESSDATA，请在「弹幕」页点重新登录")
            return
        reason = sender.send(text)
        if reason:
            self._set_send_result("⚠️ 未发送：%s" % reason, "#F59E0B")
            self.log("⚠️ 弹幕未发送：%s" % reason)
            return
        self._set_send_result("✅ 已排队发送", "#22C55E")
        self.log("📣 手动发弹幕：%s" % text[:40])
        try:
            self.entry_send_dm.delete(0, "end")
        except Exception:
            pass

    def _set_send_result(self, msg, color):
        try:
            if hasattr(self, "lbl_send_dm_result"):
                self.lbl_send_dm_result.configure(text=msg, text_color=color)
        except Exception:
            pass

    def reload_bili_sender(self):
        """用 config 里最新的 Cookie/房间号热刷新发送器，登录后不必重启。"""
        try:
            import bilibili_send
            cfg = self.config
            kwargs = dict(
                room_id=cfg.get('room_id', ''),
                cookie_str=cfg.get('bili_cookie', '') or '',
                enabled=bool(cfg.get('danmaku_send_enabled', True)),
                sends_per_min=cfg.get('danmaku_sends_per_min', 3),
                min_gap_sec=cfg.get('danmaku_min_gap_sec', 3),
            )
            if getattr(self, "danmaku_sender", None) is None:
                self.danmaku_sender = bilibili_send.RateLimitedSender(
                    kwargs['room_id'], kwargs['cookie_str'], log=self.log,
                    enabled=kwargs['enabled'], sends_per_min=kwargs['sends_per_min'],
                    min_gap_sec=kwargs['min_gap_sec'])
            else:
                self.danmaku_sender.refresh(**kwargs)
            return self.danmaku_sender
        except Exception as e:
            self.log("⚠️ 刷新弹幕发送器失败: %s: %s" % (type(e).__name__, e))
            return getattr(self, "danmaku_sender", None)

    def update_danmaku_settings(self, *_a):
        """弹幕设置即时生效：开关 / 每分钟上限 / 最小间隔。"""
        cfg = self.config
        try:
            cfg["danmaku_send_enabled"] = bool(self.sw_dm_enabled.get())
        except Exception:
            pass
        try:
            v = int(float(str(self.entry_dm_per_min.get()).strip() or 3))
            cfg["danmaku_sends_per_min"] = max(1, v)
        except Exception:
            pass
        try:
            v = float(str(self.entry_dm_gap_sec.get()).strip() or 3)
            cfg["danmaku_min_gap_sec"] = max(0.0, v)
        except Exception:
            pass
        sender = getattr(self, "danmaku_sender", None)
        if sender is not None:
            sender.refresh(enabled=cfg.get("danmaku_send_enabled", True),
                           sends_per_min=cfg.get("danmaku_sends_per_min", 3),
                           min_gap_sec=cfg.get("danmaku_min_gap_sec", 3))
        self.schedule_save_style()

    def test_send_danmaku(self):
        """测试发送：真发一条到当前直播间，把 B站返回的原因显示出来。"""
        import threading
        self._set_send_result("⏳ 正在测试发送...", "#64748B")

        def _work():
            try:
                sender = self.reload_bili_sender()
                if sender is None:
                    self.root.after(0, lambda: self._set_send_result("❌ 发送器不可用", "#EF4444"))
                    return
                ok, msg = sender.send_now("点歌台测试弹幕")
                color = "#22C55E" if ok else "#EF4444"
                text = ("✅ 测试成功：" if ok else "❌ 测试失败：") + msg
                self.root.after(0, lambda: self._set_send_result(text, color))
            except Exception as e:
                self.log("⚠️ 测试发送异常: %s: %s" % (type(e).__name__, e))
                self.root.after(0, lambda: self._set_send_result("❌ 测试异常：%s" % e, "#EF4444"))

        threading.Thread(target=_work, daemon=True).start()
