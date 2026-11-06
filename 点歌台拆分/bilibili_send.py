# -*- coding: utf-8 -*-
"""B站直播间发弹幕模块（v1.2.6 修复版）。

v1.2.6 改动（针对"弹幕发不出去"）：
  1. 补齐接口必需参数 fontsize / rnd / csrf_token / room_type / content-type，
     v1.2.4 只传 bubble/msg/color/mode/roomid/csrf，B站会判参数不全直接拒（-400）。
  2. 限频可配：构造参数 sends_per_min / min_gap_sec，
     由 config.json 的 danmaku_sends_per_min / danmaku_min_gap_sec 注入。
  3. refresh()：登录后热更新 Cookie / 房间号，不必重启程序。
  4. send_now()：同步发送并返回中文原因，UI 可直接显示结果。
  5. 错误码中文化（-101 未登录 / -111 csrf / -352 风控 / 1003212 频率限制）。
"""
import asyncio
import json
import time
import urllib.parse
import urllib.request

DEFAULT_SENDS_PER_MIN = 3      # 默认每分钟上限（保守值）
DEFAULT_MIN_GAP_SEC = 3        # 默认两条之间最小间隔
API = "https://api.live.bilibili.com/msg/send"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 兼容旧引用
SENDS_PER_MIN = DEFAULT_SENDS_PER_MIN
MIN_GAP_SEC = DEFAULT_MIN_GAP_SEC

ERR_TEXT = {
    -101: "账号未登录（请先「重新登录 B站」）",
    -111: "CSRF 校验失败（Cookie 缺 bili_jct，请重新登录）",
    -400: "参数错误（检查直播间号）",
    -403: "无权限（可能被禁言，或不是你的直播间）",
    -404: "直播间不存在（房间号不对）",
    -352: "B站风控拦截（发送过快，稍后再试）",
    -500: "B站服务端异常",
    10030: "弹幕含敏感词，被拦截",
    10031: "发送太快，被限制（降低频率后重试）",
    1003212: "被 B站临时限制发送（通常 1~10 分钟）",
}


def explain(code, message=""):
    """错误码 -> 人话。"""
    try:
        code = int(code)
    except Exception:
        return str(message or "未知错误")
    if code in ERR_TEXT:
        return ERR_TEXT[code]
    if code == 0:
        return "成功"
    return "B站返回 code=%s %s" % (code, message or "")


def parse_cookie(cookie_str):
    """'a=1; b=2' -> {'a':'1','b':'2'}"""
    out = {}
    for item in (cookie_str or "").split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip()
    return out


COOKIE_KEYS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid",
               "buvid3", "buvid4", "buvid3_4_act", "b_nut", "CURRENT_FNVAL", "LIVE_BUVID")


