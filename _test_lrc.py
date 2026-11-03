# -*- coding: utf-8 -*-
"""v1.1·H2 歌词解析回归测试（纯函数，安全）。
用法: ./.venv/Scripts/python.exe -X utf8 _test_lrc.py
覆盖用户报告的两类脏渲染 + 全部旧有正确行为（防回归）。
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
from lyrics import parse_lrc

results = []
def ck(name, got, want):
    ok = got == want
    results.append(ok)
    print(("OK  " if ok else "FAIL"), name, "" if ok else "\n     got=%r\n    want=%r" % (got, want))

# ① 核心：重复时间戳 → 同一句在两个时间点各出现一次，第二个标记绝不上屏
r = parse_lrc("[00:01.00][01:20.00]副歌重复")
ck("重复时间戳展开为两行且无标记残留", r, [(1.0, "副歌重复"), (80.0, "副歌重复")])

# ② 三连时间戳
r = parse_lrc("[00:10.00][00:30.00][01:50.00]chorus")
ck("三连时间戳", r, [(10.0, "chorus"), (30.0, "chorus"), (110.0, "chorus")])

# ③ // 注释行被过滤（旧实现只滤恰好"//"，漏 "//xxx"）
r = parse_lrc("[00:05.00]//制作信息\n[00:10.00]正常歌词")
ck("//注释过滤+正常行保留", r, [(10.0, "正常歌词")])

# ④ 元信息标签忽略（旧行为保持）
r = parse_lrc("[ti:歌名]\n[ar:歌手]\n[00:05.00]第一行")
ck("元信息标签忽略", r, [(5.0, "第一行")])

# ⑤ 无毫秒格式（旧行为保持）
r = parse_lrc("[00:30]半分钟")
ck("无毫秒时间戳", r, [(30.0, "半分钟")])

# ⑥ 排序
r = parse_lrc("[00:50.00]后\n[00:10.00]先")
ck("按时间排序", r, [(10.0, "先"), (50.0, "后")])

# ⑦ 空内容行丢弃
r = parse_lrc("[00:10.00]   \n[00:20.00]有字")
ck("空内容行丢弃", r, [(20.0, "有字")])

# ⑧ 千分位毫秒 + 三位分钟（100 分钟专辑）；单位数分钟不符合本项目的
#   \d{2,} 约定（新旧一致），用 01 验证
r = parse_lrc("[01:05.500]甲\n[100:00.00]乙")
ck("三位毫秒+三位分钟", r, [(65.5, "甲"), (6000.0, "乙")])

# ⑨ 正文里含方括号但非时间戳格式 → 原样保留（不误吞）
r = parse_lrc("[00:10.00]歌词[说唱]部分")
ck("正文内方括号保留", r, [(10.0, "歌词[说唱]部分")])

# ⑩ 纯文本行（无时间戳）忽略
r = parse_lrc("没有时间的行\n[00:10.00]有")
ck("无时间戳行忽略", r, [(10.0, "有")])

# ⑪ html 实体还原（旧行为保持）
r = parse_lrc("[00:10.00]A &amp; B")
ck("html实体还原", r, [(10.0, "A & B")])

bad = results.count(False)
print("结论:", "✅ H2 解析回归 %d/%d 全过" % (len(results), len(results)) if bad == 0 else "❌ 失败 %d 项" % bad)
sys.exit(0 if bad == 0 else 1)
