# -*- coding: utf-8 -*-
"""本机 HTTP API（v1.2.4·给 AI / 脚本用的双向接口）。

设计边界（用户拍板）：
  · 只绑 127.0.0.1 —— 外网碰不到；
  · **必须带 token**：config.json 的 `api_token`，请求带 `?token=xxx` 或
    请求头 `X-Api-Token`。没配 token 时接口整体休眠（返回 403 说明如何配），
    杜绝"免密裸奔"。
  · 字段白名单：只暴露/操作业务字段，**禁止**改 cookie、凭据、缓存路径、
    程序路径这类敏感项。

端点（全部 GET 可直接浏览器试，写操作用 POST JSON）：
  GET  /api/state            完整状态（播放/队列/暂停/版本/端口）
  GET  /api/danmaku?limit=N  最近收到的直播间弹幕（环形缓存）
  POST /api/send             发 B站弹幕 {"text":"..."}（继承每分钟3条限频）
  GET  /api/queue            点歌列表（处理中 + 已就绪）
  POST /api/queue/add        点歌入队 {"song":"晴天","user":"AI"}
  POST /api/queue/remove     删除 {"zone":"pending|ready","index":N}
  POST /api/queue/move       置顶/换序 {"index":N,"to":0}（ready 区）
  POST /api/skip             切歌
  POST /api/pause            暂停/继续 {"on":true}

所有写操作都投递到 asyncio 线程执行（队列归 loop 线程所有），
返回 {ok:true,...} 或 {ok:false,error:"..."}。
"""

import json
import time

from aiohttp import web

import state
import settings


def _cfg_token():
    """从 config.json 读 api_token（经 secretstore 透明读，兼容旧明文）。"""
    try:
        import secretstore
        cfg = secretstore.read_json(settings.CONFIG_FILE, default={}) or {}
        return str(cfg.get("api_token") or "").strip()
    except Exception:
        return ""


def _authorized(request):
    """校验 token：?token= 或 X-Api-Token 头。返回 (bool, 错误响应或None)。"""
    want = _cfg_token()
    if not want:
        return False, web.json_response({
            "ok": False,
            "error": "接口未启用：请在 config.json 里设置 api_token（任意字符串）后重启点歌台",
        }, status=403)
    got = (request.query.get("token")
           or request.headers.get("X-Api-Token") or "").strip()
    if got != want:
        return False, web.json_response({"ok": False, "error": "token 无效"}, status=403)
    return True, None


def _ok(**kw):
    d = {"ok": True}
    d.update(kw)
    return web.json_response(d)


def _err(msg, status=400):
    return web.json_response({"ok": False, "error": msg}, status=status)


# ── 读接口 ─────────────────────────────────────────────────────────
async def handle_state(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    cur = state.current_song
    return _ok(
        version=__import__("version").DISPLAY,
        port=state.overlay_port,
        platform="bilibili+douyin",
        playing={
            "song": (cur or {}).get("display_name"),
            "requester": (cur or {}).get("requester"),
            "paused": bool(state.paused),
        },
        queue={
            "processing": (state.processing_request or {}).get("song_name"),
            "pending": [{"song": r.get("song_name"), "user": r.get("uname"),
                         "platform": r.get("platform")} for r in state.pending_requests],
            "ready": [{"song": r.get("display_name"), "user": r.get("requester")}
                      for r in state.playlist],
        },
        counts={"pending": len(state.pending_requests) + (1 if state.processing_request else 0),
                "ready": len(state.playlist)},
    )


async def handle_danmaku(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    try:
        limit = int(request.query.get("limit") or 50)
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 500))
    hist = state.danmaku_history[-limit:]
    return _ok(count=len(hist), capacity=state.danmaku_history_size,
               items=[{"time": time.strftime("%H:%M:%S", time.localtime(m.get("ts") or 0)),
                       "ts": m.get("ts"), "platform": m.get("platform"),
                       "user": m.get("uname"), "text": m.get("text"),
                       "is_cmd": m.get("is_cmd")} for m in hist])


