"""
弹幕：B站直播 handler、点歌指令解析与入队
"""

import asyncio
import blivedm
from qqmusic_api import Client, Credential
import musiclib
import state

class BiliHandler(blivedm.BaseHandler):
    def __init__(self, app_instance):
        super().__init__(); self.app = app_instance
    def _on_danmaku(self, client, message):
        text = message.msg.strip()
        uname = getattr(message, 'uname', '') or '神秘观众'
        if text == "切歌":
            if state.skip_event and not state.skip_event.is_set(): self.app.log("⏭️ 收到【切歌】指令！"); self.app.root.after(0, lambda: state.skip_event.set())
            return
        if text.startswith("点歌"):
            song_name = text.replace("点歌", "").strip()
            if song_name: 
                self.app.log(f"收到点歌请求: {song_name} - {uname}")
                asyncio.create_task(search_and_add(song_name, uname, self.app))

async def search_and_add(song_name, uname, app_instance, retry=2):
    if not state.qq_credential: return
    try:
        search_res = None
        for _ in range(retry):
            try:
                async with Client(credential=state.qq_credential) as client:
                    search_res = await client.search.search_by_type(keyword=song_name, num=1)
                    if search_res: break
            except Exception as e:
                app_instance.log(f"[WARN] 歌曲搜索失败: {e}")
            app_instance.log(f"搜索第{_+1}/{retry}次尝试...")
            await asyncio.sleep(1)

        song_mid, real_name, singer_name, _ = musiclib.extract_song_info(search_res)
        if not song_mid:
            app_instance.log(f"❌ 没找到《{song_name}》或解析失败")
            return

        display_name = f"{real_name} {singer_name}"

        state.playlist.append({"name": real_name, "display_name": display_name, "mid": song_mid, "requester": uname})
        app_instance.log(f"✅ 已加入队列: {display_name}-{uname}")
        app_instance.predownload_song(song_mid, display_name)

    except Exception as e:
        app_instance.log(f"❌ 搜索出错 (检查网络/代理): {e}")
