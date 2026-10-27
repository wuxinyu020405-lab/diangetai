# -*- coding: utf-8 -*-
"""第5步单测：配额记账（日上限150 / 连5败熔断10分钟 / 冷却只挡下载不挡缓存）。"""
import asyncio
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, "点歌台拆分")
import settings
import musiclib
import state
import danmaku

passed, failed = 0, 0


def case(name, cond, detail=""):
    global passed, failed
    passed += cond; failed += (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


tmp = tempfile.mkdtemp(prefix="dgc_s5_")
settings.CACHE_DIR = tmp
musiclib.QUOTA_FILE = os.path.join(tmp, "quota_state.json")


def reset_state(date="2026-10-28", downloaded=0, fail_streak=0, cooldown=0.0):
    state.quota_state.update({"date": date, "downloaded": downloaded,
                              "fail_streak": fail_streak, "cooldown_until": cooldown})


print("═══ A. 阈值常量 = 拍板值 ═══")
case("日上限150", settings.QUOTA_DAILY_CAP == 150)
case("连败5", settings.QUOTA_FAIL_STREAK == 5)
case("冷却10分钟", settings.QUOTA_COOLDOWN_SEC == 600)

print("═══ B. 正常放行 / 达上限拦截 ═══")
reset_state(downloaded=149)
case("149 放行", musiclib.quota_block_reason() is None)
musiclib.quota_note_success()
case("成功一笔后=150", state.quota_state["downloaded"] == 150)
case("150 拦截", musiclib.quota_block_reason() is not None)
case("拦截语含上限", "上限" in musiclib.quota_block_reason())

print("═══ C. 冷却期拦截与倒计时 ═══")
reset_state(downloaded=1, cooldown=time.time() + 600)
msg = musiclib.quota_block_reason()
case("冷却中拦截", msg and "熔断冷却" in msg, msg)
case("剩余约9-10分钟", "9分" in msg or "10分" in msg, msg)
reset_state(cooldown=time.time() - 1)   # 已过期
case("冷却到期放行", musiclib.quota_block_reason() is None)

print("═══ D. 连败计数与拉闸 ═══")
reset_state()
trips = []
for i in range(6):
    r = musiclib.quota_note_failure("quota")
    trips.append(bool(r))
case("前4次不拉闸", trips[:4] == [False] * 4)
case("第5次拉闸", trips[4] is True)
case("第6次重新计数(冷却期内已重置streak)", trips[5] is False)
case("cooldown_until 已写入约10分钟后",
     590 < state.quota_state["cooldown_until"] - time.time() <= 601)
case("拉闸后重新从1计(第6次失败又开始新一轮)", state.quota_state["fail_streak"] == 1)

print("═══ E. 非配额失败不推向熔断，且清零连败 ═══")
reset_state()
musiclib.quota_note_failure("quota")
musiclib.quota_note_failure("quota")
case("累计2", state.quota_state["fail_streak"] == 2)
musiclib.quota_note_failure("all_failed")   # 冷门歌无版权
case("无版权清零连败(不冤枉队列)", state.quota_state["fail_streak"] == 0)
case("未拉闸", state.quota_state["cooldown_until"] == 0.0)

print("═══ F. 成功后连败清零 ═══")
reset_state(fail_streak=4)
musiclib.quota_note_success()
case("成功→streak=0", state.quota_state["fail_streak"] == 0)

print("═══ G. 记账持久化与跨日归零 ═══")
reset_state(date="2026-10-27", downloaded=120, fail_streak=3, cooldown=time.time() + 300)
musiclib.save_quota_state()
case("文件已写", os.path.exists(musiclib.QUOTA_FILE))
st = musiclib.load_quota_state()   # 今天≠2026-10-27 → 全部归零
case("跨日 downloaded=0", st["downloaded"] == 0)
case("跨日 fail_streak=0", st["fail_streak"] == 0)
case("跨日冷却也清", st["cooldown_until"] == 0.0)
# 同日回读
state.quota_state.update({"date": "1999-01-01"})
musiclib.save_quota_state()
musiclib.load_quota_state()
case("损坏容忍：无效内容不崩", True)
with open(musiclib.QUOTA_FILE, "w", encoding="utf-8") as f:
    f.write("{坏JSON")
try:
    musiclib.load_quota_state()
    case("坏文件容错", True)
except Exception as e:
    case("坏文件容错", False, str(e))

print("═══ H. process_one_request 集成：闸门生效与结论 ═══")


class FakeCred:
    musicid = 1
    musickey = "x"


state.qq_credential = FakeCred()


class FakeApp:
    def __init__(self):
        self.logs = []
        self.dl_called = 0
        self.last_download_reason = "downloaded"

    def log(self, m):
        self.logs.append(m)

    async def download_audio_qq(self, song_info, retries=3):
        self.dl_called += 1
        return ("path", song_info["display_name"], song_info["mid"])


orig_search = danmaku.search_song


async def search_ok(song_name, app_instance, retry=2):
    return ("MIDH", "冷却歌", "s", None)


danmaku.search_song = search_ok


def fresh_pl():
    state.playlist.clear(); state.pending_requests.clear()


# 冷却期：无缓存 → 直接 quota_blocked，不调下载
fresh_pl()
reset_state(cooldown=time.time() + 600)
app = FakeApp()
res = asyncio.run(danmaku.process_one_request({"song_name": "x", "uname": "u"}, app))
case("冷却期结论=quota_blocked", res == "quota_blocked")
case("下载零调用(快速失败)", app.dl_called == 0)
case("不入列", len(state.playlist) == 0)

# 冷却期：有缓存 → 照样就绪（下载熔断≠播放熔断）
p = os.path.join(tmp, "MIDH_default.mp3")
with open(p, "wb") as f:
    f.write(b"x" * 200_000)
fresh_pl()
res = asyncio.run(danmaku.process_one_request({"song_name": "x", "uname": "u"}, app))
case("冷却中缓存命中仍就绪", res == "cached" and len(state.playlist) == 1)

# 达上限 → 同样 blocked；放行后正常走下载
fresh_pl(); os.remove(p)
reset_state(downloaded=150)
res = asyncio.run(danmaku.process_one_request({"song_name": "x", "uname": "u"}, app))
case("上限结论=quota_blocked", res == "quota_blocked")
fresh_pl()
reset_state(downloaded=0)
res = asyncio.run(danmaku.process_one_request({"song_name": "x", "uname": "u"}, app))
case("放行后正常下载入列", res == "downloaded" and len(state.playlist) == 1)
case("成功已记账 +1", state.quota_state["downloaded"] == 1)

danmaku.search_song = orig_search
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
