# -*- coding: utf-8 -*-
"""技术验证：pywebview 能否加载 B站登录页、扫码、拿到 Cookie。
不真正扫码（需要人工），只验证：
  1. 窗口能起来（WebView2 渲染）
  2. 页面能加载
  3. get_cookies() 可用且有值
  4. 关闭后进程不残留
"""
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import webview

TARGET = "https://passport.bilibili.com/login"
result = {}


def worker(w):
    """window 创建后延迟执行：等页面加载，读 URL 和 Cookie。"""
    try:
        for i in range(20):          # 最多等 10 秒
            time.sleep(0.5)
            try:
                url = w.get_current_url()
            except Exception:
                url = None
            if url and "passport.bilibili.com" in str(url):
                result["url"] = url
                break
        time.sleep(1.5)              # 再等 Cookie 落盘
        ck = w.get_cookies()
        result["cookie_count"] = len(ck) if ck else 0
        # 只报名字，不打印值（避免泄露）
        try:
            names = [c.name if hasattr(c, "name") else k for k, c in (ck.items() if isinstance(ck, dict) else [])]
            if not names and ck:
                names = [str(x)[:20] for x in list(ck)[:8]]
            result["cookie_names"] = names[:10]
        except Exception as e:
            result["cookie_names"] = f"解析失败 {e}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"


print("创建 pywebview 窗口...")
w = webview.create_window("技术验证 - B站登录页", TARGET, width=1100, height=800)

threading.Thread(target=worker, args=(w,), daemon=True).start()

# 10 秒后自动关闭（无人值守验证）
def closer():
    time.sleep(12)
    try:
        w.destroy()
    except Exception:
        pass

threading.Thread(target=closer, daemon=True).start()

webview.start(debug=False)

print("\n═══ 验证结果 ═══")
print("  窗口已正常关闭（webview.start 返回）")
for k, v in result.items():
    print(f"  {k}: {v}")

ok = result.get("url") and "bilibili" in str(result.get("url", ""))
print("\n结论:", "✅ WebView2 能加载 B站页面" if ok else "❌ 页面未加载成功")
