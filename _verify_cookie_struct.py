# -*- coding: utf-8 -*-
"""看清 get_cookies 返回的 list 里到底是什么对象，据此修正解析。"""
import sys
import threading
import time

sys.path.insert(0, "点歌台拆分")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import browserlogin

wv = browserlogin._get_webview()
out = []


def build():
    w = wv.create_window("struct", "https://www.bilibili.com/", width=1000, height=700)

    def poll():
        time.sleep(6)
        try:
            raw = w.get_cookies()
            out.append(f"类型: {type(raw).__name__}, 长度: {len(raw) if raw else 0}")
            if raw:
                for i, item in enumerate(raw[:4]):
                    out.append(f"  [{i}] type={type(item).__name__}")
                    out.append(f"      repr={repr(item)[:150]}")
                    for attr in ("name", "value", "Name", "Value"):
                        if hasattr(item, attr):
                            try:
                                out.append(f"      .{attr} = {str(getattr(item, attr))[:40]}")
                            except Exception as e:
                                out.append(f"      .{attr} 读取失败 {e}")
                    # 字典式访问
                    if isinstance(item, dict):
                        out.append(f"      dict keys: {list(item.keys())}")
        except Exception as e:
            out.append(f"ERR {type(e).__name__}: {str(e)[:100]}")
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=poll, daemon=True).start()


build()
try:
    wv.start(debug=False)
except Exception as e:
    print("start:", str(e)[:80])

print("═══ get_cookies 返回结构 ═══")
for line in out:
    print("  ", line)
