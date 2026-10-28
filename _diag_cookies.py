# -*- coding: utf-8 -*-
"""排查 get_cookies 为何为空：
  1. private_mode（默认 True，Cookie 不落盘）是否影响
  2. 是否需要在 start() 时指定 storage_path
  3. 窗口未真正加载完页面
"""
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

result = {}


def probe(private_mode, storage_path, url, wait_load=8):
    """在独立线程里起窗口，测 get_cookies。"""
    tag = f"private={private_mode} storage={'yes' if storage_path else 'no'}"
    out = {"tag": tag}

    def work():
        old = threading.current_thread().name
        threading.current_thread().name = "MainThread"
        try:
            w = wv.create_window("probe", url, width=900, height=650)

            def poll():
                time.sleep(wait_load)
                try:
                    out["url"] = str(w.get_current_url())[:55]
                except Exception as e:
                    out["url_err"] = str(e)[:60]
                # 多种方式读 Cookie
                try:
                    ck = w.get_cookies()
                    out["type"] = type(ck).__name__
                    out["len"] = len(ck) if ck else 0
                    if ck:
                        try:
                            keys = list(ck.keys()) if hasattr(ck, "keys") else list(ck)
                            out["keys"] = [str(k) for k in keys][:8]
                        except Exception as e:
                            out["keys_err"] = str(e)[:50]
                except Exception as e:
                    out["cookie_err"] = f"{type(e).__name__}: {str(e)[:80]}"
                # 同时用 JS 读 document.cookie 对照
                try:
                    js = w.evaluate_js("document.cookie")
                    out["js_cookie_len"] = len(js) if js else 0
                    out["js_sample"] = (js or "")[:60]
                except Exception as e:
                    out["js_err"] = str(e)[:60]
                try:
                    w.destroy()
                except Exception:
                    pass

            threading.Thread(target=poll, daemon=True).start()
            wv.start(debug=False, private_mode=private_mode,
                     storage_path=storage_path)
        except Exception as e:
            out["start_err"] = f"{type(e).__name__}: {str(e)[:100]}"
        finally:
            threading.current_thread().name = old

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout=wait_load + 20)
    return out


print("═══ 测试 1: private_mode=True（默认）═══")
r1 = probe(True, None, "https://www.bilibili.com/")
for k, v in r1.items():
    print(f"  {k}: {v}")

print("\n═══ 测试 2: private_mode=False + 落盘目录 ═══")
import os
sp = os.path.abspath("_wv_storage")
os.makedirs(sp, exist_ok=True)
r2 = probe(False, sp, "https://www.bilibili.com/")
for k, v in r2.items():
    print(f"  {k}: {v}")
