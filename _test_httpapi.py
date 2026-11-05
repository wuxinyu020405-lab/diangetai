# -*- coding: utf-8 -*-
"""v1.2.4 回归：本机 AI 接口（httpapi.py）真实 HTTP 端到端。

真起一个 aiohttp 服务（绑 127.0.0.1 随机端口）→ 真发 HTTP 请求验证：
token 鉴权（无 token/错 token/对 token）、弹幕历史（可调容量）、
读状态/队列、点歌入队、删除、置顶、切歌、暂停。
写操作的 state 改动都走 loop 线程（测试用同 loop 校验真生效）。
用法: ./.venv\\Scripts\\python.exe -X utf8 _test_httpapi.py
"""
import asyncio
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "点歌台拆分"))
import state
import httpapi
from aiohttp import web

RES = []
TOKEN = "test-token-123"


def ck(name, cond, extra=""):
    RES.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  [{extra}]"))


def http(method, url, body=None, token=None, timeout=8):
    """真发 HTTP。返回 (status, json_dict)。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Api-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


class FakeSender:
    """替身：记录调用（不真发 B站）。"""
    def __init__(self):
        self.sent = []
    def send(self, text):
        if len(self.sent) >= 3:
            return "回执限频(每分钟3条)已用完"
        self.sent.append(text)
        return None


class FakeApp:
    def __init__(self):
        self.danmaku_sender = FakeSender()
        self.logs = []
    def log(self, m):
        self.logs.append(m)
    def request_pause(self, on):
        state.paused = bool(on)


async def start_server():
    app = web.Application()
    httpapi.register(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, site, port


def run_loop_bg(loop, runner, site_holder):
    """后台线程跑 loop，服务持续可用（主线程才能发 HTTP）。"""
    import threading
    async def _boot():
        runner, site, port = await start_server()
        site_holder["port"] = port
        site_holder["runner"] = runner
        site_holder["ready"].set()
    asyncio.set_event_loop(loop)
    site_holder["ready"] = threading.Event()
    loop.run_until_complete(_boot())
    loop.run_forever()


def main():
    # 配置：写 TOKEN 到 config（用 secretstore 便于加密口径一致）
    import secretstore
    import settings
    # 备份真实 config，测完还原（避免污染用户真实配置）
    _bak = None
    if os.path.exists(settings.CONFIG_FILE):
        try:
            _bak = secretstore.read_json(settings.CONFIG_FILE, default=None)
        except Exception:
            _bak = None
    secretstore.write_json(settings.CONFIG_FILE, {"api_token": TOKEN})
    fake_app = FakeApp()
    state.app = fake_app
    state.danmaku_history_size = 200
    state.danmaku_history = []
    state.skip_event = asyncio.Event()
    state.paused = False
    state.pending_requests.clear()
    state.playlist.clear()
    state.processing_request = None

    loop = asyncio.new_event_loop()
    state.skip_event = None   # 延后到 loop 线程里建
    holder = {}
    import threading

    def _boot():
        asyncio.set_event_loop(loop)
        state.skip_event = asyncio.Event()   # 必须在 loop 线程内建
        async def _inner():
            runner, site, port = await start_server()
            holder["port"] = port
            holder["runner"] = runner
        loop.run_until_complete(_inner())
        holder["ready"].set()
        loop.run_forever()

    holder["ready"] = threading.Event()
    t = threading.Thread(target=_boot, daemon=True)
    t.start()
    holder["ready"].wait(10)
    port = holder["port"]
    base = f"http://127.0.0.1:{port}"

    # ═══ 鉴权 ═══
    st, j = http("GET", base + "/api/state")
    ck("① 无 token → 403", st == 403 and j.get("ok") is False, st)
    st, j = http("GET", base + "/api/state", token="wrong")
    ck("② 错 token → 403", st == 403 and "无效" in (j.get("error") or ""), j)
    st, j = http("GET", base + "/api/state", token=TOKEN)
    ck("③ 对 token → 200", st == 200 and j.get("ok") is True, st)
    ck("④ 状态含版本/端口/队列计数",
       "version" in j and "port" in j and "counts" in j, j)

    # ═══ 弹幕历史（容量可调）═══
    import danmaku
    for i in range(5):
        danmaku._record_history("观众弹幕%d" % i, "用户%d" % i, "bilibili", i < 2)
    st, j = http("GET", base + "/api/danmaku?limit=3", token=TOKEN)
    ck("⑤ 读弹幕历史 limit 生效", st == 200 and j.get("count") == 3, j.get("count"))
    ck("⑥ 弹幕含平台/用户/文本/是否指令",
       all(k in j["items"][0] for k in ("platform", "user", "text", "is_cmd")), j["items"][0])
    state.danmaku_history_size = 2
    for i in range(3):
        danmaku._record_history("溢出%d" % i, "u", "douyin", False)
    st, j = http("GET", base + "/api/danmaku", token=TOKEN)
    ck("⑦ 容量调成2后只留2条（且是最新的）",
       j.get("count") == 2 and j.get("capacity") == 2
       and j["items"][-1]["text"] == "溢出2", j)
    state.danmaku_history_size = 200

    # ═══ 发弹幕 ═══
    st, j = http("POST", base + "/api/send", {"text": "测试弹幕"}, token=TOKEN)
    ck("⑧ 发弹幕成功入队", st == 200 and j.get("ok") is True, j)
    ck("⑨ sender 真被调用", fake_app.danmaku_sender.sent == ["测试弹幕"],
       fake_app.danmaku_sender.sent)
    st, j = http("POST", base + "/api/send", {"text": ""}, token=TOKEN)
    ck("⑩ 空文本被拒", st == 400 and j.get("ok") is False, j)
    for i in range(3):   # 打满限频（已发1条，再发3条→第4条被拦）
        http("POST", base + "/api/send", {"text": "压测%d" % i}, token=TOKEN)
    st, j = http("POST", base + "/api/send", {"text": "应当被限频"}, token=TOKEN)
    ck("⑪ 限频生效返回 429", st == 429 and "限频" in (j.get("error") or ""), j)

    # ═══ 点歌入队 ═══
    st, j = http("POST", base + "/api/queue/add", {"song": "晴天", "user": "AI"}, token=TOKEN)
    ck("⑫ 点歌入队成功", st == 200 and state.pending_requests, state.pending_requests)
    ck("⑬ 入队记录正确(song/user/platform=api)",
       state.pending_requests[0]["song_name"] == "晴天"
       and state.pending_requests[0]["platform"] == "api", state.pending_requests[0])
    st, j = http("POST", base + "/api/queue/add", {"song": ""}, token=TOKEN)
    ck("⑭ 空歌名被拒", st == 400, st)

    # ═══ 修改点歌列表：删除 / 置顶 ═══
    state.playlist.clear()
    for n in ("歌A", "歌B", "歌C"):
        state.playlist.append({"display_name": n, "requester": "观众", "mid": n})
    st, j = http("POST", base + "/api/queue/remove",
                 {"zone": "ready", "index": 1}, token=TOKEN)
    ck("⑮ 删除就绪项正确", st == 200 and [x["display_name"] for x in state.playlist] == ["歌A", "歌C"]
       and j.get("removed") == "歌B", [x["display_name"] for x in state.playlist])
    st, j = http("POST", base + "/api/queue/remove",
                 {"zone": "pending", "index": 0}, token=TOKEN)
    ck("⑯ 删除排队项正确", st == 200 and state.pending_requests == [], state.pending_requests)
    st, j = http("POST", base + "/api/queue/remove",
                 {"zone": "ready", "index": 99}, token=TOKEN)
    ck("⑰ 越界删除返回 400 不误删", st == 400 and len(state.playlist) == 2, st)

    st, j = http("POST", base + "/api/queue/move", {"index": 1, "to": 0}, token=TOKEN)
    ck("⑱ 置顶生效", st == 200 and state.playlist[0]["display_name"] == "歌C",
       [x["display_name"] for x in state.playlist])
    st, j = http("GET", base + "/api/queue", token=TOKEN)
    ck("⑲ 读队列顺序与 state 一致",
       [x["song"] for x in j["ready"]] == ["歌C", "歌A"], j["ready"])

    # ═══ 切歌 / 暂停 ═══
    st, j = http("POST", base + "/api/skip", token=TOKEN)
    ck("⑳ 切歌置位 skip_event", st == 200 and state.skip_event.is_set(), st)
    st, j = http("POST", base + "/api/pause", {"on": True}, token=TOKEN)
    ck("㉑ 暂停生效", st == 200 and state.paused is True, st)
    st, j = http("POST", base + "/api/pause", {"on": False}, token=TOKEN)
    ck("㉒ 继续生效", st == 200 and state.paused is False, st)

    # 收尾：先停服务再停 loop（避免 "Task was destroyed but pending"）
    import asyncio as _a
    fut = _a.run_coroutine_threadsafe(holder["runner"].cleanup(), loop)
    try:
        fut.result(timeout=5)
    except Exception:
        pass
    loop.call_soon_threadsafe(loop.stop)
    t.join(3)

    # 还原真实 config（不污染用户环境）
    try:
        if _bak is not None:
            secretstore.write_json(settings.CONFIG_FILE, _bak)
        else:
            os.remove(settings.CONFIG_FILE)
    except Exception:
        pass

    bad = [n for n, ok in RES if not ok]
    print(f"\n{'✅' if not bad else '❌'} _test_httpapi: {len(RES)-len(bad)}/{len(RES)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
