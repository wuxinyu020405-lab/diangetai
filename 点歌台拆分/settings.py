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
    
    for section in ["mixed", "lyric", "playing", "queue", "global"]:
        if section in old_cfg and isinstance(old_cfg[section], dict):
            new_cfg[section].update(old_cfg[section])
            
    if "audio_quality" in old_cfg: new_cfg["audio_quality"] = old_cfg["audio_quality"]
    if "max_cache_files" in old_cfg: new_cfg["max_cache_files"] = old_cfg["max_cache_files"]
    if "max_cache_size_mb" in old_cfg: new_cfg["max_cache_size_mb"] = old_cfg["max_cache_size_mb"]
    return new_cfg

# ── 需求5/6（第二批拍板）：音质收敛为两档 ──────────────────────────
# "flac"    = FLAC 无损（枚举候选 FLAC/F000/SQ）
# "default" = 默认品质：不传 file_type，吃库 get_song_urls 的函数默认值 MP3_128
#   （⚠️ 库若日后改默认值，此档行为跟着变——用户已选择"严格吃库默认"）
# 档位元组 5 字段：(tier_key, tier_label, enum候选名, 默认扩展名, needs_enum)
#   needs_enum=False 的档位不参与枚举探测，resolve 出 None 也不算错（13.1 方案B）
QUALITY_UI_MAP = {
    "flac": "FLAC 无损品质",
    "default": "默认品质",
}

UI_QUALITY_MAP = {v: k for k, v in QUALITY_UI_MAP.items()}

QUALITY_FALLBACK_CHAINS = {
    "flac": [
        ("flac", "FLAC 无损", ("FLAC", "F000", "SQ"), ".flac", True),
        ("default", "默认品质", (), ".mp3", False),
    ],
    "default": [
        ("default", "默认品质", (), ".mp3", False),
    ],
}


def normalize_quality_key(q):
    """旧配置值归一：flac/master/hires（无损诉求）→ flac；mp3_320/mp3_128/未知 → default。"""
    return "flac" if q in ("flac", "master", "hires") else "default"

# ── 配额保护（第5步，23:49 拍板：5 首 / 10 分钟 / 150）──────────────
QUOTA_DAILY_CAP = 150         # 每自然日主动下载上限（上游实测约190撞墙，留余量）
QUOTA_FAIL_STREAK = 5         # 连续几首"疑似配额类"失败 → 熔断
QUOTA_COOLDOWN_SEC = 600      # 熔断冷却（10分钟）；冷却只挡下载，缓存命中不受影响
SONG_DOWNLOAD_BUDGET_SEC = 45 # 第7步：单首总时间预算（两档链下 30~45 拍板取上限）

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


def get_browser_version(exe_path):
    """读取浏览器 exe 的主版本号（如 Edge 156.x → "156"）。失败返回 None。
    用于判断本地驱动与浏览器是否匹配——版本不匹配时驱动会拒绝连接。"""
    if not exe_path or not os.path.exists(exe_path):
        return None
    import subprocess
    try:
        # PowerShell 读文件版本，比 WMI 快且不需要管理员
        cmd = ('(Get-Item -LiteralPath "%s").VersionInfo.ProductVersion' % exe_path)
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=15)
        out = (r.stdout or "").strip()
        if out:
            return out.split(".")[0]
    except Exception:
        pass
    return None


def get_driver_version(driver_path):
    """运行 `驱动 --version` 读取驱动主版本号。失败返回 None。"""
    if not driver_path or not os.path.exists(driver_path):
        return None
    import subprocess
    try:
        r = subprocess.run([driver_path, "--version"],
                           capture_output=True, text=True, timeout=15)
        text = (r.stdout or "") + (r.stderr or "")
        # 形如 "Microsoft Edge WebDriver 155.0.4283.62 (...)" 或 "ChromeDriver 156.0.8078.73"
        for token in text.replace("(", " ").replace(")", " ").split():
            if token[:1].isdigit() and "." in token:
                return token.split(".")[0]
    except Exception:
        pass
    return None


def check_driver_match(driver_type, driver_path):
    """校验本地驱动与浏览器主版本是否一致。
    返回 (是否可用, 说明文字)。不匹配时明确告知该换驱动。"""
    exe = None
    b = get_default_browser_path()
    if b and b[0] == driver_type:
        exe = b[1]
    bv = get_browser_version(exe) if exe else None
    dv = get_driver_version(driver_path)
    if dv is None:
        return False, f"驱动无法读取版本({os.path.basename(driver_path)})"
    if bv is None:
        return True, f"驱动 v{dv}，浏览器版本未知（放行尝试）"
    if bv == dv:
        return True, f"驱动 v{dv} 与浏览器 v{bv} 匹配"
    return False, (f"驱动 v{dv} 与浏览器 v{bv} 不匹配——"
                   f"请删除旧的 {os.path.basename(driver_path)}，"
                   f"下载 v{bv} 版本驱动放到程序目录")


def save_startup_log(text, filename="启动日志.txt"):
    """把启动/登录过程的重要信息落盘，便于用户把日志发回排错。
    --windowed 打包后看不到控制台，只有落盘才可能收集到现场。"""
    try:
        p = os.path.join(BASE_DIR, filename)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p
    except Exception:
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
