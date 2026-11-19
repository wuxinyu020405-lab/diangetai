# -*- coding: utf-8 -*-
"""asyncio 主循环与直播监听：B站弹幕 / 抖音消息 / OBS 服务。

R-23 从 mainapp.py 搬出来的，逻辑一行没改。"""

import asyncio

import aiohttp
from aiohttp import web

import blivedm
import danmaku
import musiclib
import overlay
import settings
import state


class ListenerMixin:
    """R-23：从 mainapp.MusicApp 拆出的方法块，靠多重继承合回同一个类。"""

    def start_async_loop(self):
        # 窗口模式(console=False)下线程崩溃的 traceback 无处显示，用户只能看到
        # "正在启动 OBS 服务器..." 就没了下文。这里兜住异常：写进 GUI 日志 + 落盘。
        try:
            self.loop = asyncio.new_event_loop(); asyncio.set_event_loop(self.loop); self.loop.run_until_complete(self.main_async())
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                self.log(f"❌ 后台服务启动失败: {type(e).__name__}: {e}（详见 启动日志.txt）")
            except Exception:
                pass
            try:
                settings.save_startup_log(tb, "启动日志.txt")
            except Exception:
                pass

    async def main_async(self):
        global skip_event; state.skip_event = asyncio.Event()
        state.pause_event = asyncio.Event()   # v1.1·N1
        self.log("正在启动 OBS 服务器...")
        web_app = web.Application()
        web_app.router.add_get('/', overlay.handle_index)
        web_app.router.add_get('/lyric', overlay.handle_index)
        web_app.router.add_get('/playing', overlay.handle_index)
        web_app.router.add_get('/queue', overlay.handle_index)
        web_app.router.add_get('/api/data', overlay.handle_api)

        runner = web.AppRunner(web_app); await runner.setup()
        # 端口自动顺延：8080 被别的程序占着时，依次试 8081~8090，
        # 并把实际端口写回 state.overlay_port 供 GUI 复制挂件地址用。
        bound = None
        for port in range(8080, 8091):
            try:
                site = web.TCPSite(runner, '127.0.0.1', port); await site.start(); bound = port; break
            except OSError as e:
                import errno as _errno
                if e.errno in (_errno.EADDRINUSE, 10048):   # 10048 = Windows 端口被占
                    self.log(f"[INFO] 端口 {port} 已被占用，尝试下一个...")
                    continue
                self.log(f"❌ OBS 服务器启动失败: {type(e).__name__}: {e}"); break
        if bound is None:
            self.log("❌ 8080~8090 全部不可用，OBS 挂件无法启动（点歌播放不受影响）")
        else:
            state.overlay_port = bound
            if bound != 8080:
                self.log(f"⚠️ 默认端口 8080 被占用，已自动改用 {bound}，OBS 源地址请用 http://127.0.0.1:{bound}/")
            self.log("✅ OBS 网页服务器已启动")
        musiclib.load_quota_state()   # 第5步：跨重启恢复当日配额记账（跨日自动归零）
        self.init_audio_engine()

        asyncio.create_task(self.music_player_worker()); asyncio.create_task(self.system_media_worker()); asyncio.create_task(self.lyric_sync_worker())
        # 需求3：点歌串行处理 worker（pending_requests → 逐首出结论）
        asyncio.create_task(danmaku.song_request_worker(self))
        
        cookies = {}
        bili_cookie = self.config.get('bili_cookie', '')
        if not bili_cookie:
            self.log("❌ 缺少 B站 Cookie，请在顶部点击重新登录！")
        else:
            for item in bili_cookie.split(';'):
                if '=' in item: k, v = item.split('=', 1); cookies[k.strip()] = v.strip()
        # v1.1·#8/#1：点歌失败回执通道（带限频）。房间号/ Cookie 齐了才启用。
        import bilibili_send
        self.danmaku_sender = bilibili_send.RateLimitedSender(
            self.config.get('room_id', ''), bili_cookie, log=self.log,
            enabled=bool(self.config.get('danmaku_send_enabled', True)),
            sends_per_min=self.config.get('danmaku_sends_per_min', 3),
            min_gap_sec=self.config.get('danmaku_min_gap_sec', 3))
        self.log("📣 弹幕发送：%s，限频 %s 条/分钟、间隔 %ss" % (
            "已就绪" if self.danmaku_sender.ready() else "未登录/缺 Cookie",
            self.danmaku_sender.sends_per_min, int(self.danmaku_sender.min_gap_sec)))
                
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Referer": f"https://live.bilibili.com/{self.config.get('room_id', '')}", "Origin": "https://live.bilibili.com"}
        
        async with aiohttp.ClientSession(cookies=cookies, headers=headers, trust_env=False) as http_session:
            self._bili_session = http_session
            # v1.2.8：B站监听改成可热重启（登录后不用重启程序）。
            # 连接持有在实例上，restart_bili_listener() 可随时拆掉重建。
            await self._start_bili_listener()
            # v1.2·抖音双平台：配置了 douyin_room_id 就并起一路匿名弹幕
            dy_room = str(self.config.get('douyin_room_id', '') or '').strip()
            if dy_room:
                import queue as _q
                from live_providers.douyin import DouyinProvider
                self._dy_q = _q.Queue()
                self._dy = DouyinProvider(dy_room, log=self.log)
                asyncio.create_task(self._dy.run(self._dy_q))
                asyncio.create_task(self._douyin_dispatcher())
                self.log("🎙️ 抖音通道启动中（房间 %s，匿名）" % dy_room)
            try:
                while True: await asyncio.sleep(3600)
            finally:
                await self._stop_bili_listener()
                self._bili_session = None

    async def _start_bili_listener(self):
        """(重)建 B站弹幕监听。必须在 asyncio loop 线程里调用。

        为什么要有这个方法：原来 BLiveClient 只在 main_async 里建一次，
        登录后拿到的新 Cookie/房间号根本不会被它看到，必须重启程序才收得到弹幕。
        拆出来之后，restart_bili_listener() 可以在登录成功时拆旧建新。
        """
        room = str(self.config.get("room_id") or "").strip()
        if not room:
            self.log("❌ 缺少 B站 房间号，请点击顶部登录 B站！")
            self._bili_client = None
            self._bili_room = None
            return False
        try:
            session = getattr(self, "_bili_session", None)
            if session is None:
                self.log("⚠️ 弹幕监听重建失败：HTTP 会话未就绪")
                return False
            # v1.2.8：cookie 每次从 config 现取，不再用启动时那份
            cookie_str = str(self.config.get("bili_cookie") or "")
            cookies = {}
            for item in cookie_str.split(";"):
                if "=" in item:
                    k, v = item.split("=", 1)
                    cookies[k.strip()] = v.strip()
            client = blivedm.BLiveClient(int(room), session=session)
            # 把最新 Cookie 灌进共享会话（blivedm 用这个 session 的 cookie 鉴权）
            try:
                session.cookie_jar.update_cookies(cookies)
            except Exception as e:
                self.log(f"⚠️ 更新 Cookie 到弹幕会话失败（可能影响身份相关弹幕）: {e}")
            client.set_handler(danmaku.BiliHandler(self))
            client.start()
            self._bili_client = client
            self._bili_room = room
            self.log(f"✅ 连接 B 站成功！等待弹幕中...（房间 {room}）")
            return True
        except Exception as e:
            self.log(f"❌ 连接 B 站失败: {type(e).__name__}: {e}")
            self._bili_client = None
            return False

    async def _stop_bili_listener(self):
        """停掉现有 B站监听（尽力而为，异常不影响后续重建）。"""
        client = getattr(self, "_bili_client", None)
        self._bili_client = None
        if client is None:
            return
        try:
            await client.stop_and_close()
        except Exception as e:
            print(f"[WARN] 停止 B站弹幕连接异常(已忽略): {e}")

    async def _restart_bili_listener_async(self):
        """拆旧建新。加锁防重入（连点两次登录不会建出两条连接）。"""
        if getattr(self, "_bili_restarting", False):
            self.log("ℹ️ 弹幕监听正在重连中，稍候…")
            return
        self._bili_restarting = True
        try:
            old_room = getattr(self, "_bili_room", None)
            await self._stop_bili_listener()
            ok = await self._start_bili_listener()
            new_room = getattr(self, "_bili_room", None)
            if ok:
                if old_room and new_room and old_room != new_room:
                    self.log(f"🔁 弹幕监听已切换房间：{old_room} → {new_room}")
                else:
                    self.log("🔁 弹幕监听已重连（新的登录信息已生效，无需重启程序）")
            else:
                self.log("⚠️ 弹幕监听重连失败，可点「重连弹幕」重试")
        finally:
            self._bili_restarting = False

    def restart_bili_listener(self, notify_ui=False):
        """对外入口（可从 Tk 线程调用）：把重连投递到 asyncio loop 线程执行。"""
        loop = getattr(self, "loop", None)
        if loop is None or loop.is_closed():
            self.log("⚠️ 播放引擎还没就绪，弹幕监听稍后再重连")
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._restart_bili_listener_async(), loop)
            return True
        except Exception as e:
            self.log(f"❌ 弹幕监听重连投递失败: {e}")
            return False

    def gui_restart_bili_listener(self):
        """GUI『重连弹幕』按钮：手动兜底，帮用户看到结果。"""
        if self.restart_bili_listener():
            try:
                self.log("🔄 正在重连 B站弹幕监听…")
            except Exception:
                pass

    async def _douyin_dispatcher(self):
        """抖音消息队列 → 统一指令入口 handle_message（与 B 站同一行为）。
        chat 进指令解析；member/social/gift 只记日志（v1 不做进场播报）。"""
        import queue as _q
        while True:
            try:
                msg = await asyncio.to_thread(self._dy_q.get, True, 1)
            except _q.Empty:
                await asyncio.sleep(0.2)
                continue
            except Exception:
                await asyncio.sleep(1)
                continue
            try:
                if msg.type == "chat":
                    danmaku.handle_message(self, msg.text, msg.uname, "douyin")
                elif msg.type == "gift":
                    self.log("🎁 [douyin] %s 送 %s" % (msg.uname, msg.extra))
                elif msg.type == "member":
                    self.log("🚪 [douyin] %s 进入直播间" % msg.uname)
            except Exception as e:
                print(f"[WARN] 抖音消息分发异常: {e}")
