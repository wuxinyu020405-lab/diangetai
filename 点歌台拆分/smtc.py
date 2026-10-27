"""
系统媒体兜底：从 QQ音乐窗口标题解析正在播放的歌曲
"""

import ctypes
from ctypes import wintypes
import os

def get_qqmusic_window_song():
    if os.name != "nt": return None, None
    try:
        user32 = ctypes.windll.user32
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    cls_buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cls_buf, 256)
                    cls_name = cls_buf.value.strip()
                    if cls_name in ("QQMusic_Daemon_Wnd", "TXGuiFoundation") and " - " in title:
                        if not title.startswith("QQ音乐") and "迷你模式" not in title and "桌面歌词" not in title:
                            parts = title.split(" - ", 1)
                            found.append((parts[0].strip(), parts[1].strip()))
                            return False
            return True
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        if found: return found[0]
    except Exception as e:
        print(f"[WARN] 异常已捕获: {e}")

    return None, None
