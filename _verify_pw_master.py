# -*- coding: utf-8 -*-
"""最终验证：新版 pywebview（master，含 PR #1832）能否开窗口并加载 QQ音乐。
不做任何手工程序集加载 —— 只用官方推荐的用法，看它自己能不能搞定。"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import threading
import time

print("导入 webview（不设任何环境变量，让库自己选运行时）...")
try:
    import webview
    print("  ✅ 导入成功")
except Exception as e:
    print("  ❌", type(e).__name__, str(e)[:200])
    sys.exit(1)

result = {}


def worker(w):
    try:
        for _ in range(24):
            time.sleep(0.5)
            try:
                u = w.get_current_url()
            except Exception:
                u = None
            if u and len(str(u)) > 15:
                result["url"] = str(u)[:75]
                break
        time.sleep(1.8)
        ck = w.get_cookies()
        result["cookie_count"] = len(ck) if ck else 0
        if ck and isinstance(ck, dict):
            result["cookie_names"] = list(ck.keys())[:8]
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:110]}"


print("\n创建窗口...")
w = webview.create_window("pywebview 验证", "https://y.qq.com",
                          width=1100, height=780)
threading.Thread(target=worker, args=(w,), daemon=True).start()


def closer():
    time.sleep(15)
    try:
        w.destroy()
    except Exception:
        pass


threading.Thread(target=closer, daemon=True).start()

try:
    webview.start(debug=False)
except Exception as e:
    print(f"\n❌ webview.start 失败: {type(e).__name__}: {str(e)[:400]}")
    sys.exit(1)

print("\n═══ 结果 ═══")
for k, v in result.items():
    print(f"  {k}: {v}")
ok = result.get("url") and "qq.com" in str(result.get("url"))
print("\n" + ("🎉🎉 pywebview 终于可用！" if ok else "⚠ 窗口起了，页面未确认"))
