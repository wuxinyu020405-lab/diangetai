import ply
import jsonpath_ng
import jsonpath_ng.ext
try:
    import jsonpath_ng.ply_tables
except Exception:
    pass
import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog, colorchooser, ttk
import threading
import asyncio
import inspect
import re
import html
import random
import urllib.parse
import urllib.request
import aiohttp
from aiohttp import web
import time
import ctypes
from ctypes import wintypes
import winsdk.windows.media.control as wmc
import blivedm
import json
import os
import sys
import subprocess
import pygame
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from qqmusic_api import Client, Credential

# ================= 动态探测 qqmusic_api 音质枚举与模型 =================
SongFileInfo = None
SongFileType = None
for _mod_name in ("qqmusic_api.modules.song", "qqmusic_api.models.song", "qqmusic_api.song", "qqmusic_api"):
    try:
        _mod = __import__(_mod_name, fromlist=["SongFileInfo", "SongFileType"])
        if SongFileInfo is None and hasattr(_mod, "SongFileInfo"):
            SongFileInfo = getattr(_mod, "SongFileInfo")
        if SongFileType is None and hasattr(_mod, "SongFileType"):
            SongFileType = getattr(_mod, "SongFileType")
    except Exception:
        pass

if SongFileType is None and SongFileInfo is not None:
    try:
        for _p in inspect.signature(SongFileInfo).parameters.values():
            if _p.default is not inspect.Parameter.empty and hasattr(_p.default, "__class__") and "FileType" in _p.default.__class__.__name__:
                SongFileType = _p.default.__class__
                break
    except Exception:
        pass

# ================= 修复路径 =================
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CREDENTIAL_FILE = os.path.join(BASE_DIR, "credential.json")
CACHE_DIR = os.path.join(BASE_DIR, "music_cache")

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# 屏蔽代理
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('all_proxy', None)
os.environ.pop('ALL_PROXY', None)

# ================= 全局状态 =================
playlist = []
current_song = None
skip_event = None
app = None
system_media_info = {"title": "暂无播放", "artist": ""}
current_lyric_info = {"lines": [], "all_lines": [], "active_idx": -1}
lyric_cache = {}  
qq_credential = None 

# 👇 整合部署后的完整独立配置结构（包含纯歌词对齐方式，移除了透明度配置）
style_config = {
    "mixed": {
        "show_playing": True, "show_queue": True, "show_lyric": True,
        "font_playing": "'PingFang SC', 'Microsoft YaHei', sans-serif", "color_playing": "#00FFFF", "size_playing": 32, "bold_playing": False,
        "font_lyric": "'PingFang SC', 'Microsoft YaHei', sans-serif", "color_lyric": "#FFE600", "size_lyric": 28, "effect_lyric": "apple_hd", "bold_lyric": False,
        "font_queue": "'PingFang SC', 'Microsoft YaHei', sans-serif", "color_queue": "#FFFFFF", "size_queue": 36, "bold_queue": False
    },
    "lyric": {
        "font": "'PingFang SC', 'Microsoft YaHei', sans-serif",
        "color": "#FFE600", "size": 28, "align": "center",
        "effect": "apple_hd", "lines_prev": 2, "lines_next": 2,
        "pure_text": "纯音乐, 请欣赏..", "is_bold": False
    },
    "playing": {
        "font": "'PingFang SC', 'Microsoft YaHei', sans-serif",
        "color": "#00FFFF", "size": 32, "show_prefix": True, "is_bold": False
    },
    "queue": {
        "font": "'PingFang SC', 'Microsoft YaHei', sans-serif",
        "color": "#FFFFFF", "size": 36, "max_chars": 30, "is_bold": False
    },
    "audio_quality": "flac",
    "max_cache_files": 100,
    "max_cache_size_mb": 500
}

def merge_config(old_cfg, new_cfg):
    if not old_cfg: return new_cfg
    if "system_color" in old_cfg:
        new_cfg["playing"]["color"] = old_cfg.get("system_color", "#00FFFF")
        new_cfg["mixed"]["color_playing"] = old_cfg.get("system_color", "#00FFFF")
    if "lyric_color" in old_cfg:
        new_cfg["lyric"]["color"] = old_cfg.get("lyric_color", "#FFE600")
        new_cfg["mixed"]["color_lyric"] = old_cfg.get("lyric_color", "#FFE600")
    if "queue_color" in old_cfg:
        new_cfg["queue"]["color"] = old_cfg.get("queue_color", "#FFFFFF")
        new_cfg["mixed"]["color_queue"] = old_cfg.get("queue_color", "#FFFFFF")
    if "bgm_font_size" in old_cfg:
        new_cfg["playing"]["size"] = old_cfg.get("bgm_font_size", 32)
        new_cfg["mixed"]["size_playing"] = old_cfg.get("bgm_font_size", 32)
    if "lyric_font_size" in old_cfg:
        new_cfg["lyric"]["size"] = old_cfg.get("lyric_font_size", 28)
        new_cfg["mixed"]["size_lyric"] = old_cfg.get("lyric_font_size", 28)
    if "list_font_size" in old_cfg:
        new_cfg["queue"]["size"] = old_cfg.get("list_font_size", 36)
        new_cfg["mixed"]["size_queue"] = old_cfg.get("list_font_size", 36)
    
    for section in ["mixed", "lyric", "playing", "queue"]:
        if section in old_cfg and isinstance(old_cfg[section], dict):
            new_cfg[section].update(old_cfg[section])
            
    if "audio_quality" in old_cfg: new_cfg["audio_quality"] = old_cfg["audio_quality"]
    if "max_cache_files" in old_cfg: new_cfg["max_cache_files"] = old_cfg["max_cache_files"]
    if "max_cache_size_mb" in old_cfg: new_cfg["max_cache_size_mb"] = old_cfg["max_cache_size_mb"]
    return new_cfg

QUALITY_UI_MAP = {
    "flac": "FLAC 无损品质 (推荐)",
    "hires": "Hi-Res 高解析无损 (优先)",
    "master": "臻品母带 Master (优先)",
    "mp3_320": "320k 高品质 MP3",
    "mp3_128": "128k 标准 MP3 (省流)"
}
UI_QUALITY_MAP = {v: k for k, v in QUALITY_UI_MAP.items()}

QUALITY_FALLBACK_CHAINS = {
    "master": [
        ("master", "臻品母带", ("MASTER", "AI00"), ".flac"),
        ("hires", "Hi-Res 无损", ("HI_RES", "HIRES", "RS01", "FLAC_HIRES"), ".flac"),
        ("flac", "FLAC 无损", ("FLAC", "F000", "SQ"), ".flac"),
        ("mp3_320", "320k 高品质 MP3", ("MP3_320", "M800", "HQ"), ".mp3"),
        ("mp3_128", "128k 标准 MP3", ("MP3_128", "M500"), ".mp3"),
    ],
    "hires": [
        ("hires", "Hi-Res 无损", ("HI_RES", "HIRES", "RS01", "FLAC_HIRES"), ".flac"),
        ("flac", "FLAC 无损", ("FLAC", "F000", "SQ"), ".flac"),
        ("mp3_320", "320k 高品质 MP3", ("MP3_320", "M800", "HQ"), ".mp3"),
        ("mp3_128", "128k 标准 MP3", ("MP3_128", "M500"), ".mp3"),
    ],
    "flac": [
        ("flac", "FLAC 无损", ("FLAC", "F000", "SQ"), ".flac"),
        ("mp3_320", "320k 高品质 MP3", ("MP3_320", "M800", "HQ"), ".mp3"),
        ("mp3_128", "128k 标准 MP3", ("MP3_128", "M500"), ".mp3"),
    ],
    "mp3_320": [
        ("mp3_320", "320k 高品质 MP3", ("MP3_320", "M800", "HQ"), ".mp3"),
        ("mp3_128", "128k 标准 MP3", ("MP3_128", "M500"), ".mp3"),
    ],
    "mp3_128": [
        ("mp3_128", "128k 标准 MP3", ("MP3_128", "M500"), ".mp3"),
    ],
}

current_play_mode = "local" 
is_local_playing = True    
bgm_paused_by_bot = False
active_lrc_lines = []
active_song_start_ts = 0.0
active_song_base_pos = 0.0

# ================= 工具与核心逻辑 =================
def clean_cache_if_needed():
    try:
        if not os.path.exists(CACHE_DIR):
            return
        max_files = style_config.get("max_cache_files", 100)
        max_size_mb = style_config.get("max_cache_size_mb", 500)
        files = []
        total_size = 0
        for f in os.listdir(CACHE_DIR):
            full_path = os.path.join(CACHE_DIR, f)
            if os.path.isfile(full_path):
                stat = os.stat(full_path)
                files.append({"path": full_path, "mtime": stat.st_mtime, "size": stat.st_size})
                total_size += stat.st_size
        total_size_mb = total_size / (1024 * 1024)
        if len(files) > max_files or total_size_mb > max_size_mb:
            files.sort(key=lambda x: x["mtime"])
            while files and (len(files) > max_files or total_size_mb > max_size_mb):
                oldest = files.pop(0)
                try:
                    os.remove(oldest["path"])
                    total_size_mb -= oldest["size"] / (1024 * 1024)
                    print(f"🗑️ 缓存空间清理，已删除旧歌曲文件: {os.path.basename(oldest['path'])}")
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

    except Exception as e:
        print("缓存管理异常:", e)

def resolve_song_file_type(client, candidate_names):
    global SongFileType
    if SongFileType is None and hasattr(client, "song"):
        try:
            sig = inspect.signature(client.song.get_song_urls)
            for p in sig.parameters.values():
                if p.default is not inspect.Parameter.empty and hasattr(p.default, "__class__") and "FileType" in p.default.__class__.__name__:
                    SongFileType = p.default.__class__
                    break
        except Exception as e:
            print(f"[WARN] 异常已捕获: {e}")

    if SongFileType is None: return None
    members = {k.upper(): getattr(SongFileType, k) for k in dir(SongFileType) if not k.startswith("_")}
    for name in candidate_names:
        key = name.upper()
        if key in members: return members[key]
        key_no_underscore = key.replace("_", "")
        for mk, mv in members.items():
            if mk.replace("_", "") == key_no_underscore: return mv
    return None

async def request_song_url_with_type(client, song_mid, file_type_enum, credential):
    if SongFileInfo is not None:
        req_item = None
        if file_type_enum is not None:
            for field_name in ("file_type", "type", "quality"):
                try:
                    req_item = SongFileInfo(mid=song_mid, **{field_name: file_type_enum})
                    break
                except TypeError: continue
            if req_item is None:
                try: req_item = SongFileInfo(song_mid, file_type_enum)
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

        if req_item is None: req_item = SongFileInfo(mid=song_mid)

        if file_type_enum is not None:
            try:
                sig = inspect.signature(client.song.get_song_urls)
                if "file_type" in sig.parameters:
                    return await client.song.get_song_urls([req_item], file_type=file_type_enum, credential=credential)
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

        return await client.song.get_song_urls([req_item], credential=credential)
    else:
        if file_type_enum is not None:
            for kw in ("file_type", "type", "quality"):
                try:
                    return await client.song.get_song_urls([song_mid], **{kw: file_type_enum}, credential=credential)
                except TypeError: continue
        return await client.song.get_song_urls([song_mid], credential=credential)

def detect_ext_from_url(play_url, default_ext=".mp3"):
    if not play_url: return default_ext
    path_part = play_url.split("?", 1)[0].lower()
    for ext in (".flac", ".m4a", ".ogg", ".mp3", ".wav", ".ape"):
        if path_part.endswith(ext): return ext
    return default_ext

def find_cached_file_for_tier(song_mid, tier_key):
    if not song_mid: return None
    for ext in (".flac", ".mp3", ".m4a", ".ogg", ".wav"):
        candidate = os.path.join(CACHE_DIR, f"{song_mid}_{tier_key}{ext}")
        if os.path.exists(candidate):
            if os.path.getsize(candidate) > 100 * 1024: return candidate
            else:
                try: os.remove(candidate)
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

    if tier_key == "mp3_128":
        legacy = os.path.join(CACHE_DIR, f"{song_mid}.mp3")
        if os.path.exists(legacy):
            if os.path.getsize(legacy) > 100 * 1024: return legacy
            else:
                try: os.remove(legacy)
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")

    return None


