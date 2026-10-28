# -*- coding: utf-8 -*-
"""第4步单测：串行点歌管线（弹幕→pending→处理→就绪入列 / 失败不入列）。"""
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, "点歌台拆分")
import state
import settings
import musiclib
import danmaku

passed, failed = 0, 0


def case(name, cond, detail=""):
    global passed, failed
    passed += cond; failed += (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


tmp = tempfile.mkdtemp(prefix="dgc_s4_")
settings.CACHE_DIR = tmp
# 测试隔离：配额记账写临时文件，绝不污染真实 quota_state.json
musiclib.QUOTA_FILE = os.path.join(tmp, "quota.json")
state.quota_state.update({"date": "2099-01-01", "downloaded": 0, "fail_streak": 0, "cooldown_until": 0.0})


class FakeRoot:
    def after(self, ms, fn):
        fn()


class FakeApp:
    def __init__(self):
        self.logs = []
        self.root = FakeRoot()
        self.dl_result = (None, "", "")
        self.dl_reason = "all_failed"

    def log(self, m):
        self.logs.append(m)

    async def download_audio_qq(self, song_info, retries=3):
        self.last_download_reason = self.dl_reason
        return self.dl_result


class FakeCred:
    musicid = 1
    musickey = "x"


state.qq_credential = FakeCred()

print("═══ A. 弹幕只入待处理队列，不再直接进列表 ═══")
state.pending_requests.clear(); state.playlist.clear()
app = FakeApp()
h = danmaku.BiliHandler(app)


class Msg:
    msg = "点歌 晴天"
    uname = "观众甲"


h._on_danmaku(None, Msg())
case("进 pending_requests", len(state.pending_requests) == 1)
case("playlist 未变(还没处理)", len(state.playlist) == 0)
case("请求内容完整", state.pending_requests[0] == {"song_name": "晴天", "uname": "观众甲"})

print("═══ B. 搜索失败 → 不入列 ═══")
orig_search = danmaku.search_song


async def search_fail(song_name, app_instance, retry=2):
    return None


danmaku.search_song = search_fail
res = asyncio.run(danmaku.process_one_request(state.pending_requests[0], app))
case("结论=not_found", res == "not_found")
case("playlist 仍空（需求1核心）", len(state.playlist) == 0)

print("═══ C. 本地优先：缓存命中 → 就绪入列，不下载 ═══")


async def search_ok(song_name, app_instance, retry=2):
    return ("MID01", "晴天", "周杰伦", None)


danmaku.search_song = search_ok
with open(os.path.join(tmp, "MID01_default.mp3"), "wb") as f:
    f.write(b"x" * 200_000)
app.dl_result = (None, "", ""); app.dl_reason = "all_failed"  # 若被调用就失败
res = asyncio.run(danmaku.process_one_request({"song_name": "晴天", "uname": "观众甲"}, app))
case("结论=cached", res == "cached")
case("入列且只 1 项", len(state.playlist) == 1 and state.playlist[0]["mid"] == "MID01")
case("字段结构完整", set(state.playlist[0]) == {"name", "display_name", "mid", "requester"})

print("═══ D. 下载成功 → 就绪入列（缓存中无此歌，强制走下载分支） ═══")
state.pending_requests.clear(); state.playlist.clear()
# 注意：不能预先在 CACHE_DIR 放 MID02 文件，否则会被需求2"本地优先"先命中
#（上一版测试正是如此自污染 → 证明本地优先确实在下载之前执行）
app.dl_result = (os.path.join(tmp, "outside", "MID02_flac.flac"), "歌B MID", "MID02")
app.dl_reason = "downloaded"


async def search_ok2(song_name, app_instance, retry=2):
    return ("MID02", "歌B", "歌手B", 100)


danmaku.search_song = search_ok2
res = asyncio.run(danmaku.process_one_request({"song_name": "歌B", "uname": "乙"}, app))
case("结论=downloaded", res == "downloaded")
case("入列", len(state.playlist) == 1 and state.playlist[0]["mid"] == "MID02")

print("═══ E. 下载失败 → 不入列 + 归因日志 ═══")
state.playlist.clear()
app.dl_result = (None, "", ""); app.dl_reason = "quota"
res = asyncio.run(danmaku.process_one_request({"song_name": "歌B", "uname": "乙"}, app))
case("结论=quota", res == "quota")
case("playlist 空（失败不显示）", len(state.playlist) == 0)
case("日志含配额提示", any("配额" in l for l in app.logs), str(app.logs[-2:]))

print("═══ F. 串行：两首请求按序处理，无并发交错 ═══")
danmaku.search_song = orig_search  # 先还回原函数（下面自定义计数版）
order = []


async def search_counted(song_name, app_instance, retry=2):
    order.append(f"start:{song_name}")
    await asyncio.sleep(0.05)
    order.append(f"end:{song_name}")
    return ("M_" + song_name, song_name, "s", None)


danmaku.search_song = search_counted
state.pending_requests.clear(); state.playlist.clear()
app.dl_reason = "downloaded"


async def dl_ok(song_info, retries=3):
    app.last_download_reason = "downloaded"
    return ("fake_path", song_info["display_name"], song_info["mid"])


app.download_audio_qq = dl_ok
state.pending_requests.append({"song_name": "A", "uname": "u1"})
state.pending_requests.append({"song_name": "B", "uname": "u2"})


async def run_worker():
    t = asyncio.create_task(danmaku.song_request_worker(app))
    await asyncio.sleep(0.5)
    t.cancel()


asyncio.run(run_worker())
case("处理顺序 start:A→end:A→start:B→end:B",
     order == ["start:A", "end:A", "start:B", "end:B"], str(order))
case("两首均就绪入列", len(state.playlist) == 2)
case("pending 已清空", len(state.pending_requests) == 0)

print("═══ G. 未登录 → 明确失败结论 ═══")
state.qq_credential = None
res = asyncio.run(danmaku.process_one_request({"song_name": "X", "uname": "u"}, app))
case("结论=no_credential", res == "no_credential")
case("不入列", all(x["mid"] != "X" for x in state.playlist))

danmaku.search_song = orig_search
settings.CACHE_DIR = tmp.replace(tmp, os.path.join(os.getcwd(), "music_cache"))
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
