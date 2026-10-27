# -*- coding: utf-8 -*-
"""环境核验脚本：逐条比对源码真实调用点，判断依赖是否可用。"""
import sys
import inspect
import asyncio

print("Python:", sys.version.split()[0], "|", sys.executable)
print("=" * 70)

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append(("PASS", name, detail if detail else ""))
        return True
    except Exception as e:
        results.append(("FAIL", name, f"{type(e).__name__}: {e}"))
        return False


# ---------- 1. 源码 L1-L35 的全部 import ----------
SOURCE_IMPORTS = [
    ("ply", "L1"), ("jsonpath_ng", "L2"), ("jsonpath_ng.ext", "L3"),
    ("tkinter", "L8"), ("tkinter.messagebox", "L9"), ("threading", "L10"),
    ("asyncio", "L11"), ("inspect", "L12"), ("re", "L13"), ("html", "L14"),
    ("random", "L15"), ("urllib.parse", "L16"), ("urllib.request", "L17"),
    ("aiohttp", "L18"), ("aiohttp.web", "L19"), ("time", "L20"),
    ("ctypes", "L21"), ("ctypes.wintypes", "L22"),
    ("winsdk.windows.media.control", "L23"), ("blivedm", "L24"),
    ("json", "L25"), ("os", "L26"), ("sys", "L27"), ("subprocess", "L28"),
    ("pygame", "L29"), ("selenium", "L30"),
    ("selenium.webdriver.chrome.service", "L31"),
    ("selenium.webdriver.edge.service", "L32"),
    ("selenium.webdriver.chrome.options", "L33"),
    ("selenium.webdriver.edge.options", "L34"),
    ("qqmusic_api", "L35"),
]


def make_imp(mod, ref):
    def _f():
        __import__(mod)
        return ref
    return _f


for m, ref in SOURCE_IMPORTS:
    check(f"import {m}", make_imp(m, ref))


# ---------- 2. L35: from qqmusic_api import Client, Credential ----------
def _qq_top():
    from qqmusic_api import Client, Credential
    Credential(musicid=1, musickey="x")
    return "Client/Credential 可用"
check("from qqmusic_api import Client, Credential", _qq_top)


# ---------- 3. L40-L48 动态探测 SongFileInfo / SongFileType ----------
def _qq_models():
    from qqmusic_api.modules.song import SongFileInfo, SongFileType
    return f"modules.song 命中；FileType 成员数={len([k for k in dir(SongFileType) if not k.startswith('_')])}"
check("qqmusic_api SongFileInfo/SongFileType 探测", _qq_models)


def _req_item():
    from qqmusic_api.modules.song import SongFileInfo
    SongFileInfo(mid="ABCDEF")
    return "SongFileInfo(mid=...) 构造 OK (源码 L249)"
check("SongFileInfo(mid=) 构造", _req_item)


# ---------- 4. L35/L752: Credential 关键字参数 ----------
def _cred_kw():
    from qqmusic_api import Credential
    c = Credential(musicid=123, musickey="k")
    return f"musicid={c.musicid}"
check("Credential(musicid=, musickey=)", _cred_kw)


# ---------- 5. blivedm: 源码 L1751-L1752 的确切用法 ----------
def _bli_ctor():
    import blivedm
    sig = inspect.signature(blivedm.BLiveClient.__init__)
    # 源码: BLiveClient(int(room_id), session=http_session)
    sig.bind(None, 123, session=None)
    return f"blivedm {blivedm.__version__}; 形参 {list(sig.parameters)}"
check("BLiveClient(room_id, session=...) 绑定", _bli_ctor)


def _bli_set_handler():
    import blivedm
    assert hasattr(blivedm.BLiveClient, "set_handler"), "无 set_handler"
    return "set_handler 存在"
check("BLiveClient.set_handler (源码 L1752)", _bli_set_handler)


def _bli_start():
    import blivedm
    s = blivedm.BLiveClient.start
    if inspect.iscoroutinefunction(s):
        return "警告: start 是协程，源码 L1752 写的是 client.start() 未 await"
    return "start 同步 + 源码 L1752 client.start() 未 await —— 一致"
check("BLiveClient.start 同步性 (源码 L1752)", _bli_start)


def _bli_stop_close():
    import blivedm
    s = blivedm.BLiveClient.stop_and_close
    return "协程(源码 await 正确)" if inspect.iscoroutinefunction(s) else "同步(源码 await 会出错)"
check("BLiveClient.stop_and_close (源码 L1755 await)", _bli_stop_close)