# ==================== 本地缓存检查与损坏文件清理 ====================
def check_local_song_exists(download_dir: str, title: str, artist: str, min_size_kb: int = 100) -> tuple:
    """检查本地是否已有该歌曲，且文件完整可播放。返回: (是否存在可用文件, 文件路径)"""
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
    safe_artist = "".join(c for c in artist if c not in r'\/:*?"<>|').strip()

    # 尝试精确匹配 "歌名 - 歌手.ext"
    for ext in [".flac", ".mp3", ".ogg", ".m4a", ".wav"]:
        filename = f"{safe_title} - {safe_artist}{ext}"
        filepath = os.path.join(download_dir, filename)
        if os.path.exists(filepath):
            size_kb = os.path.getsize(filepath) / 1024
            if size_kb >= min_size_kb:
                # 尝试用 pygame 验证文件可读性
                try:
                    if pygame.mixer.get_init():
                        pygame.mixer.music.load(filepath)
                        print(f"[INFO] 本地缓存命中: {os.path.basename(filepath)} ({size_kb:.1f}MB)")
                        return True, filepath
                except Exception as e:
                    print(f"[WARN] 本地文件无法加载({type(e).__name__})，判定为损坏: {filepath}")
                    try:
                        os.remove(filepath)
                        print(f"[INFO] 已删除损坏文件: {os.path.basename(filepath)}")
                    except Exception as e2:
                        print(f"[WARN] 删除损坏文件失败: {e2}")
                    continue

    # 模糊匹配：在目录中查找包含歌名关键词的文件
    if os.path.isdir(download_dir):
        for f in os.listdir(download_dir):
            filepath = os.path.join(download_dir, f)
            if not os.path.isfile(filepath):
                continue
            # 检查文件大小
            size_kb = os.path.getsize(filepath) / 1024
            if size_kb < min_size_kb:
                # 文件过小，判定为残片，删除
                try:
                    os.remove(filepath)
                    print(f"[INFO] 删除残片({size_kb:.1f}KB): {f}")
                except Exception as e:
                    print(f"[WARN] 删除残片失败: {e}")
                continue
            # 模糊匹配文件名（检查歌名关键词是否出现在文件名中）
            if title and title in f:
                try:
                    if pygame.mixer.get_init():
                        pygame.mixer.music.load(filepath)
                        print(f"[INFO] 本地缓存命中(模糊匹配): {os.path.basename(filepath)} ({size_kb:.1f}MB)")
                        return True, filepath
                except Exception:
                    try:
                        os.remove(filepath)
                        print(f"[INFO] 已删除损坏文件: {os.path.basename(filepath)}")
                    except Exception:
                        pass
                    continue

    return False, None


def clean_corrupted_files(download_dir: str, min_size_kb: int = 100) -> int:
    """扫描下载目录，删除所有损坏/不完整的音频文件。返回: 删除的文件数量"""
    if not os.path.isdir(download_dir):
        return 0

    valid_exts = {".flac", ".mp3", ".ogg", ".m4a", ".wav"}
    removed_count = 0

    for item in os.listdir(download_dir):
        filepath = os.path.join(download_dir, item)
        if not os.path.isfile(filepath):
            continue
        if os.path.splitext(item)[1].lower() not in valid_exts:
            continue

        size_kb = os.path.getsize(filepath) / 1024

        # 过小的文件直接删除
        if size_kb < min_size_kb:
            try:
                os.remove(filepath)
                print(f"[CLEAN] 删除残片({size_kb:.1f}KB): {item}")
                removed_count += 1
            except Exception as e:
                print(f"[WARN] 删除失败: {item} - {e}")
            continue

        # 尝试加载验证
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.load(filepath)
        except Exception:
            try:
                os.remove(filepath)
                print(f"[CLEAN] 删除损坏文件: {item}")
                removed_count += 1
            except Exception as e:
                print(f"[WARN] 删除失败: {item} - {e}")

    if removed_count > 0:
        print(f"[INFO] 批量清理完成，共删除 {removed_count} 个损坏文件")
    return removed_count

def parse_lrc(lrc_text):
    if not lrc_text or not isinstance(lrc_text, str): return []
    lrc_text = html.unescape(lrc_text)
    lines = []
    pattern = re.compile(r'\[(\d{2,}):(\d{2})(?:\.(\d{1,3}))?\](.*)')
    for raw_line in lrc_text.splitlines():
        m = pattern.match(raw_line.strip())
        if m:
            minutes = int(m.group(1)); seconds = int(m.group(2))
            frac = m.group(3) or "0"; ms = int(frac.ljust(3, '0')[:3])
            total_sec = minutes * 60 + seconds + ms / 1000.0
            content = m.group(4).strip()
            if content and content != "//": lines.append((total_sec, content))
    lines.sort(key=lambda x: x[0])
    return lines

def get_current_lyric_state(lrc_lines, elapsed_sec):
    if not lrc_lines: return {"lines": [], "all_lines": [], "active_idx": -1}
    idx = -1
    for i, (t, _) in enumerate(lrc_lines):
        if elapsed_sec >= t: idx = i
        else: break
    if idx == -1: idx = 0

    prev_count = style_config["lyric"].get("lines_prev", 2)
    next_count = style_config["lyric"].get("lines_next", 2)
    start_idx = max(0, idx - prev_count)
    end_idx = min(len(lrc_lines), idx + next_count + 1)

    result = []
    for i in range(start_idx, end_idx):
        is_active = (i == idx)
        result.append({"text": lrc_lines[i][1], "active": is_active})

    all_lines = [line_text for _, line_text in lrc_lines]
    return {"lines": result, "all_lines": all_lines, "active_idx": idx}

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

def extract_song_info(search_res):
    if not search_res: return None, None, None, None
    try:
        songs = None
        if hasattr(search_res, 'song'):
            song_attr = search_res.song
            if isinstance(song_attr, list): songs = song_attr
            elif hasattr(song_attr, 'song'): songs = song_attr.song
            elif isinstance(song_attr, dict) and 'song' in song_attr: songs = song_attr['song']
        if not songs and hasattr(search_res, 'songs'): songs = search_res.songs
        if not songs or not isinstance(songs, list) or len(songs) == 0: return None, None, None, None
        first_song_obj = songs[0]
        mid = getattr(first_song_obj, 'mid', None)
        name = getattr(first_song_obj, 'name', None)
        singer_name = "未知歌手"
        singer_list = getattr(first_song_obj, 'singer', [])
        if singer_list: singer_name = getattr(singer_list[0], 'name', "未知歌手")
        return mid, name, singer_name, first_song_obj
    except Exception: return None, None, None, None

def extract_url(url_res, cdn=""):
    if not url_res: return None
    try:
        if hasattr(url_res, 'data') and isinstance(url_res.data, list):
            if not cdn and hasattr(url_res, 'sip') and url_res.sip: cdn = url_res.sip[0]
            for info in url_res.data:
                purl = getattr(info, 'purl', None) or getattr(info, 'url', None)
                if purl:
                    if purl.startswith('http'): return purl
                    if cdn: return f"{cdn.rstrip('/')}/{purl.lstrip('/')}"
        if isinstance(url_res, dict):
            for val in url_res.values():
                if isinstance(val, str) and val.startswith('http'): return val
        if hasattr(url_res, 'urls') and len(url_res.urls) > 0: return getattr(url_res.urls[0], 'url', None)
    except Exception as e:
        print(f"[WARN] 异常已捕获: {e}")

    return None

def get_default_browser_path():
    """探测本机 Edge / Chrome 的安装路径，返回 (类型, 路径) 或 None。
    用于打包成 exe 后在他人电脑上显式告诉 Selenium 浏览器位置，避免无限报
    "浏览器启动失败"。优先 Edge（Win10/11 基本自带），其次 Chrome。"""
    import platform
    if platform.system() != "Windows":
        return None
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in edge_paths:
        if p and os.path.exists(p):
            return ("edge", p)
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in chrome_paths:
        if p and os.path.exists(p):
            return ("chrome", p)
    return None


def start_driver(log_fn=None):
    """启动浏览器驱动：本地驱动优先（免联网，最稳），其次交给 Selenium Manager 自动管理。

    关键：所有启动尝试的真实异常都会通过 log_fn 打印到 OBS 日志区，便于定位
    究竟是驱动版本不匹配、驱动缺失还是浏览器缺失；--windowed 打包下 print 是看不到的，
    因此必须走 app_instance.log 才能让用户看到真正报错。
    """
    def _log(msg):
        if log_fn:
            try:
                log_fn(msg)
                return
            except Exception:
                pass
        try:
            print(msg)
        except Exception:
            pass

    edge_driver_path = os.path.join(BASE_DIR, "msedgedriver.exe")
    chrome_driver_path = os.path.join(BASE_DIR, "chromedriver.exe")
    browser = get_default_browser_path()

    def make_edge_opts():
        o = EdgeOptions()
        if browser and browser[0] == "edge":
            o.binary_location = browser[1]
        o.add_argument("--window-size=900,650")
        o.add_argument("--disable-gpu")
        o.add_argument("--no-sandbox")
        o.add_argument("--disable-dev-shm-usage")
        try:
            o.add_experimental_option("excludeSwitches", ["enable-logging"])
        except Exception:
            pass
        return o

    def make_chrome_opts():
        o = ChromeOptions()
        if browser and browser[0] == "chrome":
            o.binary_location = browser[1]
        o.add_argument("--window-size=900,650")
        o.add_argument("--disable-gpu")
        o.add_argument("--no-sandbox")
        o.add_argument("--disable-dev-shm-usage")
        try:
            o.add_experimental_option("excludeSwitches", ["enable-logging"])
        except Exception:
            pass
        return o

    if not browser:
        _log("[WARN] 未在常见安装路径找到 Edge/Chrome，将尝试由 Selenium Manager 自动处理。")
    _log("[INFO] Edge 本地驱动: " + ("已找到" if os.path.exists(edge_driver_path) else "未放置") +
         " | Chrome 本地驱动: " + ("已找到" if os.path.exists(chrome_driver_path) else "未放置"))

    # 尝试顺序：Edge 本地驱动 -> Edge 自动管理 -> Chrome 本地驱动 -> Chrome 自动管理
    plans = [
        ("Edge(本地驱动)", os.path.exists(edge_driver_path),
         lambda: webdriver.Edge(service=EdgeService(executable_path=edge_driver_path), options=make_edge_opts())),
        ("Edge(自动管理)", True,
         lambda: webdriver.Edge(options=make_edge_opts())),
        ("Chrome(本地驱动)", os.path.exists(chrome_driver_path),
         lambda: webdriver.Chrome(service=ChromeService(executable_path=chrome_driver_path), options=make_chrome_opts())),
        ("Chrome(自动管理)", True,
         lambda: webdriver.Chrome(options=make_chrome_opts())),
    ]

    last_err = None
    last_err_type = "None"
    for name, available, fn in plans:
        if not available:
            continue
        try:
            drv = fn()
            _log("[OK] 已通过 " + name + " 成功启动浏览器。")
            return drv
        except Exception as e:
            last_err = e
            last_err_type = type(e).__name__
            _log("[WARN] " + name + " 启动失败: " + last_err_type + ": " + str(e))

    _log("[ERR] 所有浏览器启动方式均失败，最后错误: " + last_err_type + ": " + str(last_err))
    return None


