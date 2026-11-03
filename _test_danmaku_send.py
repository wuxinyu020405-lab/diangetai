# -*- coding: utf-8 -*-
"""#8 发弹幕模块离线回归：限频闸、休眠条件、40字截断、投递不抛异常。
不真发网络请求（_post 打桩）。用法: python -X utf8 _test_danmaku_send.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
import bilibili_send as bs

results = []
def ck(name, ok, d=""):
    results.append(ok); print(("OK  " if ok else "FAIL"), name, d)

CK = "SESSDATA=abc; bili_jct=csrf123; DedeUserID=9"

# ① 正常投递（打桩 _post 记录调用）
sent = []
s = bs.RateLimitedSender("123", CK)
s._post = lambda t: sent.append(t)          # 打桩（协程属性：send 走无循环线程分支）
r = s.send("点歌失败测试")
ck("① 正常投递返回 None", r is None, "r=%r" % r)
time.sleep(0.4)
ck("① 实际发出", sent == ["点歌失败测试"], "sent=%s" % sent)

# ② 最小间隔拦截
r2 = s.send("第二条太快")
ck("② 间隔<3s 被拦", isinstance(r2, str) and "间隔" in r2, "r=%r" % r2)

# ③ 每分钟上限
s2 = bs.RateLimitedSender("123", CK)
s2._post = lambda t: None
s2._last = 0.0
blocked = []
for i in range(5):
    s2._last = 0.0                          # 绕过间隔闸，专测每分钟闸
    r = s2.send("x%d" % i)
    if isinstance(r, str) and "每分钟" in r:
        blocked.append(i)
ck("③ 第4条起触发每分钟上限", blocked and blocked[0] == bs.SENDS_PER_MIN, "blocked=%s cap=%d" % (blocked, bs.SENDS_PER_MIN))

# ④ 缺 Cookie / 缺房间号 → 休眠原因
s3 = bs.RateLimitedSender("123", "SESSDATA=only")
ck("④ 缺 bili_jct 拦截", "Cookie" in (s3.send("x") or ""), )
s4 = bs.RateLimitedSender("", CK)
ck("④ 缺房间号拦截", "房间号" in (s4.send("x") or ""))
s5 = bs.RateLimitedSender("123", CK, enabled=False)
ck("④ enabled=False 拦截", "未启用" in (s5.send("x") or ""))

# ⑤ 40 字截断（B站上限）
s6 = bs.RateLimitedSender("123", CK)
got = []
s6._post = lambda t: got.append(t)
long_text = "开" * 60
s6._last = 0.0
s6.send(long_text)
time.sleep(0.3)
ck("⑤ 截断到40字", got and len(got[0]) == 40, "len=%d" % (len(got[0]) if got else -1))

# ⑥ 空内容
s7 = bs.RateLimitedSender("123", CK)
ck("⑥ 空内容被拒", (s7.send("   ") or "") == "空内容")

bad = results.count(False)
print("结论:", "✅ #8 模块回归 %d/%d 全过" % (len(results), len(results)) if bad == 0 else "❌ 失败 %d 项" % bad)
sys.exit(0 if bad == 0 else 1)
