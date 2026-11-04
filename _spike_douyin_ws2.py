# -*- coding: utf-8 -*-
"""抖音 WS spike 收官：完整闭环（握手→收帧→解 protobuf→打印弹幕→心跳→ack）。
参数配方 = DanmuFree DouyinSign.BuildConnectUrl（已实测 101 通过）。
IP 直连绕开本地透明代理。用法: python -X utf8 _spike_douyin_ws2.py [room_id] [秒数]"""
import socket, ssl, sys, os, base64, hashlib, subprocess, random, time, gzip, urllib.parse
import urllib.request, http.cookiejar
sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
SIGN_DIR = os.path.join(HERE, "douyin_sign")

# ---------- protobuf ----------
def rvarint(b, i):
    n = shift = 0
    while True:
        x = b[i]; i += 1
        n |= (x & 0x7F) << shift
        if not (x & 0x80): break
        shift += 7
    return n, i

def parse_fields(b):
    out, i = {}, 0
    while i < len(b):
        try: tag, i = rvarint(b, i)
        except IndexError: break
        fn, wt = tag >> 3, tag & 7
        if wt == 0: v, i = rvarint(b, i)
        elif wt == 2:
            ln, i = rvarint(b, i); v = b[i:i+ln]; i += ln
        elif wt == 5: v = b[i:i+4]; i += 4
        elif wt == 1: v = b[i:i+8]; i += 8
        else: break
        out.setdefault(fn, []).append(v)
    return out

def gf(f, n): return f.get(n, [None])[0]

def wvarint(n):
    out = bytearray()
    while True:
        x = n & 0x7F; n >>= 7
        if n: out.append(x | 0x80)
        else: out.append(x); break
    return bytes(out)

def wv(fn, v): return wvarint((fn << 3) | 0) + wvarint(v)
def wb(fn, d): return wvarint((fn << 3) | 2) + wvarint(len(d)) + d
def ws_(fn, s): return wb(fn, s.encode("utf-8"))

# ---------- WS 帧 ----------
class Buf:
    """带缓冲的 socket 读：握手时多读的字节要留给后续帧解析。"""
    def __init__(self, ss):
        self.ss = ss; self.buf = b""
    def feed(self, data):
        self.buf += data
    def read(self, n):
        while len(self.buf) < n:
            c = self.ss.recv(max(4096, n - len(self.buf)))
            if not c: raise ConnectionError("closed")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

def recv_exact(ss, n):
    buf = b""
    while len(buf) < n:
        c = ss.recv(n - len(buf))
        if not c: raise ConnectionError("closed")
        buf += c
    return buf

def read_frame(rb):
    b0 = rb.read(2)
    opcode = b0[0] & 0x0F
    ln = b0[1] & 0x7F
    if ln == 126: ln = int.from_bytes(rb.read(2), "big")
    elif ln == 127: ln = int.from_bytes(rb.read(8), "big")
    masked = b0[1] & 0x80
    payload = rb.read(ln) if ln else b""
    if masked:
        mk = payload[:4]; payload = bytes(b ^ mk[i % 4] for i, b in enumerate(payload[4:]))
    return opcode, payload

def send_frame(ss, opcode, data):
    mk = os.urandom(4)
    masked = bytes(b ^ mk[i % 4] for i, b in enumerate(data))
    if len(data) < 126: hdr = bytes([0x80 | opcode, 0x80 | len(data)])
    elif len(data) < 65536: hdr = bytes([0x80 | opcode, 0xFE]) + len(data).to_bytes(2, "big")
    else: hdr = bytes([0x80 | opcode, 0xFF]) + len(data).to_bytes(8, "big")
    ss.sendall(hdr + mk + masked)

# ---------- 准备 ----------
room_id = sys.argv[1] if len(sys.argv) > 1 else open(os.path.join(HERE, "_spike_feed.txt")).read().split("\n")[0]
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 45

cj = http.cookiejar.CookieJar()
o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
o.addheaders = [("User-Agent", UA)]
o.open("https://live.douyin.com/", timeout=15)
ttwid = next((c.value for c in cj if c.name == "ttwid"), "")
user_uid = str(random.randint(10**18, 9*10**18))

ie_raw = ("internal_src:dim|wss_push_room_id:%s|wss_push_did:%s"
          "|first_req_ms:0|fetch_time:0|seq:1|wss_info:0-0-0-0|wrds_v:0" % (room_id, user_uid))
query = ("app_name=douyin_web&version_code=180800&webcast_sdk_version=1.3.0&update_version_code=1.3.0"
         "&compress=gzip&live_id=1&aid=6383&did_rule=3&device_platform=web&identity=audience"
         "&room_id=%s&user_unique_id=%s&cursor=d-1_u-1&host=https://live.douyin.com"
         "&im_path=/webcast/im/fetch/&need_persist_msg_count=15&support_wrds=1&internal_ext=%s"
         % (room_id, user_uid, urllib.parse.quote(ie_raw, safe="")))
