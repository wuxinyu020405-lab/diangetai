"""
弹幕：B站直播 handler、点歌指令解析与串行点歌处理
需求1+3（改造后）：弹幕只入待处理队列；单 worker 串行处理，
本首结论明确（就绪/失败/跳过）才处理下一首；下载成功或缓存命中才进 playlist。
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
                # 需求3：不再并发起 task，只入待处理队列，由 song_request_worker 串行消费
                state.pending_requests.append({"song_name": song_name, "uname": uname})


async def search_song(song_name, app_instance, retry=2):
    """搜索最可能的 1 首。返回 (mid, name, singer, flac_size) 或 None。"""
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
    mid, real_name, singer_name, _, flac_size = musiclib.extract_song_info(search_res)
    if not mid: return None
    return mid, real_name, singer_name, flac_size


async def process_one_request(req, app_instance):
    """一首点歌的完整结论：就绪(入 playlist) / 失败(不入)。返回结论字符串。"""
    song_name = req["song_name"]; uname = req["uname"]
    if not state.qq_credential:
        app_instance.log(f"❌ 《{song_name}》 未登录QQ音乐，无法处理 (请求人:{uname})")
        return "no_credential"

    found = await search_song(song_name, app_instance)
    if not found:
        app_instance.log(f"❌ 《{song_name}》 没找到或解析失败 → 不入列 (请求人:{uname})")
        return "not_found"
    song_mid, real_name, singer_name, flac_size = found
    display_name = f"{real_name} {singer_name}"

    # 需求2·本地优先：缓存任意档命中 → 就绪，不下载（熔断期间同样可用）
    if musiclib.find_any_cached_file(song_mid):
        state.playlist.append({"name": real_name, "display_name": display_name, "mid": song_mid, "requester": uname})
        app_instance.log(f"✅ 就绪[本地缓存]: {display_name}-{uname}")
        return "cached"

    # 第5步·配额闸门：冷却中/达当日上限 → 不再发起下载（失败快、不入列）
    blocked = musiclib.quota_block_reason()
    if blocked:
        app_instance.log(f"⏸ 《{display_name}》暂不处理（{blocked}）→ 不入列 (请求人:{uname})")
        return "quota_blocked"

    # 需求1：下载成功才入列
    app_instance.log(f"⏬ 开始处理下载: {display_name}-{uname}")
    song_info = {"mid": song_mid, "display_name": display_name, "flac_size": flac_size}
    try:
        file_path, _, _ = await app_instance.download_audio_qq(song_info)
    except Exception as e:
        file_path = None
        app_instance.log(f"❌ 下载异常: {type(e).__name__}: {e}")
    reason = getattr(app_instance, "last_download_reason", None)

    if file_path:
        musiclib.quota_note_success()   # 第5步：真实下载 +1，连败清零
        state.playlist.append({"name": real_name, "display_name": display_name, "mid": song_mid, "requester": uname})
        app_instance.log(f"✅ 就绪[下载完成]: {display_name}-{uname}")
        return "downloaded"
    # 失败：不入列（需求1）+ 单行结论（需求9/17.4）
    tripped = musiclib.quota_note_failure(reason)   # 第5步：配额类失败计连败，达阈值拉闸
    if tripped:
        app_instance.log(f"🚨 {tripped}")
    why = {
        "quota": "配额/风控限制，建议稍后再试",
        "device_limited": "播放设备受限，请重新扫码登录QQ音乐",
        "no_credential": "未登录或凭证失效，请重新扫码登录",
        "all_failed": "无版权或全部音质获取失败",
    }.get(reason, reason or "未知原因")
    app_instance.log(f"❌ 未入列: 《{display_name}》-{uname} 原因: {why}")
    return reason or "failed"


async def song_request_worker(app_instance):
    """需求3：串行消费 pending_requests。本首出明确结论才下一首。"""
    while True:
        try:
            if not state.pending_requests:
                await asyncio.sleep(0.3)
                continue
            # 简单快照取队首（asyncio 单线程，无并发写风险）
            req = state.pending_requests.pop(0)
            await process_one_request(req, app_instance)
        except Exception as e:
            app_instance.log(f"[WARN] 点歌处理循环异常: {type(e).__name__}: {e}")
            await asyncio.sleep(1)
