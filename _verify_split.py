# -*- coding: utf-8 -*-
"""
等价性证明：拆分后的代码，去掉新加的模块前缀后，应与原文件逐函数 AST 完全一致。
若一致 → 证明"纯搬家"，逻辑零改动。
"""
import ast
import io
import os
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


print("=" * 74)
print("① 函数/类等价性")
print("=" * 74)
bad = 0
for name in sorted(of):
    if name not in nf:
        print(f"  ❌ {name} 未出现在拆分结果中")
        bad += 1
        continue
    node, where = nf[name]
    if norm(node) == norm(of[name]):
        print(f"  ✅ {name:34s} ≡ 原文件  → {where}")
    else:
        print(f"  ❌ {name:34s} AST 不一致 → {where}")
        bad += 1

print()
print("=" * 74)
print("② 顶层常量等价性")
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
        a = ast.literal_eval(oc[name])
        b = ast.literal_eval(node)
        extra = f"  (逐字节 {len(a)} == {len(b)}: {a == b})"
        same = same and a == b
    print(f"  {'✅' if same else '❌'} {name:34s} → {where}{extra}")
    if not same:
        bad += 1

print()
print("=" * 74)
print(f"结论：{'全部等价，纯搬家成立 ✅' if bad == 0 else f'{bad} 处不等价 ❌'}")
print("=" * 74)