order = ["live_id","aid","version_code","webcast_sdk_version","room_id","sub_room_id",
         "sub_channel_id","did_rule","user_unique_id","device_platform","device_type","ac","identity"]
mp = {}
for kv in query.split("&"):
    if "=" in kv:
        k, v = kv.split("=", 1); mp[k] = urllib.parse.unquote(v)
stub = ",".join("%s=%s" % (k, mp.get(k, "")) for k in order)
md5 = hashlib.md5(stub.encode()).hexdigest()
r = subprocess.run(["node", os.path.join(SIGN_DIR, "sign_runner.js"), md5],
                   capture_output=True, text=True, cwd=SIGN_DIR, timeout=45)
sig = r.stdout.strip()
path = "/webcast/im/push/v2/?" + query + "&signature=" + urllib.parse.quote(sig)

host = "webcast3-ws-web-lf.douyin.com"
ip = socket.gethostbyname(host)
key = base64.b64encode(os.urandom(16)).decode()
req = ("\r\n".join(["GET %s HTTP/1.1" % path, "Host: %s" % host, "Upgrade: websocket",
    "Connection: Upgrade", "Sec-WebSocket-Key: %s" % key, "Sec-WebSocket-Version: 13",
    "Origin: https://live.douyin.com", "User-Agent: %s" % UA,
    "Cookie: ttwid=%s" % ttwid, "", ""])).encode()

s = socket.create_connection((ip, 443), timeout=15)
ss = ssl.create_default_context().wrap_socket(s, server_hostname=host)
ss.sendall(req)
rb = Buf(ss)
# 增量读到 HTTP 头结束标记，多出来的字节留给帧解析（不固定读 1024，防头>1024 卡死）
while b"\r\n\r\n" not in rb.buf:
    c = ss.recv(4096)
    if not c: break
    rb.buf += c
sep = rb.buf.find(b"\r\n\r\n")
head = rb.buf[:sep].decode("utf-8", "replace")
first = head.splitlines()[0] if head else "(空)"
rb.buf = rb.buf[sep + 4:] if sep >= 0 else b""
print("握手:", first, "| room:", room_id)
if "101" not in first:
    sys.exit(1)

# 握手响应里超出 HTTP 头的字节可能是第一帧数据的一部分——裸 socket 无法回退，
# 简化：握手后数据从新 recv 开始（丢的只是握手缓冲里的尾部帧，spike 可接受）
t0 = time.time(); n_msgs = n_chat = n_gift = 0
methods = {}
last_ping = last_hb = 0
ss.settimeout(3.0)
print("开始收弹幕 %ds …" % secs)
while time.time() - t0 < secs:
    now = time.time()
    if now - last_ping > 14:
        try: send_frame(ss, 0x9, b"")   # WS ping
        except Exception: break
        last_ping = now
    if now - last_hb > 9:
        try: send_frame(ss, 0x2, wb(8, gzip.compress(b"")))  # 业务心跳
        except Exception: break
        last_hb = now
    try:
        opcode, payload = read_frame(rb)
    except socket.timeout:
        continue
    except ConnectionError:
        print("连接断"); break
    if opcode == 0x9:
        send_frame(ss, 0xA, payload); continue
    if opcode not in (0x1, 0x2) or not payload:
        continue
    pf = parse_fields(payload)
    log_id = gf(pf, 2) or 0
    data = gf(pf, 8) or b""
    try: resp = gzip.decompress(data)
    except Exception: resp = data
    rf = parse_fields(resp)
    internal_ext = gf(rf, 5) or b""
    for mb in rf.get(1, []):
        mf = parse_fields(mb)
        method = (gf(mf, 1) or b"").decode("utf-8", "replace")
        body = gf(mf, 2) or b""
        n_msgs += 1
        methods[method] = methods.get(method, 0) + 1
        if method == "WebcastChatMessage":
            cf = parse_fields(body)
            content = (gf(cf, 3) or b"").decode("utf-8", "replace")
            user = gf(cf, 2)
            nick = (parse_fields(user).get(3, [b""])[0] if user else b"").decode("utf-8", "replace")
            print("💬 %s: %s" % (nick[:12], content[:40]))
            n_chat += 1
        elif method == "WebcastGiftMessage":
            n_gift += 1
        elif method == "WebcastMemberMessage" and n_chat == 0:
            pass
    if internal_ext:
        # log_id 可能是字符串或 varint，按原类型回写
        ack = (wb(2, log_id) if isinstance(log_id, bytes) else wv(2, log_id or 0)) \
              + ws_(7, "ack") + wb(8, internal_ext)
        try: send_frame(ss, 0x2, ack)
        except Exception: pass

print("\n结论: %ds 收到 %d 条消息 | 弹幕 %d 条 | 礼物 %d 条 → %s"
      % (secs, n_msgs, n_chat, n_gift, "✅✅ 抖音弹幕接入全链路打通！" if n_msgs else "⚠️ 连上但无消息(可能房间太冷)"))
print("方法分布:", sorted(methods.items(), key=lambda x: -x[1])[:12])
ss.close()
