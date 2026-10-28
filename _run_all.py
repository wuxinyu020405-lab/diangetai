# -*- coding: utf-8 -*-
"""一条命令跑全部自动化回归。用法: ./.venv/Scripts/python.exe _run_all.py"""
import subprocess
import sys
import os

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SUITES = [
    ("_test_attribution.py", "step1 失败归因", 22),
    ("_test_quality2.py",    "step2 音质两档", 30),
    ("_test_localfirst.py",  "step3 本地优先", 14),
    ("_test_serial.py",      "step4 串行就绪", 18),
    ("_test_quota.py",       "step5 配额保护", 32),
    ("_test_cfg6.py",        "step6 配置升级", 13),
    ("_test_step6.py",       "step6 设置逻辑", 38),
    ("_test_step7.py",       "step7 正确性",   19),
    ("_test_gui6.py",        "GUI 真机构建冒烟", None),
    ("_smoke_split.py",      "跨模块行为烟测(含OBS服务)", None),
    ("_lint_split.py",       "裸引用lint", None),
    ("_verify_split.py",     "白名单外纯搬家校验", None),
    ("_chk_js.py",           "挂件JS语法", None),
]

env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
           SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
fails = []
for script, label, expect in SUITES:
    r = subprocess.run([sys.executable, script], capture_output=True, text=True,
                       encoding="utf-8", env=env)
    ok = r.returncode == 0
    tail = ""
    if expect is not None:
        for ln in (r.stdout or "").splitlines():
            if "总计" in ln:
                tail = ln.strip()
                ok = ok and f"失败 {expect}" in ln and f"通过 {expect}" in ln
    print(f"{'✅' if ok else '❌'} {label:24s} ({script}) {tail}")
    if not ok:
        fails.append((script, (r.stdout or "")[-400:], (r.stderr or "")[-600:]))

print("=" * 60)
if fails:
    print(f"❌ {len(fails)} 个套件未通过：")
    for s, so, se in fails:
        print(f"--- {s} ---\n{so}\n{se}")
    sys.exit(1)
print("全部自动化回归通过 ✅")
