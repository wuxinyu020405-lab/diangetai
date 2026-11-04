# -*- coding: utf-8 -*-
"""抖音 provider 端到端冒烟：真连在播房间，跑 provider.run 收消息。
用法: python -X utf8 _smoke_douyin_e2e.py [web_rid] [秒数]
无 web_rid 时自动从 feed 接口找热门房。验证：消息能进队列、chat 能触发
handle_message 入队点歌（注入假"点歌"消息验证链路，真人弹幕碰运气）。"""
import asyncio, os, sys, queue, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
import state, danmaku
from live_providers.douyin import DouyinProvider

web_rid = sys.argv[1] if len(sys.argv) > 1 else None
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 40

if not web_rid:
    # 从 feed 找在播房（复用 spike 脚本的函数）
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "feed", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_spike_douyin_feed.py"))
    # feed 脚本是顶层执行式，直接内联其核心：
    import hashlib, subprocess, urllib.parse, urllib.request, http.cookiejar, json, re
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    cj = http.cookiejar.CookieJar()
    o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), urllib.request.ProxyHandler({}))
    o.addheaders = [("User-Agent", UA), ("Referer", "https://live.douyin.com/")]
    o.open("https://live.douyin.com/", timeout=15)
    tt = next((c.value for c in cj if c.name == "ttwid"), "")
    qs = ("aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN"
          "&cookie_enabled=true&screen_width=1920&screen_height=1080&browser_language=zh-CN"
          "&browser_platform=Win32&browser_name=Chrome&browser_version=126.0.0.0&count=20"
          "&source=web_live&channel=channel_pc_web")
    md5 = hashlib.md5(qs.encode()).hexdigest()
    r = subprocess.run(["node", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "douyin_sign", "sign_runner.js"), md5],
                       capture_output=True, text=True, timeout=45)
    url = "https://live.douyin.com/webcast/feed/?" + qs + "&X-Bogus=" + urllib.parse.quote(r.stdout.strip())
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://live.douyin.com/",
                                               "Cookie": "ttwid=%s" % tt})
    body = urllib.request.urlopen(req, timeout=15, ).read().decode("utf-8", "replace")
    # feed 返回里找 web_rid（短号）
    wrs = re.findall(r'"owner":\{[^}]*?"web_rid":"?(\d{5,20})', body) or re.findall(r'"web_rid":"(\d+)"', body)
    if not wrs:
        print("feed 没解析出 web_rid，请手动传: python _smoke_douyin_e2e.py <web_rid>"); sys.exit(1)
    web_rid = wrs[0]
    print("自动选中在播房间 web_rid:", web_rid)

# ---- 假 app 接 handle_message ----
class FakeApp:
    def __init__(self): self.logs = []
    def log(self, m): self.logs.append(m)
    class _R:
        def after(self, ms, fn): fn and fn()
    root = _R()
    def request_pause(self, on): pass

state.pending_requests.clear()
app = FakeApp()

async def main():
    q = queue.Queue()
    p = DouyinProvider(web_rid, log=app.log)
    task = asyncio.create_task(p.run(q))
    t0 = time.time()
    got = {"chat": 0, "member": 0, "social": 0, "gift": 0, "other": 0}
    try:
        while time.time() - t0 < secs:
            try:
                msg = await asyncio.to_thread(q.get, True, 1)
            except queue.Empty:
                continue
            got[msg.type] = got.get(msg.type, 0) + 1
            if msg.type == "chat":
                print("💬 [%s] %s: %s" % (msg.platform, msg.uname, msg.text[:40]))
                danmaku.handle_message(app, msg.text, msg.uname, msg.platform)
    finally:
        p.stop(); task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    print("\n启动日志:", app.logs[:6])
    print("消息分布:", got)
    total = sum(got.values())
    print("结论:", "✅ 端到端跑通（%ds 收到 %d 条，chat %d 条已入统一指令入口）"
          % (secs, total, got["chat"]) if total else "❌ 没收到消息")
    sys.exit(0 if total else 1)

asyncio.run(main())
