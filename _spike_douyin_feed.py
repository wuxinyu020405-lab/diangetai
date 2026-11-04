# -*- coding: utf-8 -*-
"""用 X-Bogus 签名调抖音推荐流接口，自动找在播房间。
接口候选来自社区逆向实践；签名走已验证的 sign_runner.js。"""
import re, sys, json, hashlib, subprocess, os, time, urllib.parse
import urllib.request, http.cookiejar
sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SIGN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "douyin_sign")

cj = http.cookiejar.CookieJar()
o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
o.addheaders = [("User-Agent", UA), ("Referer", "https://live.douyin.com/")]
o.open("https://live.douyin.com/", timeout=15)
ttwid = next((c.value for c in cj if c.name == "ttwid"), "")
print("ttwid:", bool(ttwid))

def sign(params_str):
    md5 = hashlib.md5(params_str.encode()).hexdigest()
    r = subprocess.run(["node", os.path.join(SIGN_DIR, "sign_runner.js"), md5],
                       capture_output=True, text=True, cwd=SIGN_DIR, timeout=45)
    return r.stdout.strip()

def try_feed(name, base, params):
    """params: dict；拼 query → 签名 → 带 X-Bogus 请求。"""
    qs = "&".join("%s=%s" % (k, urllib.parse.quote(str(v))) for k, v in params.items())
    xb = sign(qs)
    if not xb:
        print(name, "签名失败"); return None
    url = base + "?" + qs + "&X-Bogus=" + urllib.parse.quote(xb)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": "https://live.douyin.com/",
            "Cookie": "ttwid=%s" % ttwid,
        })
        body = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
        rids = re.findall(r'"id_str":"(\d{15,25})"', body)
        print("%-28s len=%-7d id_str=%d" % (name, len(body), len(rids)))
        if rids:
            return rids
    except Exception as e:
        print("%-28s 失败 %s %s" % (name, type(e).__name__, str(e)[:60]))
    return None

common = dict(aid="6383", app_name="douyin_web", live_id="1", device_platform="web",
              language="zh-CN", cookie_enabled="true", screen_width="1920",
              screen_height="1080", browser_language="zh-CN", browser_platform="Win32",
              browser_name="Chrome", browser_version="126.0.0.0")

tries = [
    ("feed 推荐流", "https://live.douyin.com/webcast/ranklist/audience/",
     dict(common, rank_type="20", count="20")),
    ("category 分区", "https://live.douyin.com/webcast/web/partition/",
     dict(common)),
    ("热门榜", "https://live.douyin.com/webcast/ranklist/room/",
     dict(common, rank_type="1", count="20")),
    ("feed 简单版", "https://live.douyin.com/webcast/feed/",
     dict(common, count="20", source="web_live", channel="channel_pc_web")),
]
rids = None
for name, base, params in tries:
    rids = try_feed(name, base, params)
    if rids:
        break

if rids:
    print("✅ 拿到在播候选 room_id:", rids[:5])
    open("_spike_feed.txt", "w").write("\n".join(rids[:10]))
else:
    print("❌ 全部接口失败（可能接口路径或签名 stub 字段不对）")
