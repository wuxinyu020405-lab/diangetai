# -*- coding: utf-8 -*-
"""对照实验：清除 WebView2 用户数据目录后，看是否又失败。
目的：确认"能加载"是稳定能力，还是依赖某次缓存的代理设置。"""
import os
import shutil
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 找 pywebview 的用户数据目录
cands = [
    os.path.expandvars(r"%APPDATA%\pywebview"),
    os.path.join(os.getcwd(), "_wv_storage"),
    os.path.expandvars(r"%LOCALAPPDATA%\pywebview"),
]
print("═══ 现有 WebView2 用户数据目录 ═══")
for c in cands:
    print(f"  {c}: {'存在' if os.path.isdir(c) else '不存在'}")

# 清理（模拟首次运行）
for c in cands:
    if os.path.isdir(c):
        shutil.rmtree(c, ignore_errors=True)
        print(f"  已删除 {c}")

import browserlogin
wv = browserlogin._get_webview()
out = {}


def build():
    w = wv.create_window("clean", "https://www.bilibili.com/", width=900, height=650)

    def poll():
        time.sleep(12)
        try:
            out["loc"] = w.evaluate_js("location.href")[:60]
            out["body"] = w.evaluate_js("(document.body?document.body.innerText:'').slice(0,80)")[:80]
            ck = w.get_cookies()
            out["cookies"] = len(ck) if ck else 0
        except Exception as e:
            out["err"] = str(e)[:100]
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=poll, daemon=True).start()


build()
try:
    wv.start(debug=False)
except Exception as e:
    out["start_err"] = str(e)[:100]

print("\n═══ 清空用户数据后首次运行 ═══")
for k in sorted(out):
    print(f"  {k}: {out[k]}")

ok = "bilibili.com" in str(out.get("loc", ""))
print("\n结论:", "✅ 干净环境也能加载（能力稳定）" if ok else "⚠ 首次运行失败（依赖代理配置）")
