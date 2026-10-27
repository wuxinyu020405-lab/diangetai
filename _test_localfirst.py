# -*- coding: utf-8 -*-
"""第3步单测：find_any_cached_file 判据 + 下载入口本地优先（置于一切网络动作之前）。"""
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

passed, failed = 0, 0


def case(name, cond, detail=""):
    global passed, failed
    passed += cond; failed += (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


tmp = tempfile.mkdtemp(prefix="dgc_test_")
orig_cache = settings.CACHE_DIR
settings.CACHE_DIR = tmp


def mkfile(name, kb=200):
    p = os.path.join(tmp, name)
    with open(p, "wb") as f:
        f.write(b"x" * kb * 1024)
    return p


MID = "00TestMid01"
print("═══ A. find_any_cached_file ═══")
case("无文件 → None", musiclib.find_any_cached_file(MID) is None)
case("mid=None → None", musiclib.find_any_cached_file(None) is None)

# 只有 default 档 → 命中（本地优先核心：有任一档就不下载）
mkfile(f"{MID}_default.mp3")
got = musiclib.find_any_cached_file(MID)
case("仅 default 档也命中", got and got.endswith(f"{MID}_default.mp3"))

# 加 flac 档 → 优先返回 flac（可预期行为）
mkfile(f"{MID}_flac.flac", 800)
got = musiclib.find_any_cached_file(MID)
case("两档都有 → flac 优先", got and got.endswith(f"{MID}_flac.flac"))

# 旧命名不识别（第十二节决定2）
mkfile(f"{MID}_hires.flac")
mkfile(f"{MID}.mp3")           # legacy 无档位后缀
mkfile(f"{MID}_mp3_320.mp3")
os.remove(os.path.join(tmp, f"{MID}_flac.flac"))
got = musiclib.find_any_cached_file(MID)
case("旧命名(_hires/legacy/_mp3_320)不识别", got and got.endswith("default.mp3"))

# <100KB 残片 → 删除且不算命中
MID2 = "00Frag02"
p = mkfile(f"{MID2}_default.mp3", 50)
got = musiclib.find_any_cached_file(MID2)
case("残片不命中", got is None)
case("残片被删除", not os.path.exists(p))

print("═══ B. download_audio_qq 本地优先·零网络 ═══")
# 造一个假 credential 对象，只验证"缓存命中时函数在预热/CDN之前就返回"
class FakeCred:
    musicid = 1
    musickey = "x"


state.qq_credential = FakeCred()
MID3 = "00Cached03"
mkfile(f"{MID3}_default.mp3")
app_holder = {}


async def run_dl():
    # 借用真实方法：构造最小 stub
    import mainapp

    class Stub:
        log = lambda self, m: None
        last_download_reason = None
        download_tasks = {}

        async def control_local_music(self, pause=True):
            pass

    s = Stub()
    app_holder["s"] = s
    t0 = time.time()
    res = await mainapp.MusicApp.download_audio_qq(
        s, {"mid": MID3, "display_name": "测试歌", "flac_size": None})
    return res, time.time() - t0


res, dt = asyncio.run(run_dl())
case("缓存命中返回该文件", res[0] and res[0].endswith("default.mp3"))
case("归因=cached", app_holder["s"].last_download_reason == "cached")
case("零网络零预热(耗时<0.5s)", dt < 0.5, f"{dt:.2f}s")

print("═══ C. 缓存优先于凭证（定稿语义：老缓存无凭证也能播） ═══")
state.qq_credential = None


async def run_dl2():
    import mainapp

    class Stub:
        log = lambda self, m: None
        last_download_reason = None
        download_tasks = {}

    s = Stub()
    res = await mainapp.MusicApp.download_audio_qq(
        s, {"mid": MID3, "display_name": "测试歌", "flac_size": None})
    s2 = Stub()
    res2 = await mainapp.MusicApp.download_audio_qq(
        s2, {"mid": "00NotExist99", "display_name": "无缓存歌", "flac_size": None})
    return s, res, s2, res2


s, res, s2, res2 = asyncio.run(run_dl2())
case("有缓存+无凭证 → 仍返回缓存", res[0] and res[0].endswith("default.mp3"))
case("归因=cached（优先路径）", s.last_download_reason == "cached")
case("无缓存+无凭证 → (None,None,None)", res2 == (None, None, None))
case("归因=no_credential", s2.last_download_reason == "no_credential")

settings.CACHE_DIR = orig_cache
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
