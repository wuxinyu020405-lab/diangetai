# -*- coding: utf-8 -*-
"""验证修复后的 _cookies_to_dict 能完整解析 Cookie 列表。"""
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import browserlogin
import http.cookies as _ck

# 先用构造数据做纯逻辑单测
print("═══ 单元测试：模拟 pywebview 的返回结构 ═══")
raw = []
for name, val in (("buvid3", "ABC123"), ("_uuid", "UUID-1"), ("b_nut", "1793")):
    sc = _ck.SimpleCookie()
    sc[name] = val
    raw.append(sc)

got = browserlogin._cookies_to_dict(raw)
print(f"  输入 {len(raw)} 个 SimpleCookie → 解析出 {len(got)} 个: {got}")
assert len(got) == 3, "单测失败"
assert got["buvid3"] == "ABC123"

# 兼容单个 SimpleCookie
one = _ck.SimpleCookie(); one["SESSDATA"] = "xyz"
print(f"  单个 SimpleCookie → {browserlogin._cookies_to_dict(one)}")
assert browserlogin._cookies_to_dict(one)["SESSDATA"] == "xyz"

# 兼容 dict
print(f"  普通 dict → {browserlogin._cookies_to_dict({'a': 'b'})}")
assert browserlogin._cookies_to_dict({"a": "b"}) == {"a": "b"}

print("  ✅ 单测通过\n")

# 再用真实页面验证
wv = browserlogin._get_webview()
out = {}


def build():
    w = wv.create_window("verify", "https://www.bilibili.com/", width=1000, height=700)

    def poll():
        time.sleep(7)
        try:
            raw = w.get_cookies()
            parsed = browserlogin._cookies_to_dict(raw)
            out["raw_len"] = len(raw) if raw else 0
            out["parsed_len"] = len(parsed)
            out["names"] = list(parsed.keys())[:12]
            out["has_buvid3"] = "buvid3" in parsed
            out["has_SESSDATA"] = "SESSDATA" in parsed
        except Exception as e:
            out["err"] = f"{type(e).__name__}: {str(e)[:90]}"
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=poll, daemon=True).start()


build()
try:
    wv.start(debug=False)
except Exception as e:
    print("start:", str(e)[:80])

print("═══ 真实页面验证 ═══")
for k in sorted(out):
    print(f"  {k}: {out[k]}")

ok = out.get("parsed_len", 0) >= 5
print("\n结论:", "✅ Cookie 解析完全正常" if ok else "❌ 仍有问题")
print("   （未登录时没有 SESSDATA 属正常 —— 登录后才会下发）")