class RateLimitedSender:
    """限频弹幕发送器（开关/上限/间隔均可运行时改）。"""

    def __init__(self, room_id, cookie_str, log=None, enabled=True,
                 sends_per_min=DEFAULT_SENDS_PER_MIN, min_gap_sec=DEFAULT_MIN_GAP_SEC):
        self.room_id = str(room_id or "")
        self.cookies = parse_cookie(cookie_str)
        self.log = log or (lambda m: None)
        self.enabled = bool(enabled)
        self.sends_per_min = max(1, int(sends_per_min or DEFAULT_SENDS_PER_MIN))
        try:
            self.min_gap_sec = max(0.0, float(min_gap_sec))
        except Exception:
            self.min_gap_sec = float(DEFAULT_MIN_GAP_SEC)
        self._stamps = []          # 最近一分钟内的发送时间
        self._last = 0.0

    # ---------- 热更新 ----------
    def refresh(self, room_id=None, cookie_str=None, enabled=None,
                sends_per_min=None, min_gap_sec=None):
        """登录后/改设置后热更新，不必重启程序。返回 self。"""
        if room_id is not None:
            self.room_id = str(room_id or "")
        if cookie_str is not None:
            self.cookies = parse_cookie(cookie_str)
        if enabled is not None:
            self.enabled = bool(enabled)
        if sends_per_min is not None:
            try:
                self.sends_per_min = max(1, int(float(sends_per_min)))
            except Exception:
                pass
        if min_gap_sec is not None:
            try:
                self.min_gap_sec = max(0.0, float(min_gap_sec))
            except Exception:
                pass
        return self

    def ready(self):
        """Cookie 与房间号是否齐备。"""
        return bool(self.room_id and self.room_id.isdigit()
                    and self.cookies.get("bili_jct") and self.cookies.get("SESSDATA"))

    # ---------- 限频闸 ----------
    def _gate(self):
        now = time.time()
        self._stamps = [t for t in self._stamps if now - t < 60]
        if not self.enabled:
            return "发送功能未启用"
        if not (self.room_id and self.room_id.isdigit()):
            return "缺少直播间号"
        if not self.cookies.get("bili_jct") or not self.cookies.get("SESSDATA"):
            return "缺少 B站 Cookie（bili_jct/SESSDATA），请先「重新登录 B站」"
        if len(self._stamps) >= self.sends_per_min:
            return "限频：每分钟 %d 条已用完" % self.sends_per_min
        if self.min_gap_sec and (now - self._last) < self.min_gap_sec:
            return "限频：两条需间隔 %ss" % int(self.min_gap_sec)
        return None

    # ---------- 发送（非阻塞） ----------
    def send(self, text):
        """非阻塞投递。返回 None=已排队，str=被拦原因。"""
        reason = self._gate()
        if reason:
            return reason
        text = (text or "").strip()[:40]
        if not text:
            return "空内容"
        self._stamps.append(time.time())
        self._last = time.time()
        try:
            asyncio.get_running_loop().create_task(self._post(text))
            return None
        except RuntimeError:
            import threading
            def _safe():
                try:
                    asyncio.run(self._post(text))
                except Exception as e:
                    self.log("[WARN] 回弹幕线程异常(已兜底): %s: %s" % (type(e).__name__, e))
            threading.Thread(target=_safe, daemon=True).start()
            return None

    # ---------- 发送（同步，给 UI 即时反馈） ----------
    def send_now(self, text, timeout=10):
        """同步真发一条，返回 (ok: bool, 中文说明)。"""
        reason = self._gate()
        if reason:
            return False, reason
        text = (text or "").strip()[:40]
        if not text:
            return False, "空内容"
        self._stamps.append(time.time())
        self._last = time.time()
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._post(text, timeout=timeout))
            finally:
                loop.close()
        except Exception as e:
            return False, "网络错误：%s" % e

    async def _post(self, text, timeout=8):
        jct = self.cookies.get("bili_jct", "")
        data = urllib.parse.urlencode({
            "bubble": "0",
            "msg": text,
            "color": "16777215",
            "fontsize": "25",
            "mode": "1",
            "rnd": str(int(time.time())),
            "roomid": self.room_id,
            "room_type": "0",
            "csrf": jct,
            "csrf_token": jct,
            "reply_mid": "0",
            "reply_type": "0",
            "replay_mid": "0",
            "is_stranger": "false",
            "font_model": "",
            "from": "web",
        }).encode()
        req = urllib.request.Request(API, data=data, headers={
            "User-Agent": UA,
            "Referer": "https://live.bilibili.com/%s" % self.room_id,
            "Origin": "https://live.bilibili.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "; ".join("%s=%s" % (k, v) for k, v in self.cookies.items()
                                if k in COOKIE_KEYS),
        })
        try:
            def _io():
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            body = await asyncio.to_thread(_io)
            j = json_loads(body)
            code = j.get("code")
            if code == 0:
                self.log("📣 已发弹幕: %s" % text)
                return True, "已发送"
            msg = explain(code, j.get("message"))
            self.log("[WARN] 发弹幕被拒: code=%s msg=%s" % (code, j.get("message")))
            return False, msg
        except Exception as e:
            self.log("[WARN] 发弹幕失败(不影响点歌): %s: %s" % (type(e).__name__, e))
            return False, "网络错误：%s" % e


def json_loads(b):
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return {"code": -1, "message": "响应非JSON"}
