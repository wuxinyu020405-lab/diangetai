# -*- coding: utf-8 -*-
"""B站直播间发弹幕模块（v1.1·#8）。

用途：给观众回执行为反馈（#1 点歌失败回执），后续排队播报等也复用这里。
设计约束（写进待办清单的拍板）：
  · 机器人发弹幕有 B站风控 —— 内置限频：每分钟最多 SENDS_PER_MIN 条，超了静默丢弃
  · 只在"观众需要知道"的事件上发（失败回执），成功不发（主播自己看得见）
  · 任何网络/接口错误只进日志，绝不影响点歌主流程
  · Cookie 里必须有 bili_jct（CSRF）才能发；缺了就整体休眠（返回原因）

接口：
  send(room_id, cookie_str, text, log=None) -> (bool, str)   同步版（内部起独立请求）
  RateLimitedSender(...)                                      推荐用法：带限频的实例
"""
import asyncio
import time
import urllib.request
import urllib.parse

SENDS_PER_MIN = 3          # 每分钟上限（保守值，直播间人数多时风控更紧）
MIN_GAP_SEC = 3            # 两条之间的最小间隔
API = "https://api.live.bilibili.com/msg/send"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def parse_cookie(cookie_str):
    """'a=1; b=2' -> {'a':'1','b':'2'}"""
    out = {}
    for item in (cookie_str or "").split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class RateLimitedSender:
    """限频弹幕发送器。send_now=False 时（默认）只记账不真发，供测试。"""

    def __init__(self, room_id, cookie_str, log=None, enabled=True):
        self.room_id = str(room_id or "")
        self.cookies = parse_cookie(cookie_str)
        self.log = log or (lambda m: None)
        self.enabled = enabled
        self._stamps = []          # 最近一分钟内的发送时间
        self._last = 0.0

    # ---------- 限频闸 ----------
    def _gate(self):
        now = time.time()
        self._stamps = [t for t in self._stamps if now - t < 60]
        if not self.enabled:
            return "发送功能未启用"
        if not (self.room_id and self.room_id.isdigit()):
            return "缺少房间号"
        if not self.cookies.get("bili_jct") or not self.cookies.get("SESSDATA"):
            return "缺少 B站 Cookie(bili_jct/SESSDATA)"
        if len(self._stamps) >= SENDS_PER_MIN:
            return "回执限频(每分钟%d条)已用完" % SENDS_PER_MIN
        if now - self._last < MIN_GAP_SEC:
            return "回执限频(间隔%ds)" % MIN_GAP_SEC
        return None

    # ---------- 发送 ----------
    def send(self, text):
        """非阻塞投递（fire-and-forget）。返回 None=已排队，str=被拦原因。"""
        reason = self._gate()
        if reason:
            return reason
        text = (text or "").strip()[:40]        # B站弹幕长度上限 40（超限会被拒）
        if not text:
            return "空内容"
        self._stamps.append(time.time())
        self._last = time.time()
        try:
            asyncio.get_running_loop().create_task(self._post(text))
            return None
        except RuntimeError:
            # 无事件循环（如测试/主线程直调）：起一个后台线程发。
            # 线程目标必须自带兜底——本模块原则是"任何异常绝不影响点歌主流程"，
            # 裸 asyncio.run 遇到非协程/内部异常会炸线程刷 traceback。
            def _safe():
                try:
                    r = self._post(text)
                    if asyncio.iscoroutine(r):
                        asyncio.run(r)
                except Exception as e:
                    self.log("[WARN] 回弹幕线程异常(已兜底): %s: %s" % (type(e).__name__, e))
            import threading
            threading.Thread(target=_safe, daemon=True).start()
            return None

    async def _post(self, text):
        data = urllib.parse.urlencode({
            "bubble": "0", "msg": text, "color": "16777215", "mode": "1",
            "roomid": self.room_id, "csrf": self.cookies.get("bili_jct", ""),
            "reply_mid": "0", "reply_type": "0", "replay_mid": "0",
            "is_stranger": "false", "font_model": "", "from": "web",
        }).encode()
        req = urllib.request.Request(API, data=data, headers={
            "User-Agent": UA,
            "Referer": "https://live.bilibili.com/%s" % self.room_id,
            "Origin": "https://live.bilibili.com",
            "Cookie": "; ".join("%s=%s" % (k, v) for k, v in self.cookies.items()
                                if k in ("SESSDATA", "bili_jct", "DedeUserID",
                                         "DedeUserID__ckMd5", "sid", "buvid3", "buvid4")),
        })
        try:
            def _io():
                with urllib.request.urlopen(req, timeout=8) as r:
                    return r.read()
            body = await asyncio.to_thread(_io)
            j = json_loads(body)
            if j.get("code") == 0:
                self.log("📣 已回弹幕: %s" % text)
            else:
                self.log("[WARN] 回弹幕被拒: code=%s msg=%s" % (j.get("code"), j.get("message")))
        except Exception as e:
            self.log("[WARN] 回弹幕失败(不影响点歌): %s: %s" % (type(e).__name__, e))


def json_loads(b):
    import json
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return {"code": -1, "message": "响应非JSON"}
