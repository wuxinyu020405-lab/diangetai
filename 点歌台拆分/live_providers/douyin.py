# -*- coding: utf-8 -*-
"""live_providers.douyin：抖音直播弹幕 provider（匿名，免登录）。

链路（2026-11-04 spike 全链路实测通过，见 抖音接入Spike结论.md）：
  ① GET live.douyin.com/ 拿 ttwid cookie
  ② enter 接口（带全套浏览器指纹参数）→ 真实 room_id
  ③ 13 字段 stub → MD5 → node sign_runner.js → X-Bogus(signature)
  ④ 裸 socket+SSL IP 直连手写 WS 握手（绕开系统代理对抖音域名的透明劫持）
  ⑤ 收帧 → gzip → 手写 protobuf 解码 → DanmuMsg 队列

参数配方来自 SoraYjy/DanmuFree（协议细节以其 DOUYIN_PLAN.md 探针实测为准）。
法律：sign.js（webmssdk 反混淆产物，版权归字节）不在仓库，用户按文档自备；
本模块只依赖同目录 sign_runner.js 调用壳。
"""
import asyncio
import base64
import gzip
import hashlib
import http.cookiejar
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import state

from . import DanmuMsg

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
WS_HOST = "webcast3-ws-web-lf.douyin.com"      # 必须带 -ws-web-（老域名已 NXDOMAIN）
SIGN_STUB_TIMEOUT = 45                          # node 冷启动+jsdom+Defender 首扫实测可 >20s
HB_INTERVAL = 9.0
PING_INTERVAL = 14.0

# 签名 13 字段顺序（DanmuFree ParamOrder，严格不可变）
_PARAM_ORDER = ["live_id", "aid", "version_code", "webcast_sdk_version",
                "room_id", "sub_room_id", "sub_channel_id", "did_rule",
                "user_unique_id", "device_platform", "device_type", "ac", "identity"]


# ---------------- protobuf 手写解析（varint，零第三方） ----------------
def _rvarint(b, i):
    n = shift = 0
    while True:
        x = b[i]; i += 1
        n |= (x & 0x7F) << shift
        if not (x & 0x80):
            return n, i
        shift += 7

def _parse(b):
    out, i = {}, 0
    while i < len(b):
        try:
            tag, i = _rvarint(b, i)
        except IndexError:
            break
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _rvarint(b, i)
        elif wt == 2:
            ln, i = _rvarint(b, i)
            v = b[i:i + ln]; i += ln
        elif wt == 5:
            v = b[i:i + 4]; i += 4
        elif wt == 1:
            v = b[i:i + 8]; i += 8
        else:
            break
        out.setdefault(fn, []).append(v)
    return out

def _g(b, n):
    v = b.get(n)
    return v[0] if v else None

def _s(b, n):
    v = _g(b, n)
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")

def _wvarint(n):
    out = bytearray()
    while True:
        x = n & 0x7F; n >>= 7
        if n:
            out.append(x | 0x80)
        else:
            out.append(x)
            return bytes(out)

def _wv(fn, v):
    return _wvarint((fn << 3) | 0) + _wvarint(v)

def _wb(fn, d):
    return _wvarint((fn << 3) | 2) + _wvarint(len(d)) + d


# ---------------- 网络小工具 ----------------
def _no_proxy_opener(cj):
    """显式禁代理：本机透明代理(如梯子客户端)会劫持抖音域名返回 502。"""
    o = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.ProxyHandler({}))
    o.addheaders = [("User-Agent", UA), ("Referer", "https://live.douyin.com/")]
    return o