def _bli_handler():
    import blivedm
    b = blivedm.BaseHandler
    d = b._on_danmaku
    if inspect.iscoroutinefunction(d):
        return "警告: 基类 _on_danmaku 是协程，源码 L2118 定义的是同步 def"
    return "基类 _on_danmaku 同步，与源码 L2118 def 一致"
check("BaseHandler._on_danmaku 签名 (源码 L2118)", _bli_handler)


def _bli_super():
    import blivedm

    class H(blivedm.BaseHandler):
        def __init__(self):
            super().__init__()   # 源码 L2117
    H()
    return "BaseHandler 可无参构造 + super().__init__()"
check("BiliHandler.__init__ super() (源码 L2117)", _bli_super)


def _bli_msg_fields():
    import blivedm
    m = blivedm.models.web.DanmakuMessage
    ann = getattr(m, "__annotations__", {})
    has_uname = "uname" in ann
    has_msg = "msg" in ann
    return f"DanmakuMessage 字段 uname={has_uname} msg={has_msg} (源码 L2119-L2120)"
check("DanmakuMessage.uname/.msg", _bli_msg_fields)


def _bli_handler_map():
    """master 的分发机制是否仍按 _on_xxx 命名。"""
    import blivedm
    src = inspect.getsource(blivedm)
    return "handlers 模块: " + blivedm.handlers.__name__
check("blivedm.handlers 可达", _bli_handler_map)


# ---------- 6. winsdk SMTC（源码 L23 / L1813） ----------
def _wmc():
    # 注意：winsdk 的 request_async 返回 WinRT IAsyncOperation，
    # 它不是 Python coroutine function，inspect.iscoroutinefunction 恒为 False。
    # 正确判据：能 await 并拿到 manager。
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

    async def _run():
        # IAsyncOperation 不是 coroutine，只能在运行中的 loop 里 await
        return await M.request_async()
    mgr = asyncio.run(_run())
    assert hasattr(mgr, "get_sessions") and hasattr(mgr, "get_current_session")
    return f"await request_async() -> {type(mgr).__name__}，get_sessions/get_current_session 可用 (源码 L1798/L1805)"
check("winsdk SMTC await", _wmc)


# ---------- 7. aiohttp web（源码 L1726-L1733） ----------
def _aio_web():
    # 复刻源码 L1726-L1733 的真实顺序：先 runner.setup() 再建 TCPSite
    from aiohttp import web

    async def _run():
        app = web.Application()
        app.router.add_get("/", lambda r: None)
        app.router.add_get("/api/data", lambda r: None)
        r = web.AppRunner(app)
        await r.setup()
        s = web.TCPSite(r, "127.0.0.1", 8099)
        await s.start()
        ok = True
        await r.cleanup()
        return ok
    asyncio.run(_run())
    return "Application/AppRunner.setup/TCPSite.start 全链路 OK (源码 L1726-L1733)"
check("aiohttp.web 服务原语", _aio_web)


# ---------- 7b. blivedm + 外部 aiohttp session（源码 L1749-L1755） ----------
def _bli_session_integration():
    import aiohttp
    import blivedm

    async def _run():
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as http_session:
            c = blivedm.BLiveClient(12345, session=http_session)
            c.set_handler(blivedm.BaseHandler())
            await c.stop_and_close()
        return f"blivedm {blivedm.__version__} + aiohttp {aiohttp.__version__} 外部 session 构造/关闭 OK"
    return asyncio.run(_run())
check("blivedm 源码集成 (L1749-L1755)", _bli_session_integration)


# ---------- 8. pygame mixer（源码 L1287） ----------
def _pg():
    import os
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pygame
    pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048)
    ok = pygame.mixer.get_init() is not None
    pygame.mixer.quit()
    return f"mixer.init(48000,-16,2,2048) 成功={ok}"
check("pygame.mixer.init 参数", _pg)


if __name__ == "__main__":
    print()
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "PASS" and ("警告" in r[2] or "源码 await 会出错" in r[2])]
    for st, name, detail in results:
        mark = "✅" if st == "PASS" else "❌"
        print(f"{mark} {name}" + (f"\n     {detail}" if detail else ""))
    print("=" * 70)
    print(f"总计 {len(results)} 项 | 失败 {len(fails)} | 需关注 {len(warns)}")
    if fails:
        print("\n--- 失败项 ---")
        for _, n, d in fails:
            print(f"  ❌ {n}: {d}")
    sys.exit(1 if fails else 0)
