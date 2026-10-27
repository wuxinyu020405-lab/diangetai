"""
配置与路径：目录常量、配置合并、音质映射表、凭据存取、客户端/浏览器探测
"""

import json
import os
import sys
from qqmusic_api import Client, Credential
import state
import subprocess              # 原 L28：源码未使用，按纯搬家保留
import urllib.parse            # 原 L16：源码未使用，按纯搬家保留

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

def save_credential(cred):
    with open(CREDENTIAL_FILE, "w", encoding="utf-8") as f: json.dump({"musicid": cred.musicid, "musickey": cred.musickey}, f)

def load_credential():
    global qq_credential
    if os.path.exists(CREDENTIAL_FILE):
        with open(CREDENTIAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            state.qq_credential = Credential(musicid=data["musicid"], musickey=data["musickey"])
            return True
    return False

def find_qqmusic_path():
    drives = ['C:', 'D:', 'E:', 'F:']
    paths = [r"\Program Files\Tencent\QQMusic\QQMusic.exe", r"\Program Files (x86)\Tencent\QQMusic\QQMusic.exe", r"\QQMusic\QQMusic.exe", r"\Tencent\QQMusic\QQMusic.exe"]
    for d in drives:
        for p in paths:
            if os.path.exists(d + p): return d + p
    return ""
