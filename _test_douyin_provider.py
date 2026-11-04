# -*- coding: utf-8 -*-
"""v1.2 抖音接入回归测试（纯逻辑部分）。
用法: python -X utf8 _test_douyin_provider.py
覆盖：handle_message 双平台同行为 / DouyinMapper 消息映射 / 签名 stub 拼接。"""
import os, sys, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
import state, danmaku
from live_providers.douyin import DouyinProvider, _wb, _parse
_stub_from_query = DouyinProvider._stub_from_query
from live_providers import DanmuMsg

results = []
def ck(name, ok, d=""):
    results.append(ok); print(("OK  " if ok else "FAIL"), name, d)

# ---------- handle_message 平台无关 ----------
class FakeApp:
    def __init__(self):
        self.logs = []; self.pauses = []
        self.config = {}
    def log(self, m): self.logs.append(m)
    def root_after(self, _ms, fn): fn and fn()
    class _R:
        def after(self, ms, fn): fn and fn()
    root = _R()
    def request_pause(self, on): self.pauses.append(on)

state.pending_requests.clear()
state.skip_event = None

a = FakeApp()
danmaku.handle_message(a, "点歌 晴天", "阿伟", "douyin")
ck("抖音点歌入队", len(state.pending_requests) == 1 and state.pending_requests[0]["song_name"] == "晴天")
ck("抖音日志带平台标", any("[douyin]" in m for m in a.logs), a.logs)

state.pending_requests.clear()
a.logs.clear()   # 复用同一 FakeApp：先清掉抖音阶段的日志再验 B站
danmaku.handle_message(a, "点歌 晴天", "张三", "bilibili")
ck("B站点歌入队(同行为)", len(state.pending_requests) == 1)
ck("B站日志无平台标", all("[douyin]" not in m for m in a.logs), a.logs)

danmaku.handle_message(a, "暂停", "x", "douyin"); danmaku.handle_message(a, "继续", "x", "douyin")
ck("暂停/继续两平台通吃", a.pauses == [True, False])

danmaku.handle_message(a, "点歌 晴天 部分 点歌 多余", "y", "bilibili")
ck("点歌前缀只剥第一个", state.pending_requests[-1]["song_name"] == "晴天 部分 点歌 多余")

# ---------- DouyinMapper 消息映射 ----------
# 手工构造 protobuf 字节：User{f3=nick} → ChatMessage{f2=user,f3=content}
def _mk_chat(nick, content):
    user = _wb(3, nick.encode())
    return _wb(2, user) + _wb(3, content.encode())

msg = DouyinProvider._map("WebcastChatMessage", _mk_chat("七七", "主播好"))
ck("chat 映射", msg is not None and msg.platform == "douyin" and msg.type == "chat"
   and msg.uname == "七七" and msg.text == "主播好")
ck("空内容丢弃", DouyinProvider._map("WebcastChatMessage", _mk_chat("a", "")) is None)
ck("未知方法忽略", DouyinProvider._map("WebcastLikeMessage", b"") is None)
ck("进场映射", DouyinProvider._map("WebcastMemberMessage", _wb(2, _wb(3, "路人".encode()))).type == "member")

# ---------- 签名 stub 拼接（对照 DanmuFree ParamOrder） ----------
q = ("app_name=douyin_web&live_id=1&aid=6383&version_code=180800"
     "&webcast_sdk_version=1.3.0&room_id=7704209084769471268&did_rule=3"
     "&user_unique_id=1234567890123456789&device_platform=web&identity=audience"
     "&internal_ext=a%7Cb")
stub = _stub_from_query(q)
parts = stub.split(",")
ck("stub 13 字段", len(parts) == 13, stub)
ck("stub 顺序=live_id 开头", parts[0] == "live_id=1")
ck("stub room_id 正确", "room_id=7704209084769471268" in parts)
ck("stub 缺失字段空值", "sub_room_id=" in parts and "ac=" in parts)
ck("stub URL解码 internal 不影响", "identity=audience" in parts)

bad = results.count(False)
print("结论:", "✅ 抖音 provider 回归 %d/%d 全过" % (len(results), len(results)) if bad == 0 else "❌ 失败 %d 项" % bad)
sys.exit(0 if bad == 0 else 1)
