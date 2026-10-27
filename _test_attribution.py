# -*- coding: utf-8 -*-
"""需求9 失败归因单测：result 码解析 / 异常分类 / 凭证续期路径（纯逻辑，不联网）。"""
import sys
sys.path.insert(0, "点歌台拆分")

import musiclib
from qqmusic_api.core import exceptions as E

passed, failed = 0, 0


def case(name, got, want):
    global passed, failed
    ok = got == want
    passed += ok
    failed += (not ok)
    print(f"  {'✅' if ok else '❌'} {name}: got={got!r} want={want!r}")


def Info(result, purl, filename="f.flac"):
    class I: pass
    i = I(); i.result = result; i.purl = purl; i.filename = filename
    return i


def Resp(data, expiration=3600):
    class R: pass
    r = R(); r.data = data; r.expiration = expiration
    return r


print("═══ extract_url_detail ═══")
d = musiclib.extract_url_detail(Resp([Info(0, "https://a.com/x.flac")]), cdn="")
case("成功直链 url", d["url"], "https://a.com/x.flac")
case("成功 result", d["result"], 0)
case("expiration 保留", d["expiration"], 3600)

d = musiclib.extract_url_detail(Resp([Info(0, "/rel/y.flac")]), cdn="https://cdn.q.com")
case("相对路径拼 CDN", d["url"], "https://cdn.q.com/rel/y.flac")

d = musiclib.extract_url_detail(Resp([Info(104003, "")]))
case("无权限 result", d["result"], 104003)
case("无权限文案", d["result_text"], "无该音质权限")
case("无权限 url", d["url"], None)

d = musiclib.extract_url_detail(Resp([Info(104004, "")]))
case("VKey失败文案", d["result_text"], "VKey获取失败")

d = musiclib.extract_url_detail(Resp([Info(104013, "")]))
case("设备受限文案", d["result_text"], "播放设备受限")

d = musiclib.extract_url_detail(Resp([Info(9999, "")]))
case("未知码文案", d["result_text"], "未知业务码(9999)")

d = musiclib.extract_url_detail(Resp([Info(0, "")]))
case("result=0 但 purl 空", d["result_text"], "purl 为空(result=0)")

d = musiclib.extract_url_detail(None)
case("空响应", d["result_text"], "响应为空")

d = musiclib.extract_url_detail(Resp([]))
case("空 data 列表", d["result_text"], "响应无 data 列表")

# 畸形 purl（issue #63 的 'h' 场景）：非 http 且无 cdn → 拒绝
d = musiclib.extract_url_detail(Resp([Info(0, "h")]), cdn="")
case("畸形值 h 被拒", d["url"], None)

print()
print("═══ classify_api_exception ═══")
mk = lambda cls: cls.__new__(cls)
# 分类顺序验证：Ratelimited 继承 CgiApiException，必须判成 quota 而非 skip
for cls in (E.RatelimitedError, E.CgiApiException):
    try:
        obj = cls("x", code=1, data=None)
    except TypeError:
        obj = cls("x")
    a, _ = musiclib.classify_api_exception(obj)
    print(f"  {cls.__name__} -> {a}")

case("Ratelimited→quota", musiclib.classify_api_exception(E.RatelimitedError("x", code=1, data=None))[0], "quota")
case("CredentialExpired→refresh_cred", musiclib.classify_api_exception(E.CredentialExpiredError("x", code=1, data=None))[0], "refresh_cred")
case("LoginAuthExpired→refresh_cred", musiclib.classify_api_exception(E.LoginAuthExpiredError("x", code=1, data=None))[0], "refresh_cred")
case("TimeoutNetwork→retry", musiclib.classify_api_exception(E.TimeoutNetworkError("t"))[0], "retry")
case("ApiData→skip", musiclib.classify_api_exception(E.ApiDataError("d"))[0], "skip")
case("GlobalApi→skip", musiclib.classify_api_exception(E.GlobalApiError("g", code=1, data=None))[0], "skip")
case("普通ValueError→retry兜底", musiclib.classify_api_exception(ValueError("v"))[0], "retry")
case("url_result_text(104004)", musiclib.url_result_text(104004), "VKey获取失败")

print()
print(f"总计 {passed + failed} 项 | 通过 {passed} | 失败 {failed}")
sys.exit(1 if failed else 0)
