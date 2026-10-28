# -*- coding: utf-8 -*-
"""按 PR #1832 的做法，为已装的 pywebview 补上 coreclr 支持：
  1. 生成 pywebview-runtimeconfig.json（要求 Microsoft.WindowsDesktop.App，rollForward=LatestMajor）
  2. 设法让 winforms 后端在 coreclr 下能加载 System.Windows.Forms
  这里先做第 1 步并验证 runtimeconfig 是否被 clr_loader 接受。"""
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIB = os.path.join(".venv", "Lib", "site-packages", "webview", "lib")
os.makedirs(LIB, exist_ok=True)

# PR 里给出的正是这个内容
CFG = {
    "runtimeOptions": {
        "tfm": "net6.0-windows",
        "rollForward": "LatestMajor",
        "framework": {
            "name": "Microsoft.WindowsDesktop.App",
            "version": "6.0.0",
        },
    }
}
P = os.path.join(LIB, "pywebview-runtimeconfig.json")
with io.open(P, "w", encoding="utf-8") as f:
    json.dump(CFG, f, indent=2)
print(f"已写入 {P}")
print(json.dumps(CFG, indent=2))

# 验证 clr_loader 是否接受 runtime_config 参数
print("\n═══ 验证 clr_loader.get_coreclr(runtime_config=...) ═══")
try:
    import inspect
    from clr_loader import get_coreclr
    sig = inspect.signature(get_coreclr)
    print("  get_coreclr 签名:", sig)
    has = "runtime_config" in sig.parameters
    print("  支持 runtime_config:", "✅" if has else "❌")
except Exception as e:
    print("  失败:", type(e).__name__, e)