# ================= B站 与 QQ音乐 登录 =================
def bilibili_auto_login(app_instance):
    app_instance.log("正在启动浏览器进行 B站 登录...")
    driver = start_driver(app_instance.log)
    if not driver:
        app_instance.log("❌ 浏览器启动失败，请检查是否安装了 Edge 或 Chrome")
        return

    try:
        driver.get("https://passport.bilibili.com/login")
        app_instance.log("👉 请在弹出浏览器中扫码/登录 B站，成功后保持浏览器打开。")
    except Exception as e:
        app_instance.log(f"❌ 打开 B站登录页面失败：{type(e).__name__}: {e}")
        try: driver.quit()
        except Exception:
            pass

        return

    def wait_for_bili():
        try:
            cookie_dict = {}
            logged_in = False
            for _ in range(180):
                time.sleep(1)
                try:
                    cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
                    if cookie_dict.get("SESSDATA") and cookie_dict.get("DedeUserID"):
                        logged_in = True
                        break
                    if "www.bilibili.com" not in driver.current_url:
                        driver.get("https://www.bilibili.com/")
                        time.sleep(1)
                        cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
                        if cookie_dict.get("SESSDATA") and cookie_dict.get("DedeUserID"):
                            logged_in = True
                            break
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")


            if not logged_in:
                app_instance.log("❌ 等待登录超时。")
                return

            cookie_names = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4"]
            cookie_str = "; ".join(f"{name}={cookie_dict[name]}" for name in cookie_names if cookie_dict.get(name))
            uid = str(cookie_dict.get("DedeUserID", "")).strip()
            app_instance.log("✅ 已读取 B站登录 Cookie，正在自动查询直播间号...")

            common_headers = {"Cookie": cookie_str, "User-Agent": "Mozilla/5.0", "Referer": "https://live.bilibili.com/"}
            room_id = ""
            endpoints = [
                "https://api.live.bilibili.com/xlive/web-ucenter/v1/bind/get_live_info",
                f"https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld?mid={uid}"
            ]
            for url in endpoints:
                try:
                    req = urllib.request.Request(url, headers=common_headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode())
                        payload = data.get("data") or {}
                        candidates = [payload.get("room_id"), payload.get("roomid"), payload.get("room_info", {}).get("room_id")]
                        candidate = next((str(x) for x in candidates if x not in (None, "", 0, "0")), "")
                        if data.get("code") == 0 and candidate:
                            room_id = candidate
                            break
                except Exception as e:
                    print(f"[WARN] 异常已捕获: {e}")


            config = {}
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f: config = json.load(f)
                except Exception:
                    pass

            config["bili_cookie"] = cookie_str
            if room_id: config["room_id"] = room_id

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)

            if room_id:
                app_instance.log(f"✅ 自动获取直播间号成功：{room_id}")
                result_message = f"B站 Cookie 和直播间号均已保存。\n直播间号：{room_id}\n\n请关闭并重新打开软件以应用配置。"
            else:
                app_instance.log("❌ 未能自动获取直播间号，请手动在 config.json 中填写 room_id。")
                result_message = "Cookie 已保存，但未能自动获取直播间号。请手动在 config.json 中填写 room_id。"

            app_instance.root.after(0, lambda: app_instance.update_account_status())
            app_instance.root.after(0, lambda msg=result_message: messagebox.showinfo("B站登录结果", msg))

        except Exception as e:
            app_instance.log(f"❌ B站登录处理失败：{type(e).__name__}: {e}")
        finally:
            try: driver.quit()
            except Exception:
                pass


    threading.Thread(target=wait_for_bili, daemon=True).start()

def qq_scan_login(app_instance):
    app_instance.log("正在启动浏览器登录 QQ音乐...")
    driver = start_driver(app_instance.log)
    if not driver:
        app_instance.log("❌ 浏览器启动失败")
        return

    driver.get("https://y.qq.com")
    app_instance.log("👉 请在浏览器中扫码登录 QQ音乐。")

    def wait_for_qq():
        for _ in range(120):
            time.sleep(1)
            try:
                cookies = driver.get_cookies()
                cookie_dict = {c['name']: c['value'] for c in cookies}
                musicid_str = cookie_dict.get('uin', '').lstrip('oO0')
                musickey = cookie_dict.get('qm_keyst') or cookie_dict.get('qqmusic_key') or cookie_dict.get('p_skey')
                if musicid_str and musickey:
                    global qq_credential
                    qq_credential = Credential(musicid=int(musicid_str), musickey=musickey)
                    save_credential(qq_credential)
                    app_instance.log("✅ 扫码成功！已绑定 VIP QQ 账号。")
                    app_instance.root.after(0, lambda: app_instance.update_account_status())
                    driver.quit()
                    return
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

        driver.quit()
    threading.Thread(target=wait_for_qq, daemon=True).start()

def save_credential(cred):
    with open(CREDENTIAL_FILE, "w", encoding="utf-8") as f: json.dump({"musicid": cred.musicid, "musickey": cred.musickey}, f)

