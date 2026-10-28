# -*- coding: utf-8 -*-
"""版本单一来源。

发版流程：改这里 → 提交 → 打 tag `v{VERSION}` → CI 用同一份版本号打包发布。
exe 版本资源（spec）、GUI 标题、自检报告、更新比对全部读这里。
"""

VERSION = "1.0.0"                      # 语义化版本，无 v 前缀
VERSION_TUPLE = (1, 0, 0, 0)           # exe 版本资源用（四段）
PRERELEASE = ""                        # 正式版留空；测试版如 "-beta.1"

DISPLAY = "v" + VERSION + PRERELEASE   # GUI / 日志用


def parse(v):
    """'1.2.3' -> (1,2,3)；解析失败返回 None。容忍 v 前缀与 -beta 后缀。"""
    try:
        s = v.strip().lstrip("vV").split("-")[0].split("+")[0]
        parts = tuple(int(x) for x in s.split("."))
        return parts if parts else None
    except Exception:
        return None


def is_newer(latest, current=None):
    """latest 严格新于 current 返回 True；任何一侧解析失败返回 False（宁可不提醒）。"""
    a = parse(latest)
    b = parse(current if current is not None else VERSION)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b
