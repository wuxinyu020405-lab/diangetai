# -*- coding: utf-8 -*-
"""第7步单测：.part 半包隔离 / 流式与预算的静态接线 / 预热只做一次 / 预算超时路径。"""
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
import mainapp

passed, failed = 0, 0


def case(name, cond, detail=""):
    global passed, failed
    passed += cond; failed += (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


tmp = tempfile.mkdtemp(prefix="dgc_s7_")
settings.CACHE_DIR = tmp

print("═══ A. .part 文件对缓存检索不可见（半包不会被当就绪）═══")
MID = "00Half07"
with open(os.path.join(tmp, f"{MID}_default.mp3.part"), "wb") as f:
    f.write(b"x" * 300_000)          # 即使超过100KB也不算命中
case("find_any_cached_file 忽略 .part", musiclib.find_any_cached_file(MID) is None)
case("find_cached_file_for_tier 忽略 .part",
     musiclib.find_cached_file_for_tier(MID, "default") is None)
with open(os.path.join(tmp, f"{MID}_default.mp3"), "wb") as f:
    f.write(b"y" * 200_000)
case("正式文件命中(共存时)", musiclib.find_any_cached_file(MID) is not None)

print("═══ B. 流式写盘与预算的静态接线 ═══")
src = open("点歌台拆分/mainapp.py", encoding="utf-8").read()
case("不再整块 resp.read()", "resp.read()" not in src)
case("逐块写盘", "iter_chunked(64 * 1024)" in src)
case("原子改名", "os.replace(tmp_path, file_path)" in src)
case("403外的旧式 timeout=30 换成 ClientTimeout", "timeout=aiohttp.ClientTimeout(total=30, connect=10)" in src)
case("预算常量入 settings", hasattr(settings, "SONG_DOWNLOAD_BUDGET_SEC"))
case("MIN_CACHE_BYTES 判据", musiclib.MIN_CACHE_BYTES == 100 * 1024)

print("═══ C. #4 预热已删除 + 预算超时快速放弃（全程零真实网络）═══")


class FakeCred:
    musicid = 1
    musickey = "x"


state.qq_credential = FakeCred()


class Stub:
    audio_backend = "none"
    last_download_reason = None
    logs = []

    def log(self, m):
        self.logs.append(m)


s = Stub()
orig_budget = settings.SONG_DOWNLOAD_BUDGET_SEC
try:
    settings.SONG_DOWNLOAD_BUDGET_SEC = -5   # 预算已耗尽（模拟极慢网络后的超时态）
    t0 = time.time()
    res = asyncio.run(mainapp.MusicApp.download_audio_qq(
        s, {"mid": "MID_Z", "display_name": "超时歌", "flac_size": None}))
    dt1 = time.time() - t0
    case("超时返回None", res[0] is None)
    case("归因=budget", s.last_download_reason == "budget")
    case("#4 预热已删：首轮也立即放弃(无1.5s等待)", dt1 < 0.5, f"{dt1:.2f}s")
    case("#4 不再设置预热标记", not hasattr(s, "_download_warmed"))
    # 二次行为一致
    t0 = time.time()
    res = asyncio.run(mainapp.MusicApp.download_audio_qq(
        s, {"mid": "MID_Z2", "display_name": "超时歌2", "flac_size": None}))
    dt2 = time.time() - t0
    case("二次同样快速", dt2 < 0.5, f"{dt2:.2f}s")
    case("#4 日志不再出现'预热'字样", not any("预热" in m for m in s.logs))
finally:
    settings.SONG_DOWNLOAD_BUDGET_SEC = orig_budget

print("═══ D. 缓存命中不受预算影响（#4 后已无预热概念）═══")
with open(os.path.join(tmp, "MIDC_flac.flac"), "wb") as f:
    f.write(b"z" * 200_000)
try:
    settings.SONG_DOWNLOAD_BUDGET_SEC = -5
    t0 = time.time()
    res = asyncio.run(mainapp.MusicApp.download_audio_qq(
        s, {"mid": "MIDC", "display_name": "有缓存", "flac_size": None}))
    dt = time.time() - t0
    case("预算耗尽仍秒取缓存", res[0] and res[0].endswith("MIDC_flac.flac") and dt < 0.2, f"{dt:.2f}s")
    case("归因=cached", s.last_download_reason == "cached")
finally:
    settings.SONG_DOWNLOAD_BUDGET_SEC = orig_budget

print("═══ E. budget 不推熔断（慢≠配额墙）═══")
case("budget 不在配额类失败集合", "budget" not in musiclib._QUOTA_LIKE_FAILS)
case("quota 在", "quota" in musiclib._QUOTA_LIKE_FAILS)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