def load_credential():
    global qq_credential
    if os.path.exists(CREDENTIAL_FILE):
        with open(CREDENTIAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            qq_credential = Credential(musicid=data["musicid"], musickey=data["musickey"])
            return True
    return False

def find_qqmusic_path():
    drives = ['C:', 'D:', 'E:', 'F:']
    paths = [r"\Program Files\Tencent\QQMusic\QQMusic.exe", r"\Program Files (x86)\Tencent\QQMusic\QQMusic.exe", r"\QQMusic\QQMusic.exe", r"\Tencent\QQMusic\QQMusic.exe"]
    for d in drives:
        for p in paths:
            if os.path.exists(d + p): return d + p
    return ""

# ================= OBS 网页渲染 =================
HTML_CONTENT = """
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>OBS 源</title>
<style>
:root { 
    --font-playing: 'Microsoft YaHei', sans-serif; 
    --font-lyric: 'Microsoft YaHei', sans-serif; 
    --font-list: 'Microsoft YaHei', sans-serif;
    --lyric-font-size: 28px;
    --lyric-color: #FFE600;
    --lyric-font-weight: normal;
    --lyric-align: center;
    --lyric-origin: center center;
}
body {background-color: transparent;margin: 0;padding: 20px;font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'PingFang SC', 'Microsoft YaHei', sans-serif;overflow: hidden;-webkit-font-smoothing: antialiased;}
.hidden { display: none !important; }
.system-box {font-family: var(--font-playing); margin-bottom: 10px; text-shadow: 1px 1px 3px rgba(0,0,0,0.85); }
.lyric-box {
    margin-bottom: 16px;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: var(--lyric-align);
    text-align: var(--lyric-align);
}
ul {list-style: none;padding: 0;margin: 0;}
li {font-family: var(--font-list); margin-bottom: 10px; text-shadow: 1px 1px 2px rgba(0,0,0,0.6); }
.empty {font-family: var(--font-list); color: #AAAAAA; text-shadow: 1px 1px 2px rgba(0,0,0,0.5); }

/* 纯歌词/综合挂件基础样式 */
.lyric-line {
    font-family: var(--font-lyric);
    font-size: var(--lyric-font-size);
    font-weight: var(--lyric-font-weight);
    color: var(--lyric-color);
    text-shadow: 1px 1px 3px rgba(0,0,0,0.9);
    padding: 4px 0;
    opacity: 0.5;
    min-height: 1.2em;
    line-height: 1.4;
}
.lyric-line.active {
    font-weight: bold;
    opacity: 1;
}

/* 独立纯歌词模式 */
body.lyric-only-mode {
    display: flex;
    flex-direction: column;
    justify-content: center;
    height: 100vh;
    padding: 0;
    box-sizing: border-box;
    overflow: hidden;
}

/* 静态非滚动模式 */
body[data-lyric-effect="static"] .lyric-box {
    margin-bottom: 0;
    width: 100%;
    height: auto;
    display: flex;
    flex-direction: column;
    align-items: var(--lyric-align);
    text-align: var(--lyric-align);
    overflow: visible;
    -webkit-mask-image: none;
    mask-image: none;
}
body[data-lyric-effect="static"] .lyric-line {
    font-size: calc(var(--lyric-font-size) * 1.15);
    padding: 4px 0;
    opacity: 0.5;
    filter: none;
    transform: none;
    transition: none;
    text-shadow: 1px 1px 3px rgba(0,0,0,0.9);
}
body[data-lyric-effect="static"] .lyric-line.active {
    font-weight: bold;
    opacity: 1;
    text-shadow: 1px 1px 3px rgba(0,0,0,0.9);
}

/* 动效遮罩容器 */
body[data-lyric-effect="apple_blur"] .lyric-box,
body[data-lyric-effect="apple_hd"] .lyric-box {
    position: relative;
    width: 100%;
    height: 100vh;
    margin-bottom: 0;
    overflow: hidden;
    display: block;
}
body[data-lyric-effect="apple_blur"] .lyric-box {
    -webkit-mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.85) 14%, rgba(0,0,0,1) 28%, rgba(0,0,0,1) 72%, rgba(0,0,0,0.85) 86%, transparent 100%);
    mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.85) 14%, rgba(0,0,0,1) 28%, rgba(0,0,0,1) 72%, rgba(0,0,0,0.85) 86%, transparent 100%);
}
body[data-lyric-effect="apple_hd"] .lyric-box {
    -webkit-mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,1) 8%, rgba(0,0,0,1) 92%, transparent 100%);
    mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,1) 8%, rgba(0,0,0,1) 92%, transparent 100%);
}

/* 平滑滚动轨道 */
.lyric-track {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: var(--lyric-align);
    text-align: var(--lyric-align);
    transition: transform 0.65s cubic-bezier(0.22, 1, 0.36, 1);
}
body[data-lyric-effect="apple_blur"] .lyric-track {
    will-change: transform;
}
.lyric-track.no-transition {
    transition: none !important;
}

/* 苹果景深滚动 (柔光) */
body[data-lyric-effect="apple_blur"] .lyric-line {
    font-size: calc(var(--lyric-font-size) * 1.15);
    line-height: 1.42;
    padding: 10px 6%;
    box-sizing: border-box;
    max-width: 100%;
    word-break: break-word;
    transform-origin: var(--lyric-origin);
    will-change: transform, opacity, filter;
    transition:
        transform 0.65s cubic-bezier(0.22, 1, 0.36, 1),
        opacity 0.55s cubic-bezier(0.22, 1, 0.36, 1),
        filter 0.55s cubic-bezier(0.22, 1, 0.36, 1),
        text-shadow 0.55s ease;
    text-shadow: 0 2px 10px rgba(0,0,0,0.75);
}
body[data-lyric-effect="apple_blur"] .lyric-line.active {
    font-weight: 800;
    opacity: 1;
    filter: blur(0px);
    transform: scale(1.08) translateY(0px);
    text-shadow: 0 0 20px rgba(255, 255, 255, 0.32), 0 4px 14px rgba(0, 0, 0, 0.9);
}

/* 高清平滑滚动 (锐利) */
body[data-lyric-effect="apple_hd"] .lyric-line {
    font-size: calc(var(--lyric-font-size) * 1.12);
    line-height: 1.42;
    padding: 9px 6%;
    box-sizing: border-box;
    max-width: 100%;
    word-break: break-word;
    filter: none !important;
    transition:
        transform 0.62s cubic-bezier(0.22, 1, 0.36, 1),
        opacity 0.5s cubic-bezier(0.22, 1, 0.36, 1);
    text-shadow: 1px 1px 3px rgba(0,0,0,0.95), -1px -1px 2px rgba(0,0,0,0.65), 0 2px 5px rgba(0,0,0,0.85);
}
body[data-lyric-effect="apple_hd"] .lyric-line.active {
    font-size: calc(var(--lyric-font-size) * 1.25);
    font-weight: 800;
    opacity: 1;
    filter: none !important;
    text-shadow: 1px 1px 3px rgba(0,0,0,0.98), -1px -1px 2px rgba(0,0,0,0.75), 0 3px 7px rgba(0,0,0,0.9);
}

/* 综合挂件特有样式调整 */
body.mixed-mode .lyric-box.hidden-lyric { height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: hidden; display: none !important; }
body.mixed-mode .lyric-box { height: 250px; display: block; }
body.playing-only-mode, body.queue-only-mode { display: flex; flex-direction: column; justify-content: center; height: 100vh; padding: 0; box-sizing: border-box; align-items: center; }
body.playing-only-mode .system-box { margin-bottom: 0; }
body.queue-only-mode ul { width: 100%; text-align: center; }
</style></head>
<body>
<div class="system-box" id="sys-playing">🎵 正在播放: 暂无</div>
<div class="lyric-box" id="lyric-container"></div>
<ul id="queue-list"><li class="empty">队列空闲中...</li></ul>
<script>
const path = window.location.pathname;
const isMixed = (path === '/' || path === '' || path === '/index.html');
const isLyric = path.includes('/lyric');
const isPlaying = path.includes('/playing');
const isQueue = path.includes('/queue');

if (isLyric) document.body.classList.add('lyric-only-mode');
if (isPlaying) document.body.classList.add('playing-only-mode');
if (isQueue) document.body.classList.add('queue-only-mode');
if (isMixed) document.body.classList.add('mixed-mode');

if (!isMixed) {
    if (!isPlaying) document.getElementById('sys-playing').style.display = 'none';
    if (!isLyric) document.getElementById('lyric-container').style.display = 'none';
    if (!isQueue) document.getElementById('queue-list').style.display = 'none';
}

let currentSongSignature = ''; 
let lastActiveIdx = -1; 
let lastLayoutKey = ''; 
let lastEffectMode = '';

function updateStaticLyric(lines, align) {
    const container = document.getElementById('lyric-container');
    currentSongSignature = '';
    lastActiveIdx = -1;
    lastLayoutKey = '';
    container.style.textAlign = align;
    if (lines && lines.length > 0) { 
        let html = ''; 
        lines.forEach((l) => { 
            const cls = l.active ? 'lyric-line active' : 'lyric-line'; 
            const txt = l.text || ''; 
            html += `<div class="${cls}">${txt || '&nbsp;'}</div>`; 
        }); 
        container.innerHTML = html; 
    } else { 
        container.innerHTML = ''; 
    }
}

function updateAppleMusicScroll(allLines, activeIdx, style, effectMode, align) {
    const container = document.getElementById('lyric-container'); 
    let track = document.getElementById('lyric-track'); 
    const isEffectChanged = (effectMode !== lastEffectMode);

    if (!track) { 
        container.innerHTML = '<div class="lyric-track no-transition" id="lyric-track"></div>'; 
        track = document.getElementById('lyric-track'); 
    }
    track.style.textAlign = align;

    if (!allLines || allLines.length === 0 || activeIdx < 0) { 
        track.innerHTML = ''; 
        currentSongSignature = ''; 
        lastActiveIdx = -1; 
        lastEffectMode = effectMode; 
        return; 
    }

    const signature = allLines.length + '::' + allLines[0] + '::' + allLines[allLines.length - 1] + '::' + allLines.join('|');
    const isNewSong = (signature !== currentSongSignature);

    if (isNewSong) { 
        currentSongSignature = signature; 
        lastActiveIdx = -1; 
        track.classList.add('no-transition'); 
        track.innerHTML = ''; 
        allLines.forEach((txt) => { 
            const div = document.createElement('div'); 
            div.className = 'lyric-line'; 
            div.textContent = txt || '\u00A0'; 
            track.appendChild(div); 
        }); 
    } else if (isEffectChanged) { 
        track.classList.add('no-transition'); 
    }

    const prevCount = (style.lines_prev !== undefined) ? style.lines_prev : 2; 
    const nextCount = (style.lines_next !== undefined) ? style.lines_next : 2;
    const layoutKey = `${effectMode}_${activeIdx}_${prevCount}_${nextCount}_${style.size}_${style.align}_${style.is_bold}_${window.innerHeight}_${window.innerWidth}`;

    if (!isNewSong && !isEffectChanged && layoutKey === lastLayoutKey) { 
        return; 
    }

    const isStepForward = (!isNewSong && !isEffectChanged && lastActiveIdx >= 0 && activeIdx === lastActiveIdx + 1);
    lastActiveIdx = activeIdx; 
    lastLayoutKey = layoutKey; 
    lastEffectMode = effectMode;

    const children = track.children; 
    const total = children.length; 
    if (total === 0) return;

    const clampedIdx = Math.max(0, Math.min(total - 1, activeIdx)); 
    const minVis = clampedIdx - prevCount; 
    const maxVis = clampedIdx + nextCount;
    const isHD = (effectMode === 'apple_hd');

    for (let i = 0; i < total; i++) {
        const el = children[i]; 
        const dist = i - clampedIdx; 
        const absDist = Math.abs(dist);

        if (isStepForward && i >= minVis - 1 && i <= maxVis + 1) {
            const order = Math.max(0, i - minVis);
            el.style.transitionDelay = `${Math.min(order * 28, 180)}ms`;
        } else {
            el.style.transitionDelay = '0ms';
        }

        if (i === clampedIdx) { 
            el.className = 'lyric-line active'; 
            el.style.opacity = '1'; 
            el.style.pointerEvents = 'auto';
            if (isHD) {
                el.style.filter = 'none';
                el.style.transform = 'translateY(0px)';
            } else {
                el.style.filter = 'blur(0px)';
                el.style.transform = 'scale(1.08) translateY(0px)';
            }
        } else if (i >= minVis && i <= maxVis) { 
            el.className = 'lyric-line'; 
            el.style.pointerEvents = 'auto';
            if (isHD) {
                let opacity = 0.72;
                if (absDist === 2) opacity = 0.52;
                else if (absDist === 3) opacity = 0.36;
                else if (absDist >= 4) opacity = 0.24;
                el.style.opacity = String(opacity);
                el.style.filter = 'none';
                el.style.transform = 'translateY(0px)';
            } else {
                let opacity = 0.58;
                if (absDist === 2) opacity = 0.36;
                else if (absDist === 3) opacity = 0.22;
                else if (absDist >= 4) opacity = 0.14;
                const blurPx = Math.min(absDist * 0.85, 3.6).toFixed(2);
                el.style.opacity = String(opacity);
                el.style.filter = `blur(${blurPx}px)`;
                el.style.transform = 'scale(0.96) translateY(0px)';
            }
        } else { 
            el.className = 'lyric-line'; 
            el.style.opacity = '0'; 
            el.style.pointerEvents = 'none';
            const shiftY = dist < 0 ? -10 : 10;
            if (isHD) {
                el.style.filter = 'none';
                el.style.transform = `translateY(${shiftY}px)`;
            } else {
                el.style.filter = 'blur(5px)';
                el.style.transform = `scale(0.92) translateY(${shiftY}px)`;
            }
        }
    }

    const activeEl = children[clampedIdx];
    if (activeEl) { 
        const viewportH = container.clientHeight || window.innerHeight; 
        const activeCenter = activeEl.offsetTop + activeEl.offsetHeight / 2; 
        const avgLineH = activeEl.offsetHeight || 52;
        const focalY = (viewportH / 2) - ((nextCount - prevCount) * avgLineH * 0.45);
        const targetY = focalY - activeCenter; 
        if (isHD) {
            track.style.transform = `translateY(${Math.round(targetY)}px)`;
        } else {
            track.style.transform = `translate3d(0, ${targetY.toFixed(1)}px, 0)`;
        }
    }

    if (isNewSong || isEffectChanged) { 
        requestAnimationFrame(() => { 
            requestAnimationFrame(() => { 
                if (track) track.classList.remove('no-transition'); 
            }); 
        }); 
    }
}

window.addEventListener('resize', () => {
    lastLayoutKey = '';
});

async function updateData() {
    try {
        const response = await fetch('/api/data'); 
        const data = await response.json(); 
        const cfg = data.style; 
        const root = document.documentElement;

        if (isMixed) {
            root.style.setProperty('--font-playing', cfg.mixed.font_playing);
            root.style.setProperty('--font-lyric', cfg.mixed.font_lyric);
            root.style.setProperty('--font-list', cfg.mixed.font_queue);
            
            const sys = document.getElementById('sys-playing');
            sys.style.fontSize = cfg.mixed.size_playing + 'px'; 
            sys.style.color = cfg.mixed.color_playing;
            sys.style.fontWeight = cfg.mixed.bold_playing ? 'bold' : 'normal';
            sys.classList.toggle('hidden', !cfg.mixed.show_playing);
            const sysText = (data.system_playing && data.system_playing !== "暂无播放") ? ('🎵 正在播放: ' + data.system_playing) : '🎵 正在播放: 暂无';
            sys.innerText = sysText;
            
            const ul = document.getElementById('queue-list');
            ul.style.fontSize = cfg.mixed.size_queue + 'px'; 
            ul.style.color = cfg.mixed.color_queue;
            ul.style.fontWeight = cfg.mixed.bold_queue ? 'bold' : 'normal';
            ul.classList.toggle('hidden', !cfg.mixed.show_queue);
            if (data.list.length === 0) {
                ul.innerHTML = '<li class="empty">队列空闲中...</li>';
            } else {
                let html = '';
                data.list.forEach((item, index) => {
                    let reqStr = item.requester ? `-${item.requester}` : '';
                    html += `<li>${index + 1}. ${item.display_name}${reqStr}</li>`;
                });
                ul.innerHTML = html;
            }

            const lc = document.getElementById('lyric-container');
            lc.style.setProperty('--lyric-font-size', cfg.mixed.size_lyric + 'px');
            lc.style.setProperty('--lyric-color', cfg.mixed.color_lyric);
            lc.style.setProperty('--lyric-font-weight', cfg.mixed.bold_lyric ? 'bold' : 'normal');
            
            if (cfg.mixed.show_lyric) {
                lc.classList.remove('hidden-lyric');
                document.body.setAttribute('data-lyric-effect', cfg.mixed.effect_lyric);
                const mixedStyle = { size: cfg.mixed.size_lyric, lines_prev: cfg.lyric.lines_prev, lines_next: cfg.lyric.lines_next, align: cfg.lyric.align || 'center' };
                if (cfg.mixed.effect_lyric === 'static') updateStaticLyric(data.lyric.lines, cfg.lyric.align || 'center');
                else updateAppleMusicScroll(data.lyric.all_lines, data.lyric.active_idx, mixedStyle, cfg.mixed.effect_lyric, cfg.lyric.align || 'center');
            } else { 
                lc.classList.add('hidden-lyric');
                lc.innerHTML = '';
            }
        } 
        else if (isPlaying) {
            const sys = document.getElementById('sys-playing');
            sys.style.fontFamily = cfg.playing.font;
            sys.style.fontSize = cfg.playing.size + 'px';
            sys.style.color = cfg.playing.color;
            sys.style.fontWeight = cfg.playing.is_bold ? 'bold' : 'normal';
            const txt = data.system_playing;
            sys.innerText = cfg.playing.show_prefix ? ('🎵 正在播放: ' + txt) : txt;
        } 
        else if (isQueue) {
            const ul = document.getElementById('queue-list');
            ul.style.fontFamily = cfg.queue.font;
            ul.style.fontSize = cfg.queue.size + 'px';
            ul.style.color = cfg.queue.color;
            ul.style.fontWeight = cfg.queue.is_bold ? 'bold' : 'normal';
            const max = cfg.queue.max_chars || 999;
            if (data.list.length === 0) ul.innerHTML = '<li class="empty">队列空闲中...</li>';
            else {
                let html = ''; data.list.forEach((item, i) => {
                    let s = `${i+1}. ${item.display_name}${item.requester ? '-'+item.requester : ''}`;
                    if (s.length > max) s = s.substring(0, max) + '...';
                    html += `<li>${s}</li>`;
                }); ul.innerHTML = html;
            }
        } 
        else if (isLyric) {
            root.style.setProperty('--font-lyric', cfg.lyric.font);
            let align = 'center';
            let flexAlign = 'center';
            let origin = 'center center';
            if (cfg.lyric.align === 'left') {
                align = 'left'; flexAlign = 'flex-start'; origin = 'left center';
            } else if (cfg.lyric.align === 'right') {
                align = 'right'; flexAlign = 'flex-end'; origin = 'right center';
            }
            root.style.setProperty('--lyric-align', flexAlign);
            root.style.setProperty('--lyric-origin', origin);

            const lc = document.getElementById('lyric-container');
            lc.style.setProperty('--lyric-font-size', cfg.lyric.size + 'px');
            lc.style.setProperty('--lyric-color', cfg.lyric.color);
            lc.style.setProperty('--lyric-font-weight', cfg.lyric.is_bold ? 'bold' : 'normal');
            document.body.setAttribute('data-lyric-effect', cfg.lyric.effect);
            
            if (cfg.lyric.effect === 'static') updateStaticLyric(data.lyric.lines, align);
            else updateAppleMusicScroll(data.lyric.all_lines, data.lyric.active_idx, cfg.lyric, cfg.lyric.effect, align);
        }
    } catch (e) {}
}
setInterval(updateData, 150); updateData();
</script></body></html>
"""

async def handle_index(request): return web.Response(text=HTML_CONTENT, content_type='text/html')
async def handle_api(request):
    global system_media_info, current_lyric_info
    sys_text = system_media_info.get("title", "暂无播放"); artist = system_media_info.get("artist", "")
    if artist and sys_text != "暂无播放": sys_text += f" - {artist}"
    data = {"current": current_song, "list": playlist, "style": style_config, "system_playing": sys_text, "lyric": current_lyric_info}
    return web.json_response(data)

# ================= 主程序类 =================
class MusicApp:
    def __init__(self, root, config):
        self.root = root; self.config = config
        
        old_style = self.config.get("style_config", {})
        global style_config
        style_config = merge_config(old_style, style_config)
            
        if not self.config.get("qqmusic_path"):
            auto_path = find_qqmusic_path()
            if auto_path: self.config["qqmusic_path"] = auto_path

        self.audio_backend = "none"

        self.root.title(f"控制台 - 房间 {self.config.get('room_id', '未配置')}"); self.root.geometry("780x880")
        self.setup_ui()
        self.download_tasks = {}
        self.thread = threading.Thread(target=self.start_async_loop, daemon=True); self.thread.start()

    def init_audio_engine(self):
        try:
            pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048)
            self.audio_backend = "pygame"
            self.log("✅ 内置无损音频引擎 (Pygame 稳定通道) 已就绪")
            self.update_engine_badge("✅ 驱动: Pygame 本地稳定版", "#2E7D32")
        except Exception as e:
            self.audio_backend = "none"
            self.log(f"❌ 音频通道初始化失败: {e}")
            self.update_engine_badge("❌ 音频驱动未就绪", "#C62828")

    def update_engine_badge(self, text, color):
        def _update():
            if hasattr(self, "lbl_engine_status"):
                self.lbl_engine_status.config(text=text, fg=color)
        self.root.after(0, _update)

    def player_is_busy(self):
        if self.audio_backend == "pygame" and pygame.mixer.get_init():
            return pygame.mixer.music.get_busy()
        return False

    def player_stop(self):
        if self.audio_backend == "pygame" and pygame.mixer.get_init():
            try: pygame.mixer.music.stop()
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")


    def player_get_elapsed(self):
        if self.audio_backend == "pygame" and pygame.mixer.get_init():
            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms >= 0: return pos_ms / 1000.0
        return max(0.0, time.time() - active_song_start_ts)

    async def player_load_and_play(self, file_path):
        def _pg_start():
            try:
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.play()
                return True
            except Exception as e:
                print("pygame 播放异常:", e)
                return False
        success = await asyncio.to_thread(_pg_start)
        await asyncio.sleep(0.4)
        return pygame.mixer.music.get_busy()

    def save_style_config(self):
        self.config["style_config"] = style_config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print("保存配置失败:", e)

    def schedule_save_style(self, event=None):
        if hasattr(self, "_save_timer") and self._save_timer:
            self.root.after_cancel(self._save_timer)
        self._save_timer = self.root.after(500, self.save_style_config)

    def update_account_status(self):
        bili_status = "❌ 未配置 (缺少Cookie或房间号)"
        bili_color = "red"
        if self.config.get("bili_cookie") and self.config.get("room_id"):
            bili_status = f"✅ 已配置 (房间号: {self.config['room_id']})"
            bili_color = "green"
        self.lbl_bili_status.config(text=bili_status, fg=bili_color)

        qq_status = "❌ 未登录"
        qq_color = "red"
        if os.path.exists(CREDENTIAL_FILE):
            try:
                with open(CREDENTIAL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("musicid") and data.get("musickey"):
                        qq_status = f"✅ 已登录 (账号UID: {data['musicid']})"
                        qq_color = "green"
            except Exception:
                pass
        self.lbl_qq_status.config(text=qq_status, fg=qq_color)

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        top_frame = tk.Frame(self.root, bg="#f8f9fa", pady=5, padx=5)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text="📋 浏览器源:", bg="#f8f9fa", font=("微软雅黑", 10, "bold")).pack(side=tk.LEFT, padx=(0,5))
        
        tk.Button(top_frame, text="综合挂件", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080"), bg="#607D8B", fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(top_frame, text="纯歌词", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080/lyric"), bg="#607D8B", fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(top_frame, text="正在播放", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080/playing"), bg="#FF9800", fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(top_frame, text="点歌列表", command=lambda: self.copy_to_clipboard("http://127.0.0.1:8080/queue"), bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=2)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # === Tab 1: 运行日志 ===
        tab_log = tk.Frame(notebook)
        notebook.add(tab_log, text="📝 运行日志")
        self.log_text = scrolledtext.ScrolledText(tab_log, font=("Consolas", 10), bg="#1e1e1e", fg="#00ff00", relief=tk.FLAT)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # === Tab 2: 账号与登录 ===
        tab_account = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_account, text="🔐 账号与登录")
        account_inner = tk.Frame(tab_account, bg="#f0f0f0", padx=20, pady=20)
        account_inner.pack(fill=tk.BOTH, expand=True)

        bili_group = tk.LabelFrame(account_inner, text="B站直播间", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        bili_group.pack(fill=tk.X, pady=10)
        self.lbl_bili_status = tk.Label(bili_group, text="⏳ 检测中...", font=("微软雅黑", 11), bg="#f0f0f0")
        self.lbl_bili_status.pack(anchor="w", padx=10, pady=5)
        tk.Button(bili_group, text="🔄 重新登录 B站", bg="#2196F3", fg="white", font=("微软雅黑", 10, "bold"), command=lambda: bilibili_auto_login(self)).pack(anchor="w", padx=10, pady=(0, 10))

        qq_group = tk.LabelFrame(account_inner, text="QQ音乐账号", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        qq_group.pack(fill=tk.X, pady=10)
        self.lbl_qq_status = tk.Label(qq_group, text="⏳ 检测中...", font=("微软雅黑", 11), bg="#f0f0f0")
        self.lbl_qq_status.pack(anchor="w", padx=10, pady=5)
        tk.Button(qq_group, text="📱 扫码登录 QQ 音乐", bg="#FF9800", fg="white", font=("微软雅黑", 10, "bold"), command=lambda: qq_scan_login(self)).pack(anchor="w", padx=10, pady=(0, 10))
        tk.Button(account_inner, text="🔄 刷新状态", bg="#9E9E9E", fg="white", command=self.update_account_status).pack(pady=10)

        # === Tab 3: 音质与缓存 ===
        tab_basic = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_basic, text="🎵 音质与缓存")
        basic_inner = tk.Frame(tab_basic, bg="#f0f0f0", padx=20, pady=20)
        basic_inner.pack(fill=tk.BOTH, expand=True)

        quality_group = tk.LabelFrame(basic_inner, text="点歌音质", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        quality_group.pack(fill=tk.X, pady=5)
        tk.Label(quality_group, text="首选音质:", bg="#f0f0f0").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        self.var_audio_quality = tk.StringVar(value=QUALITY_UI_MAP.get(style_config.get("audio_quality", "flac"), "FLAC 无损品质 (推荐)"))
        self.combo_quality_top = ttk.Combobox(quality_group, textvariable=self.var_audio_quality, values=list(QUALITY_UI_MAP.values()), state="readonly", width=25)
        self.combo_quality_top.bind("<<ComboboxSelected>>", self.update_audio_quality)
        self.combo_quality_top.grid(row=0, column=1, sticky="w")

        path_group = tk.LabelFrame(basic_inner, text="本地客户端路径", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        path_group.pack(fill=tk.X, pady=5)
        tk.Label(path_group, text="QQ音乐路径:", bg="#f0f0f0").pack(side=tk.LEFT, padx=10, pady=10)
        self.entry_qq_path = tk.Entry(path_group, width=40, font=("微软雅黑", 9))
        self.entry_qq_path.insert(0, self.config.get("qqmusic_path", ""))
        self.entry_qq_path.pack(side=tk.LEFT, padx=5)
        tk.Button(path_group, text="浏览...", command=self.browse_qq_path, bg="#9E9E9E", fg="white").pack(side=tk.LEFT, padx=5)

        cache_group = tk.LabelFrame(basic_inner, text="缓存自动清理限制", bg="#f0f0f0", font=("微软雅黑", 10, "bold"))
        cache_group.pack(fill=tk.X, pady=5)
        tk.Label(cache_group, text="最多保留歌曲数:", bg="#f0f0f0").grid(row=0, column=0, padx=10, pady=5, sticky="e")
        self.entry_max_files = tk.Entry(cache_group, width=10)
        self.entry_max_files.insert(0, str(style_config.get("max_cache_files", 100)))
        self.entry_max_files.grid(row=0, column=1, sticky="w")
        self.entry_max_files.bind("<KeyRelease>", self.update_cache_settings)
        
        tk.Label(cache_group, text="最大占用体积(MB):", bg="#f0f0f0").grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.entry_max_size = tk.Entry(cache_group, width=10)
        self.entry_max_size.insert(0, str(style_config.get("max_cache_size_mb", 500)))
        self.entry_max_size.grid(row=1, column=1, sticky="w")
        self.entry_max_size.bind("<KeyRelease>", self.update_cache_settings)

        # ==========================================
        # Tab 4: 综合挂件设置
        # ==========================================
        tab_mixed = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_mixed, text="🎨 综合挂件")
        mixed_inner = tk.Frame(tab_mixed, bg="#f0f0f0", padx=20, pady=20)
        mixed_inner.pack(fill=tk.BOTH, expand=True)

        self.var_mix_sp = tk.BooleanVar(value=style_config['mixed']['show_playing'])
        self.var_mix_sl = tk.BooleanVar(value=style_config['mixed']['show_lyric'])
        self.var_mix_sq = tk.BooleanVar(value=style_config['mixed']['show_queue'])
        self.var_mix_bp = tk.BooleanVar(value=style_config['mixed']['bold_playing'])
        self.var_mix_bl = tk.BooleanVar(value=style_config['mixed']['bold_lyric'])
        self.var_mix_bq = tk.BooleanVar(value=style_config['mixed']['bold_queue'])

        chk_frame = tk.Frame(mixed_inner, bg="#f0f0f0"); chk_frame.pack(fill=tk.X, pady=5)
        tk.Checkbutton(chk_frame, text="显示【正在播放】", variable=self.var_mix_sp, command=lambda: self.update_mixed("show_playing", self.var_mix_sp.get()), bg="#f0f0f0").pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(chk_frame, text="显示【实时歌词】", variable=self.var_mix_sl, command=lambda: self.update_mixed("show_lyric", self.var_mix_sl.get()), bg="#f0f0f0").pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(chk_frame, text="显示【点歌列表】", variable=self.var_mix_sq, command=lambda: self.update_mixed("show_queue", self.var_mix_sq.get()), bg="#f0f0f0").pack(side=tk.LEFT, padx=5)

        tk.Label(mixed_inner, text="--- 正在播放样式 ---", bg="#f0f0f0", font=("微软雅黑", 9, "bold")).pack(anchor="w", pady=(10,0))
        f1 = tk.Frame(mixed_inner, bg="#f0f0f0"); f1.pack(fill=tk.X, pady=2)
        self.combo_mix_font_playing = ttk.Combobox(f1, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal", width=22)
        self.combo_mix_font_playing.set(style_config['mixed']['font_playing'])
        self.combo_mix_font_playing.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("font_playing", self.combo_mix_font_playing.get()))
        self.combo_mix_font_playing.bind("<KeyRelease>", lambda e: self.update_mixed("font_playing", self.combo_mix_font_playing.get()))
        self.combo_mix_font_playing.pack(side=tk.LEFT, padx=2)
        tk.Button(f1, text="颜色", command=lambda: self.pick_mixed("color_playing", "lbl_mix_color_playing"), bg="#e0e0e0").pack(side=tk.LEFT, padx=2)
        self.lbl_mix_color_playing = tk.Label(f1, text=style_config['mixed']['color_playing'], bg=style_config['mixed']['color_playing'], width=7)
        self.lbl_mix_color_playing.pack(side=tk.LEFT, padx=2)
        tk.Label(f1, text="字号:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(3,1))
        scale_sp = tk.Scale(f1, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_mixed("size_playing", int(e)), length=80, bg="#f0f0f0")
        scale_sp.set(style_config['mixed']['size_playing'])
        scale_sp.pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f1, text="加粗", variable=self.var_mix_bp, command=lambda: self.update_mixed("bold_playing", self.var_mix_bp.get()), bg="#f0f0f0").pack(side=tk.LEFT)

        tk.Label(mixed_inner, text="--- 实时歌词样式 ---", bg="#f0f0f0", font=("微软雅黑", 9, "bold")).pack(anchor="w", pady=(10,0))
        f2 = tk.Frame(mixed_inner, bg="#f0f0f0"); f2.pack(fill=tk.X, pady=2)
        self.combo_mix_font_lyric = ttk.Combobox(f2, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal", width=22)
        self.combo_mix_font_lyric.set(style_config['mixed']['font_lyric'])
        self.combo_mix_font_lyric.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("font_lyric", self.combo_mix_font_lyric.get()))
        self.combo_mix_font_lyric.bind("<KeyRelease>", lambda e: self.update_mixed("font_lyric", self.combo_mix_font_lyric.get()))
        self.combo_mix_font_lyric.pack(side=tk.LEFT, padx=2)
        tk.Button(f2, text="颜色", command=lambda: self.pick_mixed("color_lyric", "lbl_mix_color_lyric"), bg="#e0e0e0").pack(side=tk.LEFT, padx=2)
        self.lbl_mix_color_lyric = tk.Label(f2, text=style_config['mixed']['color_lyric'], bg=style_config['mixed']['color_lyric'], width=7)
        self.lbl_mix_color_lyric.pack(side=tk.LEFT, padx=2)
        tk.Label(f2, text="字号:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(3,1))
        scale_sl = tk.Scale(f2, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_mixed("size_lyric", int(e)), length=80, bg="#f0f0f0")
        scale_sl.set(style_config['mixed']['size_lyric'])
        scale_sl.pack(side=tk.LEFT, padx=2)
        eff_mix = ttk.Combobox(f2, values=["高清平滑滚动", "苹果景深滚动", "无滚动 (静态)"], state="readonly", width=11)
        eff_mix_map = {"apple_hd": "高清平滑滚动", "apple_blur": "苹果景深滚动", "static": "无滚动 (静态)"}
        eff_mix.set(eff_mix_map.get(style_config['mixed']['effect_lyric'], "高清平滑滚动"))
        eff_mix.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("effect_lyric", {"高清平滑滚动":"apple_hd", "苹果景深滚动":"apple_blur", "无滚动 (静态)":"static"}[eff_mix.get()]))
        eff_mix.pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f2, text="加粗", variable=self.var_mix_bl, command=lambda: self.update_mixed("bold_lyric", self.var_mix_bl.get()), bg="#f0f0f0").pack(side=tk.LEFT)

        tk.Label(mixed_inner, text="--- 点歌列表样式 ---", bg="#f0f0f0", font=("微软雅黑", 9, "bold")).pack(anchor="w", pady=(10,0))
        f3 = tk.Frame(mixed_inner, bg="#f0f0f0"); f3.pack(fill=tk.X, pady=2)
        self.combo_mix_font_queue = ttk.Combobox(f3, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal", width=22)
        self.combo_mix_font_queue.set(style_config['mixed']['font_queue'])
        self.combo_mix_font_queue.bind("<<ComboboxSelected>>", lambda e: self.update_mixed("font_queue", self.combo_mix_font_queue.get()))
        self.combo_mix_font_queue.bind("<KeyRelease>", lambda e: self.update_mixed("font_queue", self.combo_mix_font_queue.get()))
        self.combo_mix_font_queue.pack(side=tk.LEFT, padx=2)
        tk.Button(f3, text="颜色", command=lambda: self.pick_mixed("color_queue", "lbl_mix_color_queue"), bg="#e0e0e0").pack(side=tk.LEFT, padx=2)
        self.lbl_mix_color_queue = tk.Label(f3, text=style_config['mixed']['color_queue'], bg=style_config['mixed']['color_queue'], width=7)
        self.lbl_mix_color_queue.pack(side=tk.LEFT, padx=2)
        tk.Label(f3, text="字号:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(3,1))
        scale_sq = tk.Scale(f3, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_mixed("size_queue", int(e)), length=80, bg="#f0f0f0")
        scale_sq.set(style_config['mixed']['size_queue'])
        scale_sq.pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f3, text="加粗", variable=self.var_mix_bq, command=lambda: self.update_mixed("bold_queue", self.var_mix_bq.get()), bg="#f0f0f0").pack(side=tk.LEFT)

        # ==========================================
        # Tab 5: 纯歌词源设置（已同步完整对齐参数与动效控制，移除了透明度配置）
        # ==========================================
        tab_lyric = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_lyric, text="🎤 纯歌词源")
        lyric_inner = tk.Frame(tab_lyric, bg="#f0f0f0", padx=20, pady=20)
        lyric_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(lyric_inner, text="字体 (可手动输入):", bg="#f0f0f0").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_lyric_font = ttk.Combobox(lyric_inner, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif", "'KaiTi', sans-serif"], state="normal")
        self.combo_lyric_font.set(style_config['lyric']['font'])
        self.combo_lyric_font.bind("<<ComboboxSelected>>", lambda e: self.update_lyric("font", self.combo_lyric_font.get()))
        self.combo_lyric_font.bind("<KeyRelease>", lambda e: self.update_lyric("font", self.combo_lyric_font.get()))
        self.combo_lyric_font.grid(row=0, column=1, pady=5, sticky="w")

        tk.Button(lyric_inner, text="修改歌词颜色", command=lambda: self.pick_lyric("color"), bg="#e0e0e0").grid(row=1, column=0, padx=5, pady=5)
        self.lbl_lyric_color = tk.Label(lyric_inner, text=style_config['lyric']['color'], bg=style_config['lyric']['color'], width=10)
        self.lbl_lyric_color.grid(row=1, column=1, sticky="w")

        tk.Label(lyric_inner, text="歌词字号:", bg="#f0f0f0").grid(row=2, column=0, padx=5, sticky="e")
        self.scale_lyric_size = tk.Scale(lyric_inner, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_lyric("size", int(e)))
        self.scale_lyric_size.set(style_config['lyric']['size'])
        self.scale_lyric_size.grid(row=2, column=1, sticky="w")

        # 部署：对齐方式选择组件
        tk.Label(lyric_inner, text="对齐方式:", bg="#f0f0f0").grid(row=3, column=0, padx=5, sticky="e")
        self.combo_lyric_align = ttk.Combobox(lyric_inner, values=["居中对齐", "左对齐", "右对齐"], state="readonly")
        align_map = {"center": "居中对齐", "left": "左对齐", "right": "右对齐"}
        self.combo_lyric_align.set(align_map.get(style_config['lyric'].get("align", "center"), "居中对齐"))
        self.combo_lyric_align.bind("<<ComboboxSelected>>", self.update_lyric_align)
        self.combo_lyric_align.grid(row=3, column=1, sticky="w", pady=5)

        tk.Label(lyric_inner, text="滚动效果:", bg="#f0f0f0").grid(row=4, column=0, padx=5, sticky="e")
        self.combo_effect = ttk.Combobox(lyric_inner, values=["高清平滑滚动 (锐利)", "苹果景深滚动 (柔光)", "无滚动 (经典静态)"], state="readonly")
        eff_map = {"apple_hd": "高清平滑滚动 (锐利)", "apple_blur": "苹果景深滚动 (柔光)", "static": "无滚动 (经典静态)"}
        self.combo_effect.set(eff_map.get(style_config['lyric']['effect'], "高清平滑滚动 (锐利)"))
        self.combo_effect.bind("<<ComboboxSelected>>", self.update_effect)
        self.combo_effect.grid(row=4, column=1, sticky="w", pady=5)

        tk.Label(lyric_inner, text="上方已播放行数:", bg="#f0f0f0").grid(row=5, column=0, padx=5, sticky="e")
        self.scale_lyric_prev = tk.Scale(lyric_inner, from_=0, to=5, orient=tk.HORIZONTAL, command=lambda e: self.update_lyric("lines_prev", int(e)))
        self.scale_lyric_prev.set(style_config['lyric']['lines_prev'])
        self.scale_lyric_prev.grid(row=5, column=1, sticky="w")

        tk.Label(lyric_inner, text="下方未播放行数:", bg="#f0f0f0").grid(row=6, column=0, padx=5, sticky="e")
        self.scale_lyric_next = tk.Scale(lyric_inner, from_=1, to=8, orient=tk.HORIZONTAL, command=lambda e: self.update_lyric("lines_next", int(e)))
        self.scale_lyric_next.set(style_config['lyric']['lines_next'])
        self.scale_lyric_next.grid(row=6, column=1, sticky="w")

        tk.Label(lyric_inner, text="纯音乐提示语:", bg="#f0f0f0").grid(row=7, column=0, padx=5, sticky="e")
        self.entry_pure_music = tk.Entry(lyric_inner, width=25)
        self.entry_pure_music.insert(0, style_config['lyric']['pure_text'])
        self.entry_pure_music.grid(row=7, column=1, sticky="w", pady=5)
        self.entry_pure_music.bind("<KeyRelease>", lambda e: self.update_lyric("pure_text", self.entry_pure_music.get()))

        self.var_lyric_bold = tk.BooleanVar(value=style_config['lyric']['is_bold'])
        tk.Checkbutton(lyric_inner, text="字体加粗", variable=self.var_lyric_bold, command=lambda: self.update_lyric("is_bold", self.var_lyric_bold.get()), bg="#f0f0f0").grid(row=8, column=1, sticky="w", pady=5)

        # ==========================================
        # Tab 6: 正在播放源设置
        # ==========================================
        tab_playing = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_playing, text="📺 正在播放源")
        playing_inner = tk.Frame(tab_playing, bg="#f0f0f0", padx=20, pady=20)
        playing_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(playing_inner, text="字体 (可手动输入):", bg="#f0f0f0").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_playing_font = ttk.Combobox(playing_inner, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal")
        self.combo_playing_font.set(style_config['playing']['font'])
        self.combo_playing_font.bind("<<ComboboxSelected>>", lambda e: self.update_playing("font", self.combo_playing_font.get()))
        self.combo_playing_font.bind("<KeyRelease>", lambda e: self.update_playing("font", self.combo_playing_font.get()))
        self.combo_playing_font.grid(row=0, column=1, pady=5, sticky="w")

        tk.Button(playing_inner, text="修改颜色", command=lambda: self.pick_playing("color"), bg="#e0e0e0").grid(row=1, column=0, padx=5, pady=5)
        self.lbl_playing_color = tk.Label(playing_inner, text=style_config['playing']['color'], bg=style_config['playing']['color'], width=10)
        self.lbl_playing_color.grid(row=1, column=1, sticky="w")

        tk.Label(playing_inner, text="字号:", bg="#f0f0f0").grid(row=2, column=0, padx=5, sticky="e")
        self.scale_playing_size = tk.Scale(playing_inner, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_playing("size", int(e)))
        self.scale_playing_size.set(style_config['playing']['size'])
        self.scale_playing_size.grid(row=2, column=1, sticky="w")

        self.var_show_prefix = tk.BooleanVar(value=style_config['playing']['show_prefix'])
        tk.Checkbutton(playing_inner, text="显示“正在播放”前缀", variable=self.var_show_prefix, command=lambda: self.update_playing("show_prefix", self.var_show_prefix.get()), bg="#f0f0f0").grid(row=3, column=0, columnspan=2, sticky="w", pady=5)

        self.var_playing_bold = tk.BooleanVar(value=style_config['playing']['is_bold'])
        tk.Checkbutton(playing_inner, text="字体加粗", variable=self.var_playing_bold, command=lambda: self.update_playing("is_bold", self.var_playing_bold.get()), bg="#f0f0f0").grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

        # ==========================================
        # Tab 7: 点歌列表源设置
        # ==========================================
        tab_queue = tk.Frame(notebook, bg="#f0f0f0")
        notebook.add(tab_queue, text="📜 点歌列表源")
        queue_inner = tk.Frame(tab_queue, bg="#f0f0f0", padx=20, pady=20)
        queue_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(queue_inner, text="字体 (可手动输入):", bg="#f0f0f0").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_queue_font = ttk.Combobox(queue_inner, values=["'PingFang SC', 'Microsoft YaHei', sans-serif", "'Microsoft YaHei', sans-serif"], state="normal")
        self.combo_queue_font.set(style_config['queue']['font'])
        self.combo_queue_font.bind("<<ComboboxSelected>>", lambda e: self.update_queue("font", self.combo_queue_font.get()))
        self.combo_queue_font.bind("<KeyRelease>", lambda e: self.update_queue("font", self.combo_queue_font.get()))
        self.combo_queue_font.grid(row=0, column=1, pady=5, sticky="w")

        tk.Button(queue_inner, text="修改颜色", command=lambda: self.pick_queue("color"), bg="#e0e0e0").grid(row=1, column=0, padx=5, pady=5)
        self.lbl_queue_color = tk.Label(queue_inner, text=style_config['queue']['color'], bg=style_config['queue']['color'], width=10)
        self.lbl_queue_color.grid(row=1, column=1, sticky="w")

        tk.Label(queue_inner, text="字号:", bg="#f0f0f0").grid(row=2, column=0, padx=5, sticky="e")
        self.scale_queue_size = tk.Scale(queue_inner, from_=15, to=80, orient=tk.HORIZONTAL, command=lambda e: self.update_queue("size", int(e)))
        self.scale_queue_size.set(style_config['queue']['size'])
        self.scale_queue_size.grid(row=2, column=1, sticky="w")

        tk.Label(queue_inner, text="列表最多字数:", bg="#f0f0f0").grid(row=3, column=0, padx=5, sticky="e")
        self.scale_max_chars = tk.Scale(queue_inner, from_=10, to=60, orient=tk.HORIZONTAL, command=lambda e: self.update_queue("max_chars", int(e)))
        self.scale_max_chars.set(style_config['queue']['max_chars'])
        self.scale_max_chars.grid(row=3, column=1, sticky="w", pady=5)

        self.var_queue_bold = tk.BooleanVar(value=style_config['queue']['is_bold'])
        tk.Checkbutton(queue_inner, text="字体加粗", variable=self.var_queue_bold, command=lambda: self.update_queue("is_bold", self.var_queue_bold.get()), bg="#f0f0f0").grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

        self.update_account_status()
        
        bottom_frame = tk.Frame(self.root, bg="#e0e0e0", pady=5)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.lbl_engine_status = tk.Label(bottom_frame, text="⏳ 正在检测音频驱动...", bg="#e0e0e0", fg="#555555", font=("微软雅黑", 9, "bold"))
        self.lbl_engine_status.pack()

    # === 回调 ===
    def update_mixed(self, key, val): style_config["mixed"][key] = val; self.schedule_save_style()
    def update_lyric(self, key, val): style_config["lyric"][key] = val; self.schedule_save_style()
    def update_playing(self, key, val): style_config["playing"][key] = val; self.schedule_save_style()
    def update_queue(self, key, val): style_config["queue"][key] = val; self.schedule_save_style()

    def update_lyric_align(self, event):
        val = self.combo_lyric_align.get()
        m = {"居中对齐": "center", "左对齐": "left", "右对齐": "right"}
        style_config["lyric"]["align"] = m.get(val, "center")
        self.schedule_save_style()

    def pick_mixed(self, key, lbl_name):
        c = colorchooser.askcolor(title="选择颜色")[1]
        if c:
            style_config["mixed"][key] = c
            getattr(self, lbl_name).config(bg=c, text=c)
            self.schedule_save_style()

    def pick_lyric(self, key):
        c = colorchooser.askcolor(title="选择歌词颜色")[1]
        if c: style_config["lyric"][key] = c; self.lbl_lyric_color.config(bg=c, text=c); self.schedule_save_style()

    def pick_playing(self, key):
        c = colorchooser.askcolor(title="选择播放颜色")[1]
        if c: style_config["playing"][key] = c; self.lbl_playing_color.config(bg=c, text=c); self.schedule_save_style()

    def pick_queue(self, key):
        c = colorchooser.askcolor(title="选择列表颜色")[1]
        if c: style_config["queue"][key] = c; self.lbl_queue_color.config(bg=c, text=c); self.schedule_save_style()

    def update_effect(self, event):
        val = self.combo_effect.get()
        m = {"高清平滑滚动 (锐利)": "apple_hd", "高清平滑滚动": "apple_hd", "苹果景深滚动 (柔光)": "apple_blur", "苹果景深滚动": "apple_blur", "无滚动 (经典静态)": "static", "无滚动 (静态)": "static"}
        style_config["lyric"]["effect"] = m.get(val, "apple_hd")
        self.schedule_save_style()

    def update_audio_quality(self, event=None):
        val = self.var_audio_quality.get()
        q_key = UI_QUALITY_MAP.get(val, "flac")
        style_config["audio_quality"] = q_key
        self.schedule_save_style()
        self.log(f"🎵 点歌首选音质已切换为: 【{val}】 (无对应音源时自动平滑降级)")
    
    def browse_qq_path(self):
        path = filedialog.askopenfilename(title="选择 QQMusic.exe", filetypes=[("Executable", "*.exe")])
        if path:
            path = path.replace("/", "\\")
            self.entry_qq_path.delete(0, tk.END)
            self.entry_qq_path.insert(0, path)
            self.config["qqmusic_path"] = path
            self.save_style_config()
            self.log(f"✅ QQ音乐路径已更新并保存: {path}")

    def copy_to_clipboard(self, text):
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.log(f"📋 已复制到剪贴板: {text}")

    def update_cache_settings(self, event=None):
        try:
            files = int(self.entry_max_files.get().strip())
            if files > 0: style_config["max_cache_files"] = files
        except ValueError as e:
            print(f"[WARN] 值解析失败: {e}")

        try:
            size = int(self.entry_max_size.get().strip())
            if size > 0: style_config["max_cache_size_mb"] = size
        except ValueError as e:
            print(f"[WARN] 值解析失败: {e}")

        self.schedule_save_style()

    def log(self, msg):
        def _log(): self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n"); self.log_text.see(tk.END)
        self.root.after(0, _log)

    def start_async_loop(self):
        self.loop = asyncio.new_event_loop(); asyncio.set_event_loop(self.loop); self.loop.run_until_complete(self.main_async())

    async def main_async(self):
        global skip_event; skip_event = asyncio.Event()
        self.log("正在启动 OBS 服务器...")
        web_app = web.Application()
        web_app.router.add_get('/', handle_index)
        web_app.router.add_get('/lyric', handle_index)
        web_app.router.add_get('/playing', handle_index)
        web_app.router.add_get('/queue', handle_index)
        web_app.router.add_get('/api/data', handle_api)
        
        runner = web.AppRunner(web_app); await runner.setup(); site = web.TCPSite(runner, '127.0.0.1', 8080); await site.start()
        self.log("✅ OBS 网页服务器已启动")
        self.init_audio_engine()

        asyncio.create_task(self.music_player_worker()); asyncio.create_task(self.system_media_worker()); asyncio.create_task(self.lyric_sync_worker())
        
        cookies = {}
        bili_cookie = self.config.get('bili_cookie', '')
        if not bili_cookie:
            self.log("❌ 缺少 B站 Cookie，请在顶部点击重新登录！")
        else:
            for item in bili_cookie.split(';'):
                if '=' in item: k, v = item.split('=', 1); cookies[k.strip()] = v.strip()
                
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Referer": f"https://live.bilibili.com/{self.config.get('room_id', '')}", "Origin": "https://live.bilibili.com"}
        
        async with aiohttp.ClientSession(cookies=cookies, headers=headers, trust_env=False) as http_session:
            if self.config.get('room_id'):
                client = blivedm.BLiveClient(int(self.config['room_id']), session=http_session)
                client.set_handler(BiliHandler(self)); client.start(); self.log("✅ 连接 B 站成功！等待弹幕中...")
                try:
                    while True: await asyncio.sleep(3600)
                finally: await client.stop_and_close()
            else:
                self.log("❌ 缺少房间号，请点击顶部登录 B站！")
                while True: await asyncio.sleep(3600)

    async def fetch_lyrics_by_mid_or_keyword(self, song_mid=None, keyword=None):
        try:
            if song_mid and song_mid in lyric_cache: return lyric_cache[song_mid]
            async with Client(credential=qq_credential) as client:
                if not song_mid and keyword:
                    search_res = await client.search.search_by_type(keyword=keyword, num=1)
                    song_mid, _, _, _ = extract_song_info(search_res)
                if not song_mid: return []
                if song_mid in lyric_cache: return lyric_cache[song_mid]
                lyric_res = await client.lyric.get_lyric(value=song_mid)
                raw_lrc = getattr(lyric_res, 'lyric', None)
                if not raw_lrc and isinstance(lyric_res, dict): raw_lrc = lyric_res.get('lyric')
                parsed = parse_lrc(raw_lrc)
                if parsed: lyric_cache[song_mid] = parsed
                return parsed
        except Exception: return []

    async def lyric_sync_worker(self):
        global current_lyric_info
        while True:
            try:
                if active_lrc_lines:
                    if current_play_mode == "api" and self.player_is_busy():
                        elapsed = self.player_get_elapsed()
                    else: 
                        elapsed = active_song_base_pos + (time.time() - active_song_start_ts)
                    
                    current_lyric_info = get_current_lyric_state(active_lrc_lines, elapsed)
                else: 
                    current_lyric_info = {"lines": [], "all_lines": [], "active_idx": -1}
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

            await asyncio.sleep(0.08)

    async def get_best_smtc_session(self, sessions_mgr):
        if not sessions_mgr: return None
        try:
            all_sessions = sessions_mgr.get_sessions(); fallback_session = None
            for s in all_sessions:
                try:
                    pinfo = s.get_playback_info()
                    if pinfo and pinfo.playback_status == 4: return s
                    if fallback_session is None: fallback_session = s
                except Exception: continue
            return sessions_mgr.get_current_session() or fallback_session
        except Exception:
            try: return sessions_mgr.get_current_session()
            except Exception: return None

    async def control_local_music(self, pause=True):
        global is_local_playing, bgm_paused_by_bot
        try:
            sessions_mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async(); session = await self.get_best_smtc_session(sessions_mgr)
            if session:
                playback_info = session.get_playback_info()
                if pause and playback_info.playback_status == 4: 
                    await session.try_toggle_play_pause_async(); self.log("⏸️ 暂停本地 BGM"); is_local_playing = False; bgm_paused_by_bot = True
                elif not pause and bgm_paused_by_bot and playback_info.playback_status != 4:
                    await session.try_toggle_play_pause_async(); self.log("▶️ 恢复本地 BGM"); is_local_playing = True; bgm_paused_by_bot = False
        except Exception as e: self.log(f"控制本地音乐失败: {e}")

    async def system_media_worker(self):
        global system_media_info, active_lrc_lines, active_song_start_ts, active_song_base_pos
        sessions_mgr = None
        try: sessions_mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
        except Exception as e:
            print(f"[WARN] 异常已捕获: {e}")

        last_logged_key = ""; last_lyric_key = ""; last_smtc_pos = -1.0
        while True:
            try:
                if current_play_mode == "local":
                    title, artist = "", ""; smtc_pos = None
                    if sessions_mgr:
                        session = await self.get_best_smtc_session(sessions_mgr)
                        if session:
                            info = await session.try_get_media_properties_async()
                            if info and info.title: title = (info.title or "").strip(); artist = (info.artist or "").strip()
                            try:
                                timeline = session.get_timeline_properties()
                                if timeline and timeline.position:
                                    pos_sec = timeline.position.total_seconds()
                                    if pos_sec > 0: smtc_pos = pos_sec
                            except Exception as e:
                                print(f"[WARN] 异常已捕获: {e}")

                    if not title:
                        win_title, win_artist = get_qqmusic_window_song()
                        if win_title: title, artist = win_title, (win_artist or "")
                    if title:
                        system_media_info = {"title": title, "artist": artist}; track_key = f"{title}|{artist}"
                        if track_key != last_logged_key: last_logged_key = track_key; self.log(f"🎵 正在播放(本地/网页): {title}" + (f" - {artist}" if artist else ""))
                        if track_key != last_lyric_key:
                            last_lyric_key = track_key; active_song_start_ts = time.time()
                            active_song_base_pos = smtc_pos if (smtc_pos is not None) else 0.0; last_smtc_pos = smtc_pos if (smtc_pos is not None) else -1.0
                            active_lrc_lines = []; search_kw = f"{title} {artist}".strip(); lines = await self.fetch_lyrics_by_mid_or_keyword(keyword=search_kw)
                            if not lines:
                                lines = [(0.0, style_config["lyric"].get("pure_text", "纯音乐, 请欣赏.."))]
                            if current_play_mode == "local" and last_lyric_key == track_key: active_lrc_lines = lines
                        elif smtc_pos is not None and abs(smtc_pos - last_smtc_pos) > 1.5:
                            last_smtc_pos = smtc_pos; active_song_base_pos = smtc_pos; active_song_start_ts = time.time()
                    else:
                        system_media_info = {"title": "暂无播放", "artist": ""}
                        if last_lyric_key != "": last_lyric_key = ""; active_lrc_lines = []
            except Exception as e:
                print(f"[WARN] 异常已捕获: {e}")

            await asyncio.sleep(1.5)

    async def download_audio_qq(self, song_info, retries=3):
        if not qq_credential: return None, None, None
        song_mid = song_info.get("mid")
        display_name = song_info.get("display_name", "")
        preferred_q = style_config.get("audio_quality", "flac")
        chain = QUALITY_FALLBACK_CHAINS.get(preferred_q, QUALITY_FALLBACK_CHAINS["flac"])

        primary_cached = find_cached_file_for_tier(song_mid, preferred_q)
        if primary_cached:
            try: os.utime(primary_cached, None)
            except Exception as e:
                print(f"[WARN] 缓存文件时间戳更新失败: {e}")
            return primary_cached, display_name, song_mid

        # 辅助函数：每次重试时重新获取CDN分发信息（避免使用过期的CDN节点）
        async def fetch_cdn():
            try:
                async with Client(credential=qq_credential) as client:
                    cdn_dispatch = await client.song.get_cdn_dispatch()
                    if hasattr(cdn_dispatch, 'sip') and cdn_dispatch.sip:
                        return random.choice(cdn_dispatch.sip)
            except Exception as e:
                print(f"[WARN] CDN分发信息获取失败: {e}")
            return ""

        # ===== 首次请求前预热：给CDN和网络连接足够的初始化时间 =====
        self.log(f"[INFO] 开始下载预热，等待网络初始化...")
        await asyncio.sleep(1.5)  # 预热延迟：给CDN节点分配和连接池初始化留时间
        
        # 首次获取CDN
        cdn = await fetch_cdn()
        if cdn:
            print(f"[INFO] 已获取CDN分发节点: {cdn}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://y.qq.com/", "Origin": "https://y.qq.com",
            "Cookie": f"uin=o{qq_credential.musicid}; qm_keyst={qq_credential.musickey};"
        }

        for idx, (tier_key, tier_label, enum_names, default_ext) in enumerate(chain):
            cached_tier_file = find_cached_file_for_tier(song_mid, tier_key)
            if cached_tier_file:
                if idx > 0: self.log(f"无 {chain[0][1]} 音源，已使用本地缓存 [{tier_label}]")
                try: os.utime(cached_tier_file, None)
                except Exception as e:
                    print(f"[WARN] 缓存文件时间戳更新失败: {e}")
                return cached_tier_file, display_name, song_mid

            # 每次音质降级时重新获取CDN
            cdn = await fetch_cdn()
            if cdn:
                self.log(f"已刷新CDN节点: {cdn}")

            # 使用 retries 参数控制重试次数（默认3次）
            for attempt in range(retries):
                try:
                    # 每次重试重新获取CDN节点（确保不复用过期节点）
                    if attempt > 0:
                        fresh_cdn = await fetch_cdn()
                        if fresh_cdn:
                            cdn = fresh_cdn
                            self.log(f"[INFO] 重试 [{tier_label}] (第{attempt+1}/{retries}次)，已刷新CDN节点: {fresh_cdn}")
                        else:
                            self.log(f"[WARN] 重试 [{tier_label}] (第{attempt+1}/{retries}次)，CDN刷新失败")

                    async with Client(credential=qq_credential) as client:
                        ft_enum = resolve_song_file_type(client, enum_names)
                        if ft_enum is None and tier_key != "mp3_128":
                            self.log(f"[{tier_label}] 无法探测音质枚举类型，跳过此档位")
                            break

                        url_res = await request_song_url_with_type(client, song_mid, ft_enum, qq_credential)
                        fresh_url = extract_url(url_res, cdn=cdn)
                        if attempt > 0 and fresh_url:
                            self.log(f"[INFO] 重试获取到新的下载URL (音质={tier_label})")

                        if not fresh_url:
                            self.log(f"[{tier_label}] 未能获取下载URL，跳过此档位")
                            break

                        selected_ext = detect_ext_from_url(fresh_url, default_ext)
                        file_path = os.path.join(CACHE_DIR, f"{song_mid}_{tier_key}{selected_ext}")

                        if attempt == 0:
                            self.log(f"[INFO] 首次下载 [{tier_label}]: {display_name} (URL签名时效: 约{int(time.time())})...")
                        else:
                            self.log(f"[INFO] 重试下载 [{tier_label}] (第{attempt+1}/{retries}次)...")

                        async with aiohttp.ClientSession(trust_env=False, headers=headers) as session:
                            async with session.get(fresh_url, timeout=30) as resp:
                                if resp.status in (200, 206):
                                    data = await resp.read()
                                    if data:
                                        with open(file_path, "wb") as f: f.write(data)
                                        size_mb = len(data) / (1024 * 1024)
                                        self.log(f"[INFO] ✅ 下载完成 [{tier_label}] ({size_mb:.1f} MB): {display_name} | 文件路径: {file_path}")
                                        clean_cache_if_needed()
                                        return file_path, display_name, song_mid
                                elif resp.status == 403:
                                    self.log(f"[{tier_label}] 下载被拦截(403)，将刷新CDN节点和链接后重试...")
                                    retry_delay = 2 + random.uniform(0, 1.5)  # 基础2秒 + 随机抖动0~1.5秒
                                    self.log(f"[INFO] 403等待 {retry_delay:.1f}秒后重试 (CDN刷新+随机抖动避免限流)")
                                    await asyncio.sleep(retry_delay)
                                else:
                                    self.log(f"[{tier_label}] 下载失败: HTTP {resp.status}")
                                    break
                except Exception as e:
                    self.log(f"[{tier_label}] 网络异常: {type(e).__name__}: {e}")
                    retry_delay = 2 + random.uniform(0, 1.5)  # 基础2秒 + 随机抖动
                    self.log(f"[INFO] 网络异常等待 {retry_delay:.1f}秒后重试")
                    await asyncio.sleep(retry_delay)

            if idx < len(chain) - 1:
                self.log(f"当前音质 [{tier_label}] 全部失败，降级为 [{chain[idx+1][1]}] 尝试下载...")
                # 降级前等待更久，给服务器更多恢复时间
                fallback_delay = 3 + random.uniform(0, 2)
                self.log(f"[INFO] 降级前等待 {fallback_delay:.1f}秒，确保服务器状态恢复")
                await asyncio.sleep(fallback_delay)

        self.log(f"彻底无法下载《{display_name}》，所有音质均失败")
        return None, display_name, song_mid

    def predownload_song(self, song_mid, display_name):
        if not qq_credential or not song_mid: return
        preferred_q = style_config.get("audio_quality", "flac")
        if find_cached_file_for_tier(song_mid, preferred_q): return
        if song_mid in self.download_tasks: return
        
        # 检查本地是否有该歌曲（通过歌名模糊匹配）
        exists, cached_path = check_local_song_exists(CACHE_DIR, display_name, "")
        if exists:
            self.log(f"✅ 本地已有该歌曲，跳过下载: {display_name}")
            return

        song_info = {"mid": song_mid, "display_name": display_name}
        q_label = QUALITY_UI_MAP.get(preferred_q, preferred_q)
        self.log(f"⏬ 开始后台预下载 ({q_label}): {display_name}")
        task = asyncio.create_task(self._download_and_cleanup(song_mid, song_info))
        self.download_tasks[song_mid] = task

    async def _download_and_cleanup(self, song_mid, song_info):
        try: await self.download_audio_qq(song_info)
        except Exception as e: self.log(f"❌ 预下载《{song_info.get('display_name', '')}》失败: {type(e).__name__}: {e}")
        finally: self.download_tasks.pop(song_mid, None)

    async def music_player_worker(self):
        global current_song, current_play_mode, system_media_info, active_lrc_lines, active_song_start_ts, active_song_base_pos
        while True:
            if current_song is None and len(playlist) > 0:
                current_song = playlist.pop(0)
                requester = current_song.get("requester", "神秘观众")
                self.log(f"▶️ 准备播放: {current_song['display_name']}-{requester}")
                song_mid = current_song.get("mid")

                preferred_q = style_config.get("audio_quality", "flac")
                
                file_path = None
                for tier_key, _, _, _ in QUALITY_FALLBACK_CHAINS.get(preferred_q, QUALITY_FALLBACK_CHAINS["flac"]):
                    file_path = find_cached_file_for_tier(song_mid, tier_key)
                    if file_path: break

                has_file = bool(file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0)

                # 如果缓存中没找到，尝试通过歌名匹配本地文件
                if not has_file and song_mid:
                    exists, cached_path = check_local_song_exists(CACHE_DIR, current_song.get('display_name', ''), '')
                    if exists:
                        file_path = cached_path
                        has_file = True
                        self.log(f"✅ 通过歌名匹配找到本地文件，跳过下载: {current_song.get('display_name', '')}")

                if not has_file and song_mid and song_mid in self.download_tasks:
                    self.log(f"⏳ 等待后台预下载完成: {current_song['display_name']}...")
                    while song_mid in self.download_tasks and not skip_event.is_set():
                        await asyncio.sleep(0.5)
                    if skip_event.is_set():
                        self.log("⏭️ 等待下载期间收到切歌指令，自动跳过")
                        skip_event.clear(); current_song = None; active_lrc_lines = []
                        continue
                    
                    file_path = None
                    for tier_key, _, _, _ in QUALITY_FALLBACK_CHAINS.get(preferred_q, QUALITY_FALLBACK_CHAINS["flac"]):
                        file_path = find_cached_file_for_tier(song_mid, tier_key)
                        if file_path: break
                    has_file = bool(file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0)

                real_name = current_song.get("display_name", "")
                
                if not has_file:
                    self.log(f"⏭️ 跳过无法播放的歌曲 (无版权或下载失败): {current_song['display_name']}")
                    current_song = None; active_lrc_lines = []
                    await asyncio.sleep(1)
                    continue

                if current_play_mode == "local":
                    await self.control_local_music(pause=True)
                    current_play_mode = "api"

                if file_path and os.path.exists(file_path):
                    ext_tag = os.path.splitext(file_path)[1].lstrip(".").upper() or "AUDIO"
                    self.log(f"✅ 开始独立播放 [Pygame | {ext_tag}]: {real_name}")
                    system_media_info = {"title": f"{current_song['display_name']}-{requester}", "artist": ""}
                    active_lrc_lines = await self.fetch_lyrics_by_mid_or_keyword(song_mid=song_mid, keyword=current_song['display_name'])
                    
                    if not active_lrc_lines:
                        active_lrc_lines = [(0.0, style_config["lyric"].get("pure_text", "纯音乐, 请欣赏.."))]

                    try:
                        started = await self.player_load_and_play(file_path)
                        active_song_start_ts = time.time()
                        active_song_base_pos = 0.0

                        if not started or not self.player_is_busy():
                            self.log(f"⚠️ 播放瞬间结束，可能是文件损坏或解码异常，自动清理并跳过: {real_name}")
                            try:
                                if os.path.exists(file_path): os.remove(file_path)
                            except Exception as e:
                                print(f"[WARN] 异常已捕获: {e}")

                            current_song = None; active_lrc_lines = []
                            continue

                        while self.player_is_busy():
                            if skip_event.is_set():
                                self.player_stop(); skip_event.clear(); break
                            await asyncio.sleep(0.25)
                    except Exception as e:
                        self.log(f"❌ 播放失败: {type(e).__name__}: {e}")
                        try:
                            if os.path.exists(file_path): os.remove(file_path)
                        except Exception as e:
                            print(f"[WARN] 异常已捕获: {e}")


                current_song = None; active_lrc_lines = []

                if len(playlist) == 0 and current_play_mode == "api":
                    await asyncio.sleep(0.5)
                    if len(playlist) == 0:
                        system_media_info = {"title": "暂无播放", "artist": ""}
                        await self.control_local_music(pause=False)
                        current_play_mode = "local"
            await asyncio.sleep(0.5)

class BiliHandler(blivedm.BaseHandler):
    def __init__(self, app_instance):
        super().__init__(); self.app = app_instance
    def _on_danmaku(self, client, message):
        text = message.msg.strip()
        uname = getattr(message, 'uname', '') or '神秘观众'
        if text == "切歌":
            if skip_event and not skip_event.is_set(): self.app.log("⏭️ 收到【切歌】指令！"); self.app.root.after(0, lambda: skip_event.set())
            return
        if text.startswith("点歌"):
            song_name = text.replace("点歌", "").strip()
            if song_name: 
                self.app.log(f"收到点歌请求: {song_name} - {uname}")
                asyncio.create_task(search_and_add(song_name, uname, self.app))

async def search_and_add(song_name, uname, app_instance, retry=2):
    if not qq_credential: return
    try:
        search_res = None
        for _ in range(retry):
            try:
                async with Client(credential=qq_credential) as client:
                    search_res = await client.search.search_by_type(keyword=song_name, num=1)
                    if search_res: break
            except Exception as e:
                app_instance.log(f"[WARN] 歌曲搜索失败: {e}")
            app_instance.log(f"搜索第{_+1}/{retry}次尝试...")
            await asyncio.sleep(1)

        song_mid, real_name, singer_name, _ = extract_song_info(search_res)
        if not song_mid:
            app_instance.log(f"❌ 没找到《{song_name}》或解析失败")
            return

        display_name = f"{real_name} {singer_name}"

        playlist.append({"name": real_name, "display_name": display_name, "mid": song_mid, "requester": uname})
        app_instance.log(f"✅ 已加入队列: {display_name}-{uname}")
        app_instance.predownload_song(song_mid, display_name)

    except Exception as e:
        app_instance.log(f"❌ 搜索出错 (检查网络/代理): {e}")


if __name__ == '__main__':
    # 启动时清理损坏文件
    print("[INFO] 启动时扫描缓存目录，清理损坏文件...")
    clean_corrupted_files(CACHE_DIR)
    load_credential()
    def launch_main_app(config):
        main_root = tk.Tk(); global app
        app = MusicApp(main_root, config); main_root.mainloop()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f: config_data = json.load(f)
        launch_main_app(config_data)
    else:
        launch_main_app({"room_id": "", "bili_cookie": "", "qqmusic_path": ""})