class DouyinProvider:
    """asyncio 任务形态：await provider.run(queue) —— DanmuMsg 持续入队。
    断线指数退避自动重连（每次重连重新签名）。"""

    def __init__(self, web_rid, log=None, sign_dir=None):
        self.web_rid = str(web_rid or "").strip()
        self.log = log or (lambda m: None)
        if sign_dir is None:
            # 候选顺序：exe 同级（打包版，spec 把壳放这里）→ _MEIPASS → 源码工作区根
            cands = []
            if getattr(sys, "frozen", False):
                cands.append(os.path.join(os.path.dirname(sys.executable), "douyin_sign"))
            mp = getattr(sys, "_MEIPASS", "")
            if mp:
                cands.append(os.path.join(mp, "douyin_sign"))
            cands.append(os.path.join(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))), "douyin_sign"))
            sign_dir = next((c for c in cands if c and os.path.isdir(c)), cands[-1])
        self.sign_dir = sign_dir
        self.queue = None
        self._stopped = False

    # ---------- ① ttwid + room_id ----------
    def _resolve_room(self):
        cj = http.cookiejar.CookieJar()
        o = _no_proxy_opener(cj)
        o.open("https://live.douyin.com/", timeout=15)          # 只为 ttwid
        ttwid = next((c.value for c in cj if c.name == "ttwid"), "")
        # 输入是 15~25 位长号 → 已是真实 room_id（feed/接口来源），跳过 enter 解析
        if re.match(r"^\d{15,25}$", self.web_rid):
            return ttwid, self.web_rid, 2, "(直接 room_id)"
        import json
        enter = ("https://live.douyin.com/webcast/room/web/enter/?aid=6383&app_name=douyin_web"
                 "&live_id=1&device_platform=web&language=zh-CN&web_rid=%s&cookie_enabled=true"
                 "&screen_width=1920&screen_height=1080&browser_language=zh-CN"
                 "&browser_platform=Win32&browser_name=Chrome&browser_version=126.0.0.0"
                 "&enter_from=web_live&is_need_double_stream=false" % self.web_rid)
        d = json.loads(o.open(enter, timeout=15).read().decode("utf-8", "replace"))
        rooms = (d.get("data") or {}).get("data") or []
        room = rooms[0] if rooms else {}
        room_id = room.get("id_str", "")
        status = room.get("status")
        if not room_id:
            raise RuntimeError("抖音房间解析失败：web_rid=%s 无数据（检查房间号/是否抖音直播）" % self.web_rid)
        return ttwid, room_id, status, (room.get("title") or "")[:24]

    # ---------- ③ 签名 ----------
    def _sign(self, stub_str):
        md5 = hashlib.md5(stub_str.encode()).hexdigest()
        runner = os.path.join(self.sign_dir, "sign_runner.js")
        if not os.path.exists(runner):
            raise RuntimeError("缺少 douyin_sign/sign_runner.js（抖音签名组件未安装）")
        node = shutil_which_node()
        if not node:
            raise RuntimeError("未找到 node（抖音签名需要 Node.js，见使用说明）")
        r = subprocess.run([node, runner, md5], capture_output=True, text=True,
                           cwd=self.sign_dir, timeout=SIGN_STUB_TIMEOUT)
        sig = (r.stdout or "").strip()
        if not sig:
            raise RuntimeError("签名失败: %s" % (r.stderr or "")[:120])
        return sig

    # ---------- ④ WS 握手（IP 直连绕代理） ----------
    def _build_url(self, room_id, uid, sig):
        ie_raw = ("internal_src:dim|wss_push_room_id:%s|wss_push_did:%s"
                  "|first_req_ms:0|fetch_time:0|seq:1|wss_info:0-0-0-0|wrds_v:0"
                  % (room_id, uid))
        query = ("app_name=douyin_web&version_code=180800&webcast_sdk_version=1.3.0"
                 "&update_version_code=1.3.0&compress=gzip&live_id=1&aid=6383&did_rule=3"
                 "&device_platform=web&identity=audience&room_id=%s&user_unique_id=%s"
                 "&cursor=d-1_u-1&host=https://live.douyin.com&im_path=/webcast/im/fetch/"
                 "&need_persist_msg_count=15&support_wrds=1&internal_ext=%s"
                 % (room_id, uid, urllib.parse.quote(ie_raw, safe="")))
        return query, "/webcast/im/push/v2/?aid=6383&%s&signature=%s" % (query, urllib.parse.quote(sig))

    @staticmethod
    def _stub_from_query(query):
        mp = {}
        for kv in query.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                mp[k] = urllib.parse.unquote(v)
        return ",".join("%s=%s" % (k, mp.get(k, "")) for k in _PARAM_ORDER)

    def _connect(self, room_id, uid, ttwid):
        query, path = self._build_url(room_id, uid, "")
        sig = self._sign(self._stub_from_query(query))
        path = "/webcast/im/push/v2/?aid=6383&%s&signature=%s" % (query, urllib.parse.quote(sig))
        ip = socket.gethostbyname(WS_HOST)
        s = socket.create_connection((ip, 443), timeout=15)
        ss = ssl.create_default_context().wrap_socket(s, server_hostname=WS_HOST)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("\r\n".join([
            "GET %s HTTP/1.1" % path, "Host: %s" % WS_HOST,
            "Upgrade: websocket", "Connection: Upgrade",
            "Sec-WebSocket-Key: %s" % key, "Sec-WebSocket-Version: 13",
            "Origin: https://live.douyin.com", "User-Agent: %s" % UA,
            "Cookie: ttwid=%s" % ttwid, "", "",
        ])).encode()
        ss.sendall(req)
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = ss.recv(4096)
            if not c:
                raise ConnectionError("握手无响应")
            buf += c
        head = buf.split(b"\r\n\r\n")[0].decode("utf-8", "replace")
        first = head.splitlines()[0] if head else ""
        rest = buf[buf.find(b"\r\n\r\n") + 4:]
        if "101" not in first:
            hm = [l for l in head.splitlines() if l.startswith("Handshake-")]
            raise ConnectionError("握手失败: %s %s" % (first, " ".join(hm)[:120]))
        return ss, rest

    # ---------- ⑤ 收帧循环 ----------
    def check_deps(self):
        """抖音功能依赖自检：node + sign_runner.js + sign.js。
        返回 (ok, 缺失说明)。缺则调用方应友好停用抖音路，不进入重连循环。"""
        if shutil_which_node() is None:
            return False, "未找到 Node.js（抖音签名需要，见使用说明抖音章节）"
        if not os.path.exists(os.path.join(self.sign_dir, "sign_runner.js")):
            return False, "缺少 douyin_sign/sign_runner.js"
        if not os.path.exists(os.path.join(self.sign_dir, "sign.js")):
            return False, "缺少 douyin_sign/sign.js（抖音签名组件，需自行获取，见使用说明）"
        return True, ""

    async def run(self, queue):
        self.queue = queue
        # 依赖预检：缺件直接停用（避免无限重连刷日志、误导用户以为在连）
        ok, why = await asyncio.to_thread(self.check_deps)
        if not ok:
            state.douyin_status = "未启用：" + why
            self.log("⚠️ 抖音通道未启用：%s" % why)
            return
        attempt = 0
        while not self._stopped:
            ss = None
            try:
                ttwid, room_id, status, title = await asyncio.to_thread(self._resolve_room)
                if status != 2:
                    self.log("ℹ️ 抖音房间 %s 当前不在播（status=%s），30s 后重试" % (self.web_rid, status))
                    await asyncio.sleep(30)
                    continue
                uid = str(random.randint(10**18, 9 * 10**18))
                state.douyin_status = "连接中…"
                self.log("🎙️ 抖音直播已识别:《%s》 连接中…" % title)
                ss, rest = await asyncio.to_thread(self._connect, room_id, uid, ttwid)
                state.douyin_status = "已连接（房间 %s）" % room_id
                self.log("✅ 抖音弹幕通道已连接（房间 %s）" % room_id)
                attempt = 0
                await self._pump(ss, rest)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._stopped:
                    break
                attempt += 1
                wait = min(30, 2 ** min(attempt, 5))
                state.douyin_status = "异常重连中（%s）" % str(e)[:40]
                self.log("⚠️ 抖音通道异常(%s)，%ds 后重连" % (str(e)[:90], wait))
                await asyncio.sleep(wait)
            finally:
                try:
                    if ss:
                        ss.close()
                except Exception:
                    pass

    async def _pump(self, ss, prebuf):
        """帧循环：读→解→入队→ack/心跳。socket 用 to_thread 读避免阻塞事件循环。"""
        buf = bytearray(prebuf)

        def _recv(n):
            while len(buf) < n:
                c = ss.recv(max(4096, n - len(buf)))
                if not c:
                    raise ConnectionError("连接被关闭")
                buf.extend(c)
            out = bytes(buf[:n])
            del buf[:n]
            return out

        def _read_frame():
            b0 = _recv(2)
            op = b0[0] & 0x0F
            ln = b0[1] & 0x7F
            if ln == 126:
                ln = int.from_bytes(_recv(2), "big")
            elif ln == 127:
                ln = int.from_bytes(_recv(8), "big")
            payload = _recv(ln) if ln else b""
            return op, payload

        def _send_frame(op, data):
            mk = os.urandom(4)
            masked = bytes(b ^ mk[i % 4] for i, b in enumerate(data))
            if len(data) < 126:
                hdr = bytes([0x80 | op, 0x80 | len(data)])
            elif len(data) < 65536:
                hdr = bytes([0x80 | op, 0xFE]) + len(data).to_bytes(2, "big")
            else:
                hdr = bytes([0x80 | op, 0xFF]) + len(data).to_bytes(8, "big")
            ss.sendall(hdr + mk + masked)

        last_hb = last_ping = time.time()
        ss.settimeout(3.0)
        while not self._stopped:
            now = time.time()
            if now - last_ping > PING_INTERVAL:
                await asyncio.to_thread(_send_frame, 0x9, b"")
                last_ping = now
            if now - last_hb > HB_INTERVAL:
                await asyncio.to_thread(_send_frame, 0x2, _wb(8, gzip.compress(b"")))
                last_hb = now
            try:
                op, payload = await asyncio.to_thread(_read_frame)
            except socket.timeout:
                continue
            except ConnectionError:
                raise
            if op == 0x9:
                await asyncio.to_thread(_send_frame, 0xA, payload)
                continue
            if op not in (0x1, 0x2) or not payload:
                continue
            pf = _parse(payload)
            log_id = _g(pf, 2) or 0
            data = _g(pf, 8) or b""
            try:
                resp = gzip.decompress(data)
            except Exception:
                resp = data
            rf = _parse(resp)
            internal_ext = _g(rf, 5) or b""
            for mb in rf.get(1, []):
                if not isinstance(mb, bytes):
                    continue
                mf = _parse(mb)
                method = _s(mf, 1)
                body = _g(mf, 2) or b""
                msg = self._map(method, body)
                if msg:
                    self.queue.put_nowait(msg)
            if internal_ext:
                ack = (_wb(2, log_id) if isinstance(log_id, bytes) else _wv(2, log_id or 0)) \
                      + _wb(7, b"ack") + _wb(8, internal_ext)
                try:
                    await asyncio.to_thread(_send_frame, 0x2, ack)
                except Exception:
                    pass

    @staticmethod
    def _map(method, body):
        """抖音 method → DanmuMsg（映射表照 DanmuFree DouyinMapper）。"""
        try:
            if method == "WebcastChatMessage":
                f = _parse(body)
                content = _s(f, 3)
                if not content:
                    return None
                user = _g(f, 2)
                nick = _s(_parse(user), 3) if isinstance(user, bytes) else ""
                return DanmuMsg("douyin", "chat", nick or "神秘观众", content)
            if method == "WebcastMemberMessage":
                f = _parse(body)
                user = _g(f, 2)
                nick = _s(_parse(user), 3) if isinstance(user, bytes) else ""
                return DanmuMsg("douyin", "member", nick or "神秘观众", "进入直播间")
            if method == "WebcastSocialMessage":
                f = _parse(body)
                user = _g(f, 2)
                nick = _s(_parse(user), 3) if isinstance(user, bytes) else ""
                return DanmuMsg("douyin", "social", nick or "神秘观众", "关注了主播")
            if method == "WebcastGiftMessage":
                f = _parse(body)
                user = _g(f, 7)
                nick = _s(_parse(user), 3) if isinstance(user, bytes) else ""
                gift = _g(f, 15)
                gname = _s(_parse(gift), 16) if isinstance(gift, bytes) else ""
                num = _g(f, 5) or 1
                return DanmuMsg("douyin", "gift", nick or "神秘观众", "", extra="%s x%s" % (gname or "礼物", num))
        except Exception:
            return None
        return None   # Like/Banner/Rank/Stats 等忽略

    def stop(self):
        self._stopped = True


def shutil_which_node():
    """找 node：PATH → 程序目录内置 node/node.exe。"""
    import shutil as _sh
    n = _sh.which("node")
    if n:
        return n
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(base, "node", "node.exe"),
                 os.path.join(os.path.dirname(base), "node", "node.exe")):
        if os.path.exists(cand):
            return cand
    return None
