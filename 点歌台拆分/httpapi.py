# -*- coding: utf-8 -*-
"""本机 HTTP API（v1.2.6+ · 给本机 AI / 脚本用的能力开放层）。

设计边界（用户拍板，红线不可拆）：
  · 只绑 127.0.0.1 —— 外网碰不到（mainapp.main_async 里 TCPSite('127.0.0.1', port)）；
  · **必须带 token**：config.json 的 `api_token`，`?token=xxx` 或头 `X-Api-Token`。
    没配 token 时接口整体休眠（返回 403 说明如何配）。
  · **字段白名单**：只暴露/操作业务与样式字段，**禁止**读写
    api_token / bili_cookie / qqmusic_path / credential.json 的 musickey·musicid
    以及房间号等凭据·路径类配置；也不提供任何文件增删、程序退出、登录扫码能力。
  · 弹幕采集/指令解析逻辑（danmaku.py）一行不动；本次只扩 httpapi.py。

端点总览（GET 读 / POST 写，全部需 token）：
  能力自发现   GET  /api/capabilities
  状态         GET  /api/state   /api/queue   /api/account   /api/lyric
  弹幕         GET  /api/danmaku?limit=N&since_ts=F&since_seq=N
  设置         GET  /api/settings      POST /api/settings
  音量/音质    POST /api/volume        POST /api/quality
  日志         GET  /api/log?tail=N
  事件流       GET  /api/events  （SSE：hello/state/queue/danmaku/log/play/pause/lyric/settings）
  发弹幕       POST /api/send   /api/send/test     /api/sender/reload
  队列         POST /api/queue/add  /api/queue/remove  /api/queue/move  /api/queue/top
  播放         POST /api/skip   /api/pause         /api/pause/toggle

所有 handler 运行在 OBS 服务所在的同一个 asyncio loop 线程（与播放/点歌 worker
同线程），直接读写 state 是协作式安全的；涉及 Tk 控件一律经 root.after 编组。
"""

import asyncio
import base64
import copy
import json
import os
import re
import time

from aiohttp import web

import state
import settings


# ── 安全边界常量 ───────────────────────────────────────────────────
# 可通过 /api/settings 写入的非敏感配置键（值会做类型与范围校验）
_CONFIG_WRITE_KEYS = {
    "danmaku_send_enabled": "bool",
    "danmaku_sends_per_min": ("int", 1, 60),
    "danmaku_min_gap_sec": ("float", 0.0, 60.0),
    "danmaku_history_size": ("int", 0, 5000),
}

# 只读展示（不写）：房间号是公开信息、状态类不算凭据
_CONFIG_READ_KEYS = ("room_id", "douyin_room_id")

# 永久否决（L3）：任何接口都不读、不写、不回显
_DENIED_KEYS = (
    "api_token", "bili_cookie", "qqmusic_path",
    "credential.json:musickey", "credential.json:musicid",
)

_STYLE_SECTIONS = ("mixed", "lyric", "playing", "queue", "global")
_STYLE_SCALARS = ("audio_quality", "max_cache_files", "max_cache_size_mb")

# ── v1.2.9：本地曲库写入边界（方案 A：只允许 AI 上传音频内容）──────
# 只往 LOCAL_SONGS_DIR 这一个目录写；扩展名白名单；单文件上限；重名不覆盖；
# 写完立刻校验是不是真能播，不能播就删掉。绝不接受"源路径"(那是读任意路径)。
LOCAL_ALLOWED_EXTS = (".mp3", ".wav", ".flac", ".ogg")
LOCAL_MAX_BYTES = 200 * 1024 * 1024          # 单首上限 200MB
LOCAL_MIN_BYTES = 100 * 1024                  # 与 locallib.MIN_BYTES 一致


def _local_dir():
    """当前生效的本地曲库目录（跟 mainapp.get_local_songs_dir 同一口径）。"""
    app = state.app
    cfg = getattr(app, "config", {}) if app is not None else {}
    folder = (cfg.get("local_songs_dir") or settings.LOCAL_SONGS_DIR)
    if not os.path.isabs(folder):
        folder = os.path.join(settings.BASE_DIR, folder)
    return folder


def _safe_song_name(raw):
    """把用户/AI 给的名字清洗成安全的文件名主干。返回 (name, 错误)。

    严格：只保留文字、数字、空格与少量安全符号，绝不带路径分隔符；
    挡掉 '..'、控制字符、Windows 保留名、首尾点空格。
    """
    s = str(raw or "").strip()
    if not s:
        return "", "缺少歌名"
    # 去掉扩展名（如果传了）
    base, ext = os.path.splitext(s)
    if ext.lower() in LOCAL_ALLOWED_EXTS:
        s = base
    # 只留安全字符：中英文、数字、空格、- _ ( ) . ' & 、 · 等常见符号
    safe = re.sub(r'[^\w\u4e00-\u9fff \-_().\'&·、,，]', "", s, flags=re.UNICODE)
    safe = safe.strip(" .")               # 去首尾点与空格（Windows 不允许结尾点）
    if not safe:
        return "", "歌名里没有可用字符"
    if safe.upper() in ("CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
                        "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
                        "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"):
        return "", "歌名撞上系统保留名"
    if len(safe) > 120:
        safe = safe[:120]
    return safe, ""


# ── 日志环形缓冲（不碰 mainapp，运行时挂 log 钩子）─────────────────
_LOG_RING = []          # [{"seq":int, "ts":float, "text":str}]
_LOG_RING_CAP = 500
_LOG_SEQ = 0


