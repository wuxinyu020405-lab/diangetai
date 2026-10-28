# -*- coding: utf-8 -*-
"""对照实验：主线程 vs 子线程（打桩）运行 pywebview，get_cookies 差异。
主线程运行会阻塞本脚本，用定时器自动关闭。"""
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
out = {}


def build_and_probe(tag):
    w = wv.create_window("cookie test", "https://www.bilibili.com/", width=900, height=650)

    def poll():
        time.sleep(10)
        try:
            out[tag + "_url"] = str(w.get_current_url())[:45]
            ck = w.get_cookies()
            out[tag + "_count"] = len(ck) if ck else 0
            if ck:
                out[tag + "_list"] = [str(x)[:45] for x in list(ck)[:4]]
            # 再用 JS 读（同源下可用）
            try:
                js = w.evaluate_js("document.cookie || ''")
                out[tag + "_js_len"] = len(js) if js else 0
                out[tag + "_js_head"] = str(js)[:80]
            except Exception as e:
                out[tag + "_js_err"] = str(e)[:60]
        except Exception as e:
            out[tag + "_err"] = f"{type(e).__name__}: {str(e)[:80]}"
        finally:
            try:
                w.destroy()
            except Exception:
                pass

    threading.Thread(target=poll, daemon=True).start()
    return w


# ---- 主线程运行（本脚本主线程没有被 Tk 占用，可直用）----
print("═══ 主线程运行 ═══")
build_and_probe("main")
try:
    wv.start(debug=False)
except Exception as e:
    out["main_start_err"] = str(e)[:100]

for k in sorted(out):
    print(f"  {k}: {out[k]}")
