# -*- coding: utf-8 -*-
"""提取 overlay.py 内嵌 JS 到 _chk.js 并 node --check（避免管道/编码坑）。"""
import io
import re
import subprocess

src = io.open("点歌台拆分/overlay.py", encoding="utf-8").read()
js = re.search(r"<script>(.*?)</script>", src, re.S).group(1)
io.open("_chk.js", "w", encoding="utf-8").write(js)
r = subprocess.run(["node", "--check", "_chk.js"], capture_output=True, text=True)
print("node --check:", "OK" if r.returncode == 0 else "FAIL")
if r.returncode != 0:
    print(r.stderr[:1200])
raise SystemExit(r.returncode)