def _push_log(text):
    global _LOG_SEQ
    _LOG_SEQ += 1
    _LOG_RING.append({"seq": _LOG_SEQ, "ts": time.time(), "text": str(text)})
    if len(_LOG_RING) > _LOG_RING_CAP:
        del _LOG_RING[:len(_LOG_RING) - _LOG_RING_CAP]


def _install_log_hook():
    """首次调用时把 app.log 包一层，同步喂给内存环形缓冲；并在 Tk 线程
    把已存在的日志文本回填一次。幂等，失败不影响主程序。"""
    app = state.app
    if app is None:
        return False
    if getattr(app, "_api_log_hooked", False):
        return True

    def _seed():
        try:
            txt = app.log_text.get("1.0", "end")
            for line in (txt or "").splitlines():
                line = line.strip()
                if line:
                    _push_log(line)
        except Exception:
            pass

    try:
        app.root.after(0, _seed)
    except Exception:
        pass

    orig_log = app.log

    def _wrapped(msg):
        try:
            _push_log("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
        except Exception:
            pass
        return orig_log(msg)

    try:
        app.log = _wrapped
        sender = getattr(app, "danmaku_sender", None)
        if sender is not None:
            sender.log = _wrapped
        app._api_log_hooked = True
    except Exception:
        return False
    return True


# ── 弹幕游标（不改 danmaku.py，用对象身份发单调 seq）──────────────
_danmaku_seq = 0
_danmaku_ids = {}       # id(dict) -> (seq, ref)；持有 ref 防 id 复用


def _assign_danmaku_seqs():
    global _danmaku_seq
    live = set()
    try:
        for m in state.danmaku_history:
            k = id(m)
            live.add(k)
            entry = _danmaku_ids.get(k)
            if entry is None or entry[1] is not m:
                _danmaku_seq += 1
                _danmaku_ids[k] = (_danmaku_seq, m)
        for k in list(_danmaku_ids.keys()):
            if k not in live:
                del _danmaku_ids[k]
    except Exception:
        pass


def _seq_of(m):
    e = _danmaku_ids.get(id(m))
    return e[0] if e and e[1] is m else 0


def _danmaku_item(m):
    return {
        "time": time.strftime("%H:%M:%S", time.localtime(m.get("ts") or 0)),
        "ts": m.get("ts"),
        "seq": _seq_of(m),
        "platform": m.get("platform"),
        "user": m.get("uname"),
        "text": m.get("text"),
        "is_cmd": m.get("is_cmd"),
    }


# ── 鉴权与响应（沿用 v1.2.4 原语义，未改动）────────────────────────
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


async def _body(request):
    try:
        return await request.json()
    except Exception:
        return {}


# ── 设置读写辅助 ───────────────────────────────────────────────────
def _style_allowed_keys():
    """白名单 = 当前生效样式里已经存在的键；AI 只能改已有项，不能凭空造键。"""
    out = {}
    for s in _STYLE_SECTIONS:
        sec = state.style_config.get(s)
        if isinstance(sec, dict):
            out[s] = set(sec.keys())
    return out


def _norm_quality(v):
    s = str(v).strip()
    if s in settings.UI_QUALITY_MAP:
        s = settings.UI_QUALITY_MAP[s]
    return settings.normalize_quality_key(s)


def _coerce_style_value(key, old, new):
    """按现有值的类型做轻量校验/钳制；返回 None 表示值无效应忽略。"""
    try:
        if isinstance(old, bool):
            if isinstance(new, str):
                return new.strip().lower() in ("1", "true", "yes", "on", "是")
            return bool(new)
        if isinstance(old, int):            # bool 已在上面拦截
            v = int(float(new))
            if "size" in key or key in ("max_chars", "max_items", "line_spacing", "lines_prev", "lines_next"):
                return max(0, min(v, 300))
            return max(0, min(v, 10000))
        if isinstance(old, float):
            v = float(new)
            if key == "volume":
                if v > 1.0:
                    v = v / 100.0           # 也接受 0~100 的百分比
                return max(0.0, min(v, 1.0))
            if key == "opacity":
                return max(0.0, min(v, 2.0))
            return max(0.0, min(v, 10000.0))
        return str(new)[:200]
    except (TypeError, ValueError):
        return None


def _apply_volume_runtime(v):
    try:
        import pygame
        app = state.app
        if app is not None and getattr(app, "audio_backend", "none") == "pygame" \
                and pygame.mixer.get_init():
            pygame.mixer.music.set_volume(v)
    except Exception:
        pass


def _apply_scalar(k, val, changed, ignored):
    if k == "audio_quality":
        q = _norm_quality(val)
        if q != state.style_config.get("audio_quality"):
            state.style_config["audio_quality"] = q
            changed["style_config.audio_quality"] = q
        return
    if k in ("max_cache_files", "max_cache_size_mb"):
        try:
            v = max(1, min(int(float(val)), 1000000))
        except (TypeError, ValueError):
            ignored.append(k + "(值无效)")
            return
        if v != state.style_config.get(k):
            state.style_config[k] = v
            changed["style_config." + k] = v


def _settings_snapshot():
    app = state.app
    cfg = app.config if app is not None else {}
    out = {"style_config": copy.deepcopy(state.style_config)}
    for k in _CONFIG_WRITE_KEYS:
        out[k] = cfg.get(k)
    return out


def _persist(app):
    """落盘：等价于 mainapp.save_style_config，但在 loop 线程同步写一次。"""
    if app is None:
        return
    try:
        app.config["style_config"] = state.style_config
        import secretstore
        secretstore.write_json(settings.CONFIG_FILE, app.config)
    except Exception:
        try:
            app.schedule_save_style()
        except Exception:
            pass


def _sync_gui(app):
    """尽力把 API 改动同步回 GUI 控件（全部编组到 Tk 线程，异常吞掉）。"""
    if app is None:
        return

    def _do():
        try:
            import ui_ctk
            v = state.style_config.get("global", {}).get("volume", 1.0)
            pct = int(round(float(v) * 100))
            ui_ctk.set_label(getattr(app, "lbl_volume_pct", None), text="%d%%" % pct)
            try:
                app.scale_volume.set(pct)
            except Exception:
                pass
        except Exception:
            pass
        try:
            q = settings.QUALITY_UI_MAP.get(
                settings.normalize_quality_key(state.style_config.get("audio_quality")),
                "FLAC 无损品质")
            app.var_audio_quality.set(q)
            app.combo_quality_top.set(q)
        except Exception:
            pass
        try:
            pairs = (
                ("entry_dm_per_min", str(app.config.get("danmaku_sends_per_min", 3))),
                ("entry_dm_gap_sec", str(app.config.get("danmaku_min_gap_sec", 3))),
                ("entry_dm_hist", str(app.config.get("danmaku_history_size", 200))),
                ("entry_max_files", str(state.style_config.get("max_cache_files", 100))),
                ("entry_max_size", str(state.style_config.get("max_cache_size_mb", 500))),
            )
            for name, val in pairs:
                w = getattr(app, name, None)
                if w is None:
                    continue
                w.delete(0, "end")
                w.insert(0, val)
        except Exception:
            pass

    try:
        app.root.after(0, _do)
    except Exception:
        pass


def _settings_apply(body):
    """把白名单字段写进 state.style_config / app.config。返回 (changed, ignored)。"""
    changed = {}
    ignored = []
    app = state.app
    cfg = app.config if app is not None else {}

    # 0) 敏感字段：明确回执「拒不处理」，绝不静默忽略，也绝不写入
    _KNOWN = set(_CONFIG_WRITE_KEYS) | set(_STYLE_SCALARS) | {"style_config", "volume"}
    _SENSITIVE_HINTS = ("cookie", "token", "musickey", "musicid", "path",
                        "credential", "secret", "password", "cookie_str")
    for k in body:
        if k in _KNOWN:
            continue
        kl = str(k).lower()
        if any(h in kl for h in _SENSITIVE_HINTS) or k in ("room_id", "douyin_room_id"):
            ignored.append(k + "(敏感/只读字段，拒不处理)")
    # style_config 补丁里的敏感键也逐段拦
    sc_check = body.get("style_config")
    if isinstance(sc_check, dict):
        for section, patch in sc_check.items():
            if not isinstance(patch, dict):
                if any(h in str(section).lower() for h in _SENSITIVE_HINTS):
                    ignored.append("style_config.%s(敏感字段，拒不处理)" % section)
                continue
            for key in patch:
                if any(h in str(key).lower() for h in _SENSITIVE_HINTS):
                    ignored.append("style_config.%s.%s(敏感字段，拒不处理)" % (section, key))

    # 1) 把嵌套 style_config 与扁平便捷键合并成一份 patch
    sc = body.get("style_config")
    patches = dict(sc) if isinstance(sc, dict) else {}
    if "volume" in body:
        g = dict(patches.get("global") or {}) if isinstance(patches.get("global"), dict) else {}
        g["volume"] = body["volume"]
        patches["global"] = g
    for k in _STYLE_SCALARS:
        if k in body and k not in patches:
            patches[k] = body[k]

    # 2) 样式
    allowed = _style_allowed_keys()
    for section, patch in patches.items():
        if not isinstance(patch, dict):
            if section in _STYLE_SCALARS:
                _apply_scalar(section, patch, changed, ignored)
            else:
                ignored.append(section)
            continue
        if section not in _STYLE_SECTIONS or section not in allowed:
            ignored.append(section)
            continue
        target = state.style_config.setdefault(section, {})
        for key, val in patch.items():
            if key not in allowed[section]:
                ignored.append("%s.%s" % (section, key))
                continue
            old = target.get(key)
            new = _coerce_style_value(key, old, val)
            if new is None:
                ignored.append("%s.%s(值无效)" % (section, key))
                continue
            # v1.2.9：字体键做归一。AI 常说中文名（楷体/黑体），归一成英文族名
            # 跨浏览器更稳；但用户传的是完整字体栈（含逗号）就原样保留，
            # 不能把它压成单字体，否则会把用户配好的回退链弄丢。
            if "font" in key and isinstance(new, str) and new.strip() and "," not in new:
                try:
                    import fontlib
                    fam = fontlib.canonical_css_name(new)
                    new = fontlib.to_css(fam)
                except Exception:
                    pass
            if old != new:
                target[key] = new
                changed["style_config.%s.%s" % (section, key)] = new
                if section == "global" and key == "volume":
                    _apply_volume_runtime(new)

    # 3) 非敏感配置键
    dm_changed = False
    for k, rule in _CONFIG_WRITE_KEYS.items():
        if k not in body:
            continue
        val = body[k]
        if rule == "bool":
            if isinstance(val, str):
                v = val.strip().lower() in ("1", "true", "yes", "on", "是")
            else:
                v = bool(val)
        else:
            kind, lo, hi = rule
            try:
                v = int(float(val)) if kind == "int" else float(val)
            except (TypeError, ValueError):
                ignored.append(k + "(值无效)")
                continue
            v = max(lo, min(hi, v))
        if cfg.get(k) != v:
            cfg[k] = v
            changed[k] = v
            dm_changed = True
        if k == "danmaku_history_size":
            n = int(v)
            state.danmaku_history_size = n
            if n > 0 and len(state.danmaku_history) > n:
                del state.danmaku_history[:len(state.danmaku_history) - n]

    # 4) 发送器热更新 + 落盘 + GUI 同步
    if dm_changed and app is not None:
        sender = getattr(app, "danmaku_sender", None)
        if sender is not None:
            try:
                sender.refresh(enabled=cfg.get("danmaku_send_enabled", True),
                               sends_per_min=cfg.get("danmaku_sends_per_min", 3),
                               min_gap_sec=cfg.get("danmaku_min_gap_sec", 3))
            except Exception:
                pass
    if changed:
        _persist(app)
        _sync_gui(app)
    return changed, ignored


# ── 能力自发现 ─────────────────────────────────────────────────────
def _font_hints():
    """字体可改的键 + 推荐值，让 AI 别瞎填。

    改字体只需 POST /api/settings，形如：
      {"style_config": {"lyric": {"font": "'SimHei', sans-serif"}}}
    中文名会被 fontlib 归一成英文族名（黑体 → SimHei），跨浏览器更稳。
    """
    try:
        import fontlib
        recommended = [{"css": fontlib.to_css(css_fam), "name": disp,
                        "available": fontlib.is_available(css_fam)}
                       for css_fam, disp, _al in fontlib.CURATED_FONTS]
    except Exception:
        recommended = []
    return {
        "writable_keys": {
            "mixed": ["font_lyric", "font_playing", "font_queue"],
            "lyric": ["font"], "playing": ["font"], "queue": ["font"],
        },
        "how": "POST /api/settings 传 {\"style_config\":{\"lyric\":{\"font\":\"'SimHei', sans-serif\"}}}",
        "recommended": recommended,
        "note": "也可直接填中文字体名（如 楷体），程序会归一成英文族名；"
                "字体必须装在跑 OBS 的那台电脑上才会生效，本机没装会回落但不报错。",
    }


def _capabilities():
    read = [
        ("GET", "/api/capabilities", "本清单：AI 一调就知道能干啥", {}),
        ("GET", "/api/state", "完整运行状态（版本/端口/播放/队列/计数）", {}),
        ("GET", "/api/queue", "点歌队列（处理中 + 待处理 + 已就绪）", {}),
        ("GET", "/api/danmaku", "直播间弹幕历史（环形缓存）",
         {"limit": "1..500，默认 50", "since_ts": "只返该时间戳之后的", "since_seq": "只返该游标之后的（推荐）"}),
        ("GET", "/api/settings", "全部可读设置 + 可写字段清单 + 红线说明", {}),
        ("GET", "/api/account", "B站/QQ音乐/抖音账号状态（不含任何凭据）", {}),
        ("GET", "/api/lyric", "当前歌词（活动行、行窗口、系统媒体信息）", {}),
        ("GET", "/api/log", "最近运行日志", {"tail": "1..500，默认 80"}),
        ("GET", "/api/events", "SSE 事件流（state/queue/danmaku/log/play/pause/lyric/settings）",
         {"token": "EventSource 无法设头，用 ?token= 传"}),
        ("GET", "/api/localsongs", "列出本地曲库（自己录的歌）：名字/大小/能否播", {}),
    ]
    write = [
        ("POST", "/api/send", "发 B站弹幕（继承限频）", {"text": "弹幕内容"}),
        ("POST", "/api/send/test", "同步真发一条测试弹幕并回中文结果", {"text": "可选，默认『点歌台测试弹幕』"}),
        ("POST", "/api/sender/reload", "用最新配置热刷新发弹幕发送器", {}),
        ("POST", "/api/queue/add", "点歌入队",
         {"song": "歌名", "user": "点歌人",
          "local_only": "true=只点本地曲库（等价观众发『本地点歌 歌名』），省略=走 QQ 音乐"}),
        ("POST", "/api/localsongs/upload",
         "把音频内容上传进本地曲库（只收 base64 内容，不收路径）",
         {"name": "歌名（不含扩展名）", "ext": "mp3|wav|flac|ogg",
          "data": "base64 编码的音频字节（≤200MB）"}),
        ("POST", "/api/localsongs/open", "打开本地曲库文件夹（不改任何文件）", {}),
        ("POST", "/api/queue/remove", "从队列删除", {"zone": "pending|ready", "index": "0 起"}),
        ("POST", "/api/queue/move", "换序/置顶", {"index": "0 起", "to": "0 起", "zone": "pending|ready，默认 ready"}),
        ("POST", "/api/queue/top", "把某项置顶（move 的快捷版）", {"index": "0 起", "zone": "pending|ready"}),
        ("POST", "/api/skip", "切歌", {}),
        ("POST", "/api/pause", "暂停/继续", {"on": "true 暂停 / false 继续"}),
        ("POST", "/api/pause/toggle", "按当前状态取反", {}),
        ("POST", "/api/settings", "改设置（白名单）",
         {"style_config": "嵌套样式补丁（mixed/lyric/playing/queue/global + 顶层标量）",
          "volume": "0~1 或 0~100 百分比（便捷键）",
          "audio_quality": "flac|default|中文档位名",
          "max_cache_files": "整数", "max_cache_size_mb": "整数",
          "danmaku_send_enabled": "bool", "danmaku_sends_per_min": "1..60",
          "danmaku_min_gap_sec": "0..60", "danmaku_history_size": "0..5000"}),
        ("POST", "/api/volume", "只改音量（settings 的便捷版）", {"value": "0~1 或 0~100"}),
        ("POST", "/api/quality", "只改首选音质", {"value": "flac|default|中文档位名"}),
    ]
    fmt = lambda rows: [{"method": m, "path": p, "desc": d, "params": q} for m, p, d, q in rows]
    allowed = _style_allowed_keys()
    return {
        "version": __import__("version").DISPLAY,
        "port": state.overlay_port,
        "auth": "所有端点都要 ?token= 或头 X-Api-Token；值取 config.json 的 api_token",
        "read": fmt(read),
        "write": fmt(write),
        "settings_writable": {
            "config_keys": sorted(_CONFIG_WRITE_KEYS.keys()),
            "style_sections": {s: sorted(allowed.get(s, [])) for s in _STYLE_SECTIONS},
            "style_scalars": list(_STYLE_SCALARS),
        },
        "fonts": _font_hints(),
        "settings_readonly": list(_CONFIG_READ_KEYS),
        "denied": list(_DENIED_KEYS),
        "security": [
            "只监听 127.0.0.1，外网不可达",
            "每个请求校验 token，未配置 api_token 时全部端点休眠返 403",
            "凭据(B站Cookie/QQ musickey)/文件路径/api_token 永不通过接口读写；房间号只读不可改；敏感字段传入会明确回执『拒不处理』",
            "不提供退出程序、扫码登录、删除文件的能力",
            ("本地曲库上传只允许写入曲库目录本身；扩展名限 " +
             "/".join(LOCAL_ALLOWED_EXTS) +
             "；单首 ≤%dMB；" % (LOCAL_MAX_BYTES // 1048576) +
             "重名自动加序号不覆盖；落盘后校验不是音频即删；绝不接受『源路径』参数（那等于开放整块硬盘）"),
            "弹幕采集与指令解析逻辑不经过本接口，不受影响",
        ],
    }


# ── 读接口（原有端点，语义原样保留）────────────────────────────────
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
    """兼容原 limit 语义；新增 since_ts / since_seq 游标，供 AI 增量读取。"""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    _assign_danmaku_seqs()
    try:
        limit = int(request.query.get("limit") or 50)
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 500))
    try:
        since_ts = float(request.query.get("since_ts") or 0)
    except ValueError:
        since_ts = 0.0
    try:
        since_seq = int(request.query.get("since_seq") or 0)
    except ValueError:
        since_seq = 0

    # 只把显式提供的游标纳入过滤；否则 since_ts 默认 0 会经 OR 让全部历史命中
    use_seq = since_seq > 0
    use_ts = since_ts > 0
    if use_seq or use_ts:
        def _match(m):
            ok_seq = _seq_of(m) > since_seq if use_seq else False
            ok_ts = float(m.get("ts") or 0) > since_ts if use_ts else False
            if use_seq and use_ts:
                return ok_seq or ok_ts
            return ok_seq if use_seq else ok_ts
        src = [m for m in state.danmaku_history if _match(m)]
    else:
        src = state.danmaku_history[-limit:]
    hist = src[-limit:]
    items = [_danmaku_item(m) for m in hist]
    next_ts = max([float(m.get("ts") or 0) for m in state.danmaku_history] or [since_ts])
    return _ok(count=len(hist), capacity=state.danmaku_history_size,
               items=items, since_ts=since_ts, since_seq=since_seq,
               next_since_ts=next_ts, next_since_seq=_danmaku_seq)


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


