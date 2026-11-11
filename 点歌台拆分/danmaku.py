"""
弹幕：直播平台 handler、点歌指令解析与串行点歌处理
需求1+3（改造后）：弹幕只入待处理队列；单 worker 串行处理，
本首结论明确（就绪/失败/跳过）才处理下一首；下载成功或缓存命中才进 playlist。

v1.2·抖音接入：指令解析抽成平台无关的 handle_message（B站 blivedm 与
抖音 provider 共用同一入口，行为完全一致）。
"""

import asyncio
import os
import blivedm
from qqmusic_api import Client, Credential
import locallib
import musiclib
import settings
import state


def handle_message(app, text, uname, platform="bilibili"):
    """平台无关的指令入口：切歌/暂停/继续/点歌。
    两平台行为对齐的关键——任何 provider 收到 chat 都调这里。"""
    text = (text or "").strip()
    if not text:
        return
    tag = "" if platform == "bilibili" else "[%s] " % platform
    # v1.2.8：显式本地命令——只查 my_songs/，不回退 QQ 音乐。
    # 必须排在普通「点歌」之前，否则会被 startswith("点歌") 误吞。
    if text.startswith("本地点歌"):
        local_name = text.replace("本地点歌", "", 1).strip()
        if local_name:
            app.log("%s收到本地点歌请求: %s - %s" % (tag, local_name, uname))
            import time as _t
            state.pending_requests.append({"song_name": local_name, "uname": uname,
                                           "platform": platform, "local_only": True,
                                           "ts": _t.time()})
            return
    if text == "切歌":
        # v1.2.9：完全空闲（没在播、队列也空）时不置位 skip_event。
        # 否则意图会残留 —— 下次点歌刚开始播就被切掉（用户报的「自动切一次歌」）。
        if state.current_song is None and not state.playlist:
            app.log("%sℹ️ 当前没有在播的歌，忽略【切歌】" % tag)
            return
        if state.skip_event and not state.skip_event.is_set():
            app.log("%s⏭️ 收到【切歌】指令！" % tag)
            app.root.after(0, lambda: state.skip_event.set())
        return
    # v1.1·N1：暂停/继续（精确匹配，防"暂停一下好吗"这类聊天误触；
    # 与切歌同款 root.after 编组到 Tk 线程，复用 GUI 按钮同一入口保证行为一致）
    if text == "暂停":
        app.root.after(0, lambda: app.request_pause(True)); return
    if text == "继续":
        app.root.after(0, lambda: app.request_pause(False)); return
    if text.startswith("点歌"):
        song_name = text.replace("点歌", "", 1).strip()
        if song_name:
            app.log("%s收到点歌请求: %s - %s" % (tag, song_name, uname))
            # 需求3：不再并发起 task，只入待处理队列，由 song_request_worker 串行消费
            # v1.2.2·队列管理页：带 ts=入队时刻（等待时长展示用）
            import time as _t
            state.pending_requests.append({"song_name": song_name, "uname": uname,
                                           "platform": platform, "ts": _t.time()})


