# -*- coding: utf-8 -*-
"""_test_secretstore.py — v1.2.1 需求6：DPAPI 配置加密回归（8 断言）。
运行：python _test_secretstore.py（工作目录任意）。临时文件用 %TEMP%。"""
import json
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "点歌台拆分"))
import secretstore

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("  " + str(extra) if extra and not cond else ""))


def main():
    # 临时目录放工作区内（沙箱可写；用户机器上任意临时目录同样可用）
    tmp = os.path.join(ROOT, "_test_tmp_secretstore")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    p = lambda n: os.path.join(tmp, n)

    ck("① 本机 DPAPI 可用", secretstore.dpapi_available())

    # 写→密文落盘→读→还原
    d = {"bili_cookie": "SESSDATA=abc; bili_jct=def", "room_id": "123",
         "style_config": {"lyric": {"color": "#FFE600"}}}
    secretstore.write_json(p("c.json"), d)
    raw = open(p("c.json"), encoding="utf-8").read()
    ck("② 落盘是密文且无明文 Cookie", "__enc__" in raw and "SESSDATA" not in raw)
    ck("③ 读回与写入深度相等", secretstore.read_json(p("c.json")) == d)

    # 明文迁移
    open(p("m.json"), "w", encoding="utf-8").write(json.dumps({"musicid": "m", "musickey": "k"}))
    ck("④ 明文迁移返回 True 且内容变密文", secretstore.migrate_plaintext(p("m.json"))
       and "__enc__" in open(p("m.json"), encoding="utf-8").read())
    ck("⑤ 二次迁移是 no-op", secretstore.migrate_plaintext(p("m.json")) is False)

    # 兼容与兜底
    open(p("old.json"), "w", encoding="utf-8").write(json.dumps({"a": 1}))
    ck("⑥ 老明文文件透明读", secretstore.read_json(p("old.json")) == {"a": 1})
    open(p("bad.json"), "w", encoding="utf-8").write(json.dumps({"__enc__": 1, "data": "aGVsbG8="}))
    ck("⑦ 解不开的密文回 default 不崩", secretstore.read_json(p("bad.json"), default={"f": 1}) == {"f": 1})
    ck("⑧ 缺文件回 default", secretstore.read_json(p("不存在.json"), default=None) is None)

    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'✅' if not bad else '❌'} _test_secretstore: {len(RESULTS) - len(bad)}/{len(RESULTS)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
