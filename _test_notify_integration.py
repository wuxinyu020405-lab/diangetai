# -*- coding: utf-8 -*-
"""#1 失败回执集成测试：假 sender 记录调用，假搜索失败走 not_found 路径。
用法: python -X utf8 _test_notify_integration.py"""
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
import state, danmaku

results = []
def ck(name, ok, d=""):
    results.append(ok); print(("OK  " if ok else "FAIL"), name, d)

class FakeSender:
    def __init__(self): self.sent = []
    def send(self, t): self.sent.append(t); return None

class App:
    def __init__(self, sender): self.danmaku_sender = sender; self.logs = []
    def log(self, m): self.logs.append(m)

async def main():
    # ① 未登录QQ音乐 → 回执"还没登录"
    state.qq_credential = None
    s = FakeSender(); app = App(s)
    r = await danmaku.process_one_request({"song_name": "晴天", "uname": "阿伟"}, app)
    ck("① no_credential 回执", r == "no_credential" and len(s.sent) == 1 and "还没登录" in s.sent[0], s.sent)

    # ② 搜索无结果 → 回执"没搜到"（打桩 search_song）
    state.qq_credential = object()
    async def fake_search(name, app_instance, retry=2): return None
    old = danmaku.search_song; danmaku.search_song = fake_search
    s2 = FakeSender(); app2 = App(s2)
    r = await danmaku.process_one_request({"song_name": "不存在的歌xyz", "uname": "小明"}, app2)
    danmaku.search_song = old
    ck("② not_found 回执", r == "not_found" and "没搜到" in (s2.sent[0] if s2.sent else ""), s2.sent)

    # ③ 无 sender（GUI 未初始化完）→ 不炸，正常返回结论
    app3 = App(None); app3.danmaku_sender = None
    danmaku.search_song = fake_search
    r = await danmaku.process_one_request({"song_name": "x", "uname": "u"}, app3)
    danmaku.search_song = old
    ck("③ sender=None 静默跳过", r == "not_found")

    # ④ sender.send 抛异常 → 被 notify 兜住，结论照常返回
    class Boom:
        def send(self, t): raise RuntimeError("网络炸了")
    app4 = App(Boom())
    danmaku.search_song = fake_search
    r = await danmaku.process_one_request({"song_name": "x", "uname": "u"}, app4)
    danmaku.search_song = old
    ck("④ sender 异常不影响结论", r == "not_found" and any("回执异常" in m for m in app4.logs))

    # ⑤ 回执文案 ≤40 字（B站上限，sender 内部也会截，双保险）
    ck("⑤ 文案不超长", all(len(t) <= 40 for t in s.sent + s2.sent), [len(t) for t in s.sent + s2.sent])

asyncio.run(main())
bad = results.count(False)
print("结论:", "✅ #1 集成回归 %d/%d 全过" % (len(results), len(results)) if bad == 0 else "❌ 失败 %d 项" % bad)
sys.exit(0 if bad == 0 else 1)