# ── 新读接口 ───────────────────────────────────────────────────────
async def handle_capabilities(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    return _ok(**_capabilities())


async def handle_settings_get(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    app = state.app
    cfg = app.config if app is not None else {}
    return _ok(
        settings=_settings_snapshot(),
        writable=_capabilities()["settings_writable"],
        readonly={k: cfg.get(k) for k in _CONFIG_READ_KEYS},
        denied=list(_DENIED_KEYS),
        note="POST 同路径即可按白名单改；凭据/路径/token/房间号不可读写",
    )


async def handle_account(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    app = state.app
    cfg = app.config if app is not None else {}
    sender = getattr(app, "danmaku_sender", None) if app else None
    bili = {
        "configured": bool(cfg.get("bili_cookie") and cfg.get("room_id")),
        "room_id": cfg.get("room_id", ""),
        "send_enabled": bool(cfg.get("danmaku_send_enabled", True)),
        "sends_per_min": getattr(sender, "sends_per_min", cfg.get("danmaku_sends_per_min", 3)),
        "min_gap_sec": getattr(sender, "min_gap_sec", cfg.get("danmaku_min_gap_sec", 3)),
        "sender_ready": bool(getattr(sender, "ready", lambda: False)()),
    }
    qq = {"logged_in": False, "uid": ""}
    try:
        import secretstore
        data = secretstore.read_json(settings.CREDENTIAL_FILE, default=None)
        if data and data.get("musicid") and data.get("musickey"):
            qq = {"logged_in": True, "uid": str(data.get("musicid"))}
    except Exception:
        pass
    return _ok(bilibili=bili, qqmusic=qq,
               douyin={"room_id": cfg.get("douyin_room_id", ""),
                       "status": state.douyin_status},
               version=__import__("version").DISPLAY, port=state.overlay_port)


async def handle_lyric(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    info = state.current_lyric_info or {}
    lines = info.get("lines") or []
    all_lines = info.get("all_lines") or []
    return _ok(
        song=(state.current_song or {}).get("display_name"),
        active_idx=info.get("active_idx", -1),
        lines=list(lines)[:20],
        all_lines_count=len(all_lines),
        active_lrc_lines=list(state.active_lrc_lines or [])[:20],
        system_playing=dict(state.system_media_info or {}),
    )


async def handle_log(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    _install_log_hook()
    try:
        tail = int(request.query.get("tail") or 80)
    except ValueError:
        tail = 80
    tail = max(1, min(tail, 500))
    rows = _LOG_RING[-tail:]
    return _ok(count=len(rows), total=_LOG_SEQ, tail=tail,
               items=[{"seq": r["seq"],
                       "time": time.strftime("%H:%M:%S", time.localtime(r["ts"])),
                       "ts": r["ts"], "text": r["text"]} for r in rows])


# ── SSE 事件流 ─────────────────────────────────────────────────────
def _snapshot():
    cur = state.current_song or {}
    info = state.current_lyric_info or {}
    return {
        "song": cur.get("display_name"),
        "mid": cur.get("mid"),
        "paused": bool(state.paused),
        "pause_intent": bool(state.pause_event.is_set()) if state.pause_event else False,
        "pending": [r.get("song_name") for r in state.pending_requests],
        "ready": [r.get("display_name") for r in state.playlist],
        "volume": state.style_config.get("global", {}).get("volume", 1.0),
        "audio_quality": state.style_config.get("audio_quality"),
        "system_media": (state.system_media_info or {}).get("title"),
        "active_idx": info.get("active_idx", -1),
        "douyin_status": state.douyin_status,
    }


def _diff(prev, cur):
    out = []
    if cur["song"] != prev["song"] or cur["mid"] != prev["mid"]:
        out.append(("play", {"song": cur["song"], "mid": cur["mid"]}))
    if cur["paused"] != prev["paused"] or cur["pause_intent"] != prev["pause_intent"]:
        out.append(("pause" if cur["paused"] else "resume",
                    {"paused": cur["paused"], "intent": cur["pause_intent"]}))
    if cur["pending"] != prev["pending"] or cur["ready"] != prev["ready"]:
        out.append(("queue", {"pending": cur["pending"], "ready": cur["ready"]}))
    if cur["volume"] != prev["volume"] or cur["audio_quality"] != prev["audio_quality"]:
        out.append(("settings", {"volume": cur["volume"],
                                 "audio_quality": cur["audio_quality"]}))
    if cur["active_idx"] != prev["active_idx"]:
        out.append(("lyric", {"active_idx": cur["active_idx"]}))
    if cur["system_media"] != prev["system_media"]:
        out.append(("system_media", {"title": cur["system_media"]}))
    if cur["douyin_status"] != prev["douyin_status"]:
        out.append(("platform", {"douyin_status": cur["douyin_status"]}))
    return out


async def _sse_write(r, event, data):
    await r.write(("event: %s\ndata: %s\n\n" %
                   (event, json.dumps(data, ensure_ascii=False))).encode("utf-8"))


async def handle_events(request):
    """SSE：1s 轮询 state 差分 + 弹幕/日志增量。不碰 danmaku.py、不碰 GUI。"""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    _install_log_hook()
    _assign_danmaku_seqs()
    r = web.StreamResponse(headers={
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
    await r.prepare(request)

    prev = _snapshot()
    last_seq = _danmaku_seq
    last_log = _LOG_SEQ
    last_ping = time.monotonic()
    try:
        await _sse_write(r, "hello", {
            "version": __import__("version").DISPLAY,
            "port": state.overlay_port,
            "since_seq": last_seq,
            "since_log": last_log,
            "state": prev,
        })
        while True:
            await asyncio.sleep(1.0)
            cur = _snapshot()
            for ev, data in _diff(prev, cur):
                await _sse_write(r, ev, data)
            prev = cur

            _assign_danmaku_seqs()
            if _danmaku_seq > last_seq:
                for m in state.danmaku_history:
                    s = _seq_of(m)
                    if s > last_seq:
                        await _sse_write(r, "danmaku", _danmaku_item(m))
                last_seq = _danmaku_seq

            if _LOG_SEQ > last_log:
                for row in _LOG_RING:
                    if row["seq"] > last_log:
                        await _sse_write(r, "log", {
                            "seq": row["seq"],
                            "time": time.strftime("%H:%M:%S", time.localtime(row["ts"])),
                            "text": row["text"],
                        })
                last_log = _LOG_SEQ

            if time.monotonic() - last_ping > 15:
                await r.write(b": ping\n\n")
                last_ping = time.monotonic()
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    return r


# ── 写接口（原有 7 个，语义原样保留）────────────────────────────────
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
    # v1.2.9：local_only=true 时走本地曲库（等价于观众发「本地点歌 歌名」）
    local_only = bool(body.get("local_only"))
    req = {"song_name": song, "uname": user,
           "platform": "api", "ts": time.time()}
    if local_only:
        req["local_only"] = True
    state.pending_requests.append(req)
    if local_only:
        return _ok(song=song, user=user, local_only=True,
                   note="已入本地曲库点歌队列（只在 my_songs 里找，不回退 QQ 音乐）")
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
    """原有：只在 ready 区换序；新增可选 zone=pending 支持待处理区。"""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    try:
        idx = int(body.get("index"))
        to = int(body.get("to", 0))
    except (TypeError, ValueError):
        return _err("需要 index 和 to（均 0 起）")
    zone = str(body.get("zone") or "ready")
    lst = state.pending_requests if zone == "pending" else state.playlist
    if not (0 <= idx < len(lst)):
        return _err("index 越界（当前 %d 项）" % len(lst))
    item = lst.pop(idx)
    to = max(0, min(to, len(lst)))
    lst.insert(to, item)
    return _ok(moved=item.get("display_name") or item.get("song_name"), to=to, zone=zone)


async def handle_skip(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    if not state.skip_event:
        return _err("播放引擎未就绪", 503)
    # v1.2.9：完全空闲时拒绝切歌，避免 skip_event 残留导致下次点歌被切掉
    if state.current_song is None and not state.playlist:
        return _err("当前没有在播的歌，无需切歌", 409)
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
    try:
        app.request_pause(on)
    except Exception as e:
        return _err("暂停操作失败：%s" % e, 500)
    return _ok(paused=on)


# ── 新写接口 ───────────────────────────────────────────────────────
async def handle_settings_post(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    app = state.app
    if app is None:
        return _err("程序未就绪", 503)
    body = await _body(request)
    if not isinstance(body, dict):
        return _err("请求体必须是 JSON 对象")
    try:
        changed, ignored = _settings_apply(body)
    except Exception as e:
        return _err("设置写入失败：%s" % e, 500)
    return _ok(changed=changed, ignored=ignored,
               settings=_settings_snapshot(),
               note="已即时生效并落盘；凭据/路径/token 不可写")


async def handle_volume(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    val = body.get("value", body.get("volume"))
    if val is None:
        return _err("缺少 value（0~1 或 0~100）")
    try:
        v = float(val)
    except (TypeError, ValueError):
        return _err("value 必须是数字")
    if v > 1.0:
        v = v / 100.0
    v = max(0.0, min(v, 1.0))
    changed, ignored = _settings_apply({"volume": v})
    return _ok(volume=v, changed=changed, ignored=ignored)


async def handle_quality(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    val = body.get("value", body.get("audio_quality"))
    if val is None:
        return _err("缺少 value（flac / default / 中文档位名）")
    q = _norm_quality(val)
    changed, ignored = _settings_apply({"audio_quality": q})
    return _ok(audio_quality=q, label=settings.QUALITY_UI_MAP.get(q),
               changed=changed, ignored=ignored)


async def handle_queue_top(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    try:
        idx = int(body.get("index"))
    except (TypeError, ValueError):
        return _err("缺少 index（0 起）")
    zone = str(body.get("zone") or "ready")
    lst = state.pending_requests if zone == "pending" else state.playlist
    if not (0 <= idx < len(lst)):
        return _err("index 越界（当前 %d 项）" % len(lst))
    item = lst.pop(idx)
    lst.insert(0, item)
    return _ok(topped=item.get("display_name") or item.get("song_name"), zone=zone)


async def handle_sender_reload(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    app = state.app
    if app is None:
        return _err("程序未就绪", 503)
    try:
        sender = app.reload_bili_sender()
    except Exception as e:
        return _err("刷新失败：%s" % e, 500)
    return _ok(reloaded=sender is not None,
               ready=bool(getattr(sender, "ready", lambda: False)()),
               sends_per_min=getattr(sender, "sends_per_min", None),
               min_gap_sec=getattr(sender, "min_gap_sec", None))


async def handle_send_test(request):
    """同步真发一条（GUI『测试发送』同一入口），用 to_thread 避开 loop 嵌套。"""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    body = await _body(request)
    text = str(body.get("text") or "点歌台测试弹幕").strip()[:40]
    app = state.app
    if app is None:
        return _err("程序未就绪", 503)
    try:
        sender = app.reload_bili_sender()
    except Exception:
        sender = getattr(app, "danmaku_sender", None)
    if sender is None:
        return _err("发弹幕组件未就绪（可能未登录 B站 或缺 Cookie）", 503)
    try:
        ok_send, msg = await asyncio.to_thread(sender.send_now, text)
    except Exception as e:
        return _err("测试发送异常：%s" % e, 500)
    return _ok(sent=bool(ok_send), message=msg, text=text)


async def handle_pause_toggle(request):
    ok, resp = _authorized(request)
    if not ok:
        return resp
    app = state.app
    if app is None:
        return _err("程序未就绪", 503)
    ev = state.pause_event
    on = not (ev.is_set() if ev else bool(state.paused))
    try:
        app.request_pause(on)
    except Exception as e:
        return _err("暂停操作失败：%s" % e, 500)
    return _ok(paused=on)


# ── v1.2.9：本地曲库读写（AI 可列出、可上传音频、可打开文件夹）─────
async def handle_localsongs(request):
    """列出本地曲库。返回每首歌的名字/大小/能否播，AI 一看就知道有啥。"""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    try:
        import locallib
    except Exception as e:
        return _err("本地曲库模块不可用：%s" % e, 500)
    folder = _local_dir()
    songs = locallib.list_songs(folder)
    items = []
    for s in songs:
        playable, why = locallib.check_playable(s["path"])
        items.append({"name": s["name"], "ext": s["ext"],
                      "size": os.path.getsize(s["path"]) if os.path.exists(s["path"]) else 0,
                      "playable": playable, "why": why})
    return _ok(folder=folder, count=len(items), items=items,
               note="观众发『本地点歌 歌名』就可以点到这些歌")


async def handle_localsongs_upload(request):
    """把 AI 传来的音频字节写进本地曲库（方案 A：只收内容，不收路径）。

    请求体：{"name": "夏天", "ext": "mp3", "data": "<base64>"}
    安全边界：只写 my_songs/；扩展名白名单；单文件 200MB 上限；
    文件名强制清洗（挡路径分隔符与 ..）；重名不覆盖；
    落盘后用 check_playable 校验，不是真音频就删掉并报错。
    """
    ok, resp = _authorized(request)
    if not ok:
        return resp
    try:
        import locallib
    except Exception as e:
        return _err("本地曲库模块不可用：%s" % e, 500)

    body = await _body(request)
    if not isinstance(body, dict):
        return _err("请求体必须是 JSON 对象")

    name, why = _safe_song_name(body.get("name"))
    if not name:
        return _err(why or "歌名不合法")

    ext = str(body.get("ext") or "").strip().lower()
    if not ext.startswith("."):
        ext = "." + ext if ext else ""
    if ext not in LOCAL_ALLOWED_EXTS:
        return _err("只接受 %s，收到 %r" % ("/".join(LOCAL_ALLOWED_EXTS), ext or "(空)"))

    raw_b64 = body.get("data")
    if not raw_b64 or not isinstance(raw_b64, str):
        return _err("缺少 data（base64 编码的音频内容）")
    # 预判大小，避免解码一个超大字符串把内存撑爆
    approx = len(raw_b64) * 3 // 4
    if approx > LOCAL_MAX_BYTES:
        return _err("文件太大（约 %.0fMB），单首上限 %dMB"
                    % (approx / 1048576, LOCAL_MAX_BYTES // 1048576), 413)
    try:
        blob = base64.b64decode(raw_b64, validate=False)
    except Exception:
        return _err("data 不是合法的 base64")
    if len(blob) < LOCAL_MIN_BYTES:
        return _err("音频太小（%d 字节），至少 %dKB" % (len(blob), LOCAL_MIN_BYTES // 1024))
    if len(blob) > LOCAL_MAX_BYTES:
        return _err("文件太大，单首上限 %dMB" % (LOCAL_MAX_BYTES // 1048576), 413)

    folder = _local_dir()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        return _err("曲库目录不可写：%s" % e, 500)

    # 不覆盖：同名同扩展名已存在就加 (2)/(3)… 后缀
    target = os.path.join(folder, name + ext)
    if os.path.exists(target):
        for i in range(2, 200):
            cand = os.path.join(folder, "%s(%d)%s" % (name, i, ext))
            if not os.path.exists(cand):
                target = cand
                break
        else:
            return _err("同名文件太多，请换个歌名")

    # 双保险：确认最终路径确实落在曲库目录内（防任何拼接绕过）
    real_folder = os.path.realpath(folder)
    real_target = os.path.realpath(target)
    if not real_target.startswith(real_folder + os.sep):
        return _err("目标路径越界，拒绝写入", 400)

    try:
        with open(target, "wb") as f:
            f.write(blob)
    except OSError as e:
        return _err("写入失败：%s" % e, 500)

    # 写完立刻校验是不是真音频；不是就删掉，别污染曲库
    playable, why2 = locallib.check_playable(target)
    if not playable:
        try:
            os.remove(target)
        except OSError:
            pass
        return _err("写入的内容不是可播放的音频（%s），已删除" % (why2 or "无法解码"))

    app = state.app
    if app is not None:
        try:
            app.log("📥 接口上传本地曲库：《%s》（%.1fMB）" % (
                os.path.splitext(os.path.basename(target))[0], len(blob) / 1048576))
        except Exception:
            pass
    return _ok(file=os.path.basename(target), folder=folder,
               size=len(blob), playable=True,
               note="观众发『本地点歌 %s』即可点到" % os.path.splitext(os.path.basename(target))[0])


async def handle_localsongs_open(request):
    """打开本地曲库文件夹（跟 GUI 那个按钮同一动作，不修改任何文件）。"""
    ok, resp = _authorized(request)
    if not ok:
        return resp
    app = state.app
    if app is None:
        return _err("程序未就绪", 503)
    try:
        app.open_local_songs_folder()
    except Exception as e:
        return _err("打开文件夹失败：%s" % e, 500)
    return _ok(folder=_local_dir(), note="已在资源管理器中打开")


# ── 路由注册 ───────────────────────────────────────────────────────
def register(web_app):
    """把全部端点挂到 OBS 那个 aiohttp 应用上（同一个端口，省得再开服务）。"""
    # 能力自发现 / 读
    web_app.router.add_get("/api/capabilities", handle_capabilities)
    web_app.router.add_get("/api/state", handle_state)
    web_app.router.add_get("/api/danmaku", handle_danmaku)
    web_app.router.add_get("/api/queue", handle_queue)
    web_app.router.add_get("/api/settings", handle_settings_get)
    web_app.router.add_get("/api/account", handle_account)
    web_app.router.add_get("/api/lyric", handle_lyric)
    web_app.router.add_get("/api/log", handle_log)
    web_app.router.add_get("/api/events", handle_events)
    # 写（原有）
    web_app.router.add_post("/api/send", handle_send)
    web_app.router.add_post("/api/queue/add", handle_queue_add)
    web_app.router.add_post("/api/queue/remove", handle_queue_remove)
    web_app.router.add_post("/api/queue/move", handle_queue_move)
    web_app.router.add_post("/api/skip", handle_skip)
    web_app.router.add_post("/api/pause", handle_pause)
    # 写（新增）
    web_app.router.add_post("/api/settings", handle_settings_post)
    web_app.router.add_post("/api/volume", handle_volume)
    web_app.router.add_post("/api/quality", handle_quality)
    web_app.router.add_post("/api/queue/top", handle_queue_top)
    web_app.router.add_post("/api/sender/reload", handle_sender_reload)
    web_app.router.add_post("/api/send/test", handle_send_test)
    web_app.router.add_post("/api/pause/toggle", handle_pause_toggle)
    # v1.2.9：本地曲库
    web_app.router.add_get("/api/localsongs", handle_localsongs)
    web_app.router.add_post("/api/localsongs/upload", handle_localsongs_upload)
    web_app.router.add_post("/api/localsongs/open", handle_localsongs_open)