async def handle_queue(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    return _ok(
        processing=(state.processing_request or {}).get("song_name"),
        pending=[{"song": r.get("song_name"), "user": r.get("uname")}
                 for r in state.pending_requests],
        ready=[{"song": r.get("display_name"), "user": r.get("requester"),
                "mid": r.get("mid")} for r in state.playlist],
    )


# ── 写接口（全部投递到 asyncio loop 线程改 state）──────────────────
async def _body(request):
    try:
        return await request.json()
    except Exception:
        return {}


async def handle_send(request):
    """发 B站弹幕。走 mainapp 持有的 RateLimitedSender（同一限频）。"""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    text = str(body.get("text") or "").strip()
    if not text:
        return _err("缺少 text")
    app = state.app
    sender = getattr(app, "danmaku_sender", None) if app else None
    if sender is None:
        return _err("发弹幕组件未就绪（可能未登录 B站 或缺少 Cookie）", 503)
    reason = sender.send(text)
    if reason:
        return _err("被限频或拦下：%s" % reason, 429)
    return _ok(text=text[:40], note="已排队发送")


async def handle_queue_add(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    song = str(body.get("song") or "").strip()
    user = str(body.get("user") or "AI").strip()[:30]
    if not song:
        return _err("缺少 song")
    state.pending_requests.append({"song_name": song, "uname": user,
                                   "platform": "api", "ts": time.time()})
    return _ok(song=song, user=user, note="已入点歌队列，将按顺序下载并播放")


async def handle_queue_remove(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    zone = str(body.get("zone") or "ready")
    try:
        idx = int(body.get("index"))
    except (TypeError, ValueError):
        return _err("缺少 index（0 起）")
    lst = state.pending_requests if zone == "pending" else state.playlist
    if not (0 <= idx < len(lst)):
        return _err("index 越界（当前 %d 项）" % len(lst))
    removed = lst.pop(idx)
    name = removed.get("song_name") or removed.get("display_name")
    return _ok(removed=name, zone=zone)


async def handle_queue_move(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    try:
        idx = int(body.get("index"))
        to = int(body.get("to", 0))
    except (TypeError, ValueError):
        return _err("需要 index 和 to（均 0 起）")
    lst = state.playlist
    if not (0 <= idx < len(lst)):
        return _err("index 越界（当前 %d 项）" % len(lst))
    item = lst.pop(idx)
    to = max(0, min(to, len(lst)))
    lst.insert(to, item)
    return _ok(moved=item.get("display_name"), to=to)


async def handle_skip(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    if not state.skip_event:
        return _err("播放引擎未就绪", 503)
    state.skip_event.set()
    return _ok(note="已切歌")


async def handle_pause(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    on = bool(body.get("on", True))
    app = state.app
    if app is None:
        return _err("程序未就绪", 503)
    # 复用 GUI 同一入口（内部会 root.after 编组到 Tk 线程）
    try:
        app.request_pause(on)
    except Exception as e:
        return _err("暂停操作失败：%s" % e, 500)
    return _ok(paused=on)


def register(web_app):
    """把全部端点挂到 OBS 那个 aiohttp 应用上（同一个端口，省得再开服务）。"""
    web_app.router.add_get("/api/state", handle_state)
    web_app.router.add_get("/api/danmaku", handle_danmaku)
    web_app.router.add_get("/api/queue", handle_queue)
    web_app.router.add_post("/api/send", handle_send)
    web_app.router.add_post("/api/queue/add", handle_queue_add)
    web_app.router.add_post("/api/queue/remove", handle_queue_remove)
    web_app.router.add_post("/api/queue/move", handle_queue_move)
    web_app.router.add_post("/api/skip", handle_skip)
    web_app.router.add_post("/api/pause", handle_pause)
