# -*- coding: utf-8 -*-
"""
# 改造后行为有意变化：本脚本证明"白名单外的符号仍是纯搬家"。
# 白名单内符号与新增函数的正确性由 8 套 _test_* 单测保证。
"""
import ast
import io
import os
import sys
import glob

ORIG = "扫码点歌台_优化首次成功_4.py"
OUT = "点歌台拆分"
MODULES = {"state", "settings", "lyrics", "musiclib", "overlay",
           "smtc", "browserlogin", "danmaku", "mainapp", "main"}


class StripPrefix(ast.NodeTransformer):
    """把 state.xxx / settings.xxx 这类 Attribute 还原为裸 Name。
    仅当 value 是 Name 且 id 属于模块名集合时才还原，其他属性访问原样保留。"""

    def visit_Attribute(self, node):
        self.generic_visit(node)
        v = node.value
        if isinstance(v, ast.Name) and v.id in MODULES:
            new = ast.Name(id=node.attr, ctx=node.ctx)
            ast.copy_location(new, node)
            return new
        return node


def collect(path):
    src = io.open(path, encoding="utf-8-sig").read()
    tree = ast.parse(src)
    funcs, consts = {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            funcs[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node.value
    return funcs, consts


of, oc = collect(ORIG)

# 汇总拆分后的所有定义
nf, nc = {}, {}
for p in glob.glob(os.path.join(OUT, "*.py")):
    f, c = collect(p)
    for k, v in f.items():
        if k in nf:
            print(f"❌ 重复定义 {k} 出现在多个文件")
        nf[k] = (v, os.path.basename(p))
    for k, v in c.items():
        nc[k] = (v, os.path.basename(p))


def norm(node):
    node = StripPrefix().visit(node)
    ast.fix_missing_locations(node)
    return ast.dump(node, annotate_fields=False)


# ── 需求改造后的"预期差异白名单"（1-7步有意改动，来源见 git log）──
# 这些符号 AST 与原文件不同是【正确】的；不在名单内的差异才是真错误。
# 删除符号：改造中整体移除/改名；改动符号：签名或行为有意变化。
EXPECTED_CHANGED = {
    "BiliHandler",                 # step4 弹幕入 pending 队列
    "MusicApp",                    # step1/2/3/5/6/7 多处
    "clean_cache_if_needed",       # step7 孤儿 .part 清理
    "extract_song_info",           # step2 增返 flac_size
    "find_cached_file_for_tier",   # step2 legacy 删除
    "merge_config",                # step6 白名单补 global
    "HTML_CONTENT",                # step6 JS 透明度/队列选项/前缀
    "QUALITY_UI_MAP",              # step2 两档文案
    "QUALITY_FALLBACK_CHAINS",     # step2 两档+needs_enum
    "style_config",                # step6 新配置字段
}
EXPECTED_REMOVED = {
    "extract_url",     # step1 → extract_url_detail
    "search_and_add",  # step4 → search_song + process_one_request
    "predownload_song", "_download_and_cleanup",   # step4 预下载语义消失
}

print("=" * 74)
print("① 函数/类等价性（白名单外必须全等）")
print("=" * 74)
bad = 0
for name in sorted(of):
    if name not in nf:
        if name in EXPECTED_REMOVED:
            print(f"  🟡 {name:34s} 已按需求移除（预期）")
        else:
            print(f"  ❌ {name} 未出现在拆分结果中")
            bad += 1
        continue
    node, where = nf[name]
    if norm(node) == norm(of[name]):
        print(f"  ✅ {name:34s} ≡ 原文件  → {where}")
    elif name in EXPECTED_CHANGED:
        print(f"  🟡 {name:34s} 有意改动（预期）→ {where}")
    else:
        print(f"  ❌ {name:34s} AST 不一致且不在白名单 → {where}")
        bad += 1

print()
print("=" * 74)
print("② 顶层常量（白名单外必须全等）")
print("=" * 74)
for name in sorted(oc):
    if name not in nc:
        print(f"  ❌ {name} 缺失")
        bad += 1
        continue
    node, where = nc[name]
    same = norm(node) == norm(oc[name])
    extra = ""
    if name == "HTML_CONTENT":
        try:
            a = ast.literal_eval(oc[name]); b = ast.literal_eval(node)
            extra = f"  ({len(a)}→{len(b)} 字节)"
        except Exception:
            extra = "  (字面量解析失败)"
    if same:
        print(f"  ✅ {name:34s} ≡ 原文件 → {where}")
    elif name in EXPECTED_CHANGED:
        print(f"  🟡 {name:34s} 有意改动（预期）→ {where}{extra}")
    else:
        print(f"  ❌ {name:34s} 变化且不在白名单 → {where}{extra}")
        bad += 1

print()
print("=" * 74)
print(f"结论：{'白名单外全部保持纯搬家 ✅' if bad == 0 else f'{bad} 处意外漂移 ❌'}")
print("  注：白名单内符号的行为正确性由 8 套 _test_* 单测保证；")
print("      本脚本只担保【其余符号未被无意改动】。")
print("=" * 74)
sys.exit(1 if bad else 0)