class BiliHandler(blivedm.BaseHandler):
    def __init__(self, app_instance):
        super().__init__(); self.app = app_instance
    def _on_danmaku(self, client, message):
        handle_message(self.app, message.msg,
                       getattr(message, 'uname', '') or '神秘观众', "bilibili")


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
    platform = req.get("platform", "bilibili")

    def notify(text):
        """v1.1·#1 失败回执：只回失败、成功不打扰主播弹幕区；限频在 sender 内部，
        被拦/无配置都静默，绝不影响点歌主流程。
        v1.2·修串台：回执通道是 B站专用（danmaku_sender 绑死 B站房间+Cookie），
        抖音等非B站平台的失败只记主播日志、不发弹幕——抖音发弹幕接口未接入，
        若误发会把「抖音观众小明失败」的消息串到 B站直播间去。"""
        if platform != "bilibili":
            return
        sender = getattr(app_instance, "danmaku_sender", None)
        if sender is not None:
            try:
                blocked = sender.send(text)
                if blocked:
                    app_instance.log("[回执未发] %s" % blocked)
            except Exception as e:
                app_instance.log("[WARN] 回执异常: %s" % e)

    # ── v1.2.8：本地曲库短路（显式命令「本地点歌」专用，不回退 QQ 音乐）──
    # 必须排在 QQ 登录检查之前：本地歌不需要 QQ 登录、不占配额、不联网络。
    if req.get("local_only"):
        cfg = getattr(app_instance, "config", {}) or {}
        folder = cfg.get("local_songs_dir") or settings.LOCAL_SONGS_DIR
        try:
            thr = float(cfg.get("local_match_threshold", locallib.DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            thr = locallib.DEFAULT_THRESHOLD
        result, reason = locallib.find_best(song_name, folder, threshold=thr)
        if reason == "ok":
            # v1.2.8：入列前先确认这文件真能播。改了后缀（如 m4a 伪装成 .mp3）、
            # 下载不完整、编码不受支持的文件，pygame 会加载失败；不先验就会进队列
            # 后被静默跳过，观众以为点歌没反应。这里验不过就直接算点歌失败。
            playable, why = locallib.check_playable(result["path"])
            if not playable:
                msg = "点歌失败：《%s》这个文件放不出来（%s）" % (result["name"][:12], why)
                app_instance.log("❌ 本地点歌失败: 《%s》-%s 原因: %s（文件 %s）"
                                 % (result["name"], uname, why, result["path"]))
                notify("@%s %s" % (uname, msg))
                return "local_unplayable"
            entry = locallib.make_entry(result, uname, platform="local")
            state.playlist.append(entry)
            app_instance.log("✅ 就绪[本地曲库 %s 相似度%.2f]: 《%s》-%s（文件 %s）"
                             % (platform, result["score"], result["name"], uname,
                                os.path.basename(result["path"])))
            return "local"
        msg = {
            "empty_library": "本地曲库还是空的，请先把我录的歌放进 my_songs 文件夹",
            "no_match": "本地曲库里没找到《%s》" % song_name[:12],
            "ambiguous": "本地曲库里《%s》有几首都像，换个说法再点" % song_name[:12],
        }.get(reason, "本地曲库匹配失败")
        app_instance.log("❌ 本地点歌未入列: 《%s》-%s 原因: %s" % (song_name, uname, msg))
        notify("@%s %s" % (uname, msg))
        return "local_not_found"

    if not state.qq_credential:
        app_instance.log(f"❌ 《{song_name}》 未登录QQ音乐，无法处理 (请求人:{uname})")
        notify("@%s 主播还没登录QQ音乐，暂时点不了歌" % uname)
        return "no_credential"

    found = await search_song(song_name, app_instance)
    if not found:
        app_instance.log(f"❌ 《{song_name}》 没找到或解析失败 → 不入列 (请求人:{uname})")
        notify("@%s 没搜到《%s》" % (uname, song_name[:12]))
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
        notify("@%s 点歌排队中（%s）" % (uname, "今日额度用完" if "上限" in blocked else "冷却中，稍后再试"))
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
        "budget": "超出单首时间预算(可能网络慢/服务端拖)",
    }.get(reason, reason or "未知原因")
    app_instance.log(f"❌ 未入列: 《{display_name}》-{uname} 原因: {why}")
    notify("@%s 《%s》点歌失败：%s" % (uname, real_name[:10], why.split("，")[0].split("(")[0]))
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
            state.processing_request = req   # v1.2.2·队列管理页：正在下载的那条保持可见
            try:
                await process_one_request(req, app_instance)
            finally:
                state.processing_request = None
        except Exception as e:
            app_instance.log(f"[WARN] 点歌处理循环异常: {type(e).__name__}: {e}")
            await asyncio.sleep(1)
