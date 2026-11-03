"""
歌词：LRC 文本解析、当前播放行的窗口计算
"""

import re
import html
import state

def parse_lrc(lrc_text):
    if not lrc_text or not isinstance(lrc_text, str): return []
    lrc_text = html.unescape(lrc_text)
    lines = []
    # v1.1·H2：单个时间戳标记（非贪婪吃掉行首连续的多个 [mm:ss.xx]）。
    # 旧实现用 (.*) 把"第一个时间戳之后的全部"当正文，导致
    #   [00:01.00][01:20.00]副歌   的第二段标记被当成正文字符渲染上屏。
    _ts = re.compile(r'\[(\d{2,}):(\d{2})(?:\.(\d{1,3}))?\]')
    for raw_line in lrc_text.splitlines():
        s = raw_line.strip()
        if not s:
            continue
        stamps = []
        pos = 0
        while True:
            m = _ts.match(s, pos)
            if not m:
                break
            minutes = int(m.group(1)); seconds = int(m.group(2))
            frac = m.group(3) or "0"; ms = int(frac.ljust(3, '0')[:3])
            stamps.append(minutes * 60 + seconds + ms / 1000.0)
            pos = m.end()
        if not stamps:
            continue
        content = s[pos:].strip()
        # 过滤空行与 // 注释（QQ音乐/网易云 LRC 常见注释约定）；旧实现只排除了
        # 内容恰好等于 "//" 的行，漏掉了 "//xxx" 这种带正文的注释。
        if not content or content.startswith("//"):
            continue
        for t in stamps:
            lines.append((t, content))
    lines.sort(key=lambda x: x[0])
    return lines

def get_current_lyric_state(lrc_lines, elapsed_sec):
    if not lrc_lines: return {"lines": [], "all_lines": [], "active_idx": -1}
    idx = -1
    for i, (t, _) in enumerate(lrc_lines):
        if elapsed_sec >= t: idx = i
        else: break
    if idx == -1: idx = 0

    prev_count = state.style_config["lyric"].get("lines_prev", 2)
    next_count = state.style_config["lyric"].get("lines_next", 2)
    start_idx = max(0, idx - prev_count)
    end_idx = min(len(lrc_lines), idx + next_count + 1)

    result = []
    for i in range(start_idx, end_idx):
        is_active = (i == idx)
        result.append({"text": lrc_lines[i][1], "active": is_active})

    all_lines = [line_text for _, line_text in lrc_lines]
    return {"lines": result, "all_lines": all_lines, "active_idx": idx}
