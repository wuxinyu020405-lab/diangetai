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


def _no_window_kwargs():
    """子进程静默参数：禁止弹黑窗。
    打包成 --windowed 程序后，任何 subprocess 调用都会弹出黑色控制台窗口，
    即使加了 CREATE_NO_WINDOW 之外的参数也一样。必须显式指定。"""
    if os.name != "nt":
        return {}
    si = None
    try:
        import subprocess as _sp
        si = _sp.STARTUPINFO()
        si.dwFlags |= _sp.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return {"startupinfo": si, "creationflags": 0x08000000}  # CREATE_NO_WINDOW
    except Exception:
        return {}


def get_browser_version(exe_path):
    """读取浏览器 exe 的主版本号（如 Edge 156.x → "156"）。失败返回 None。

    ★ 不再调用 powershell：那样每读一次就闪一个黑窗，体验极差。
      改用纯 Python 读 PE 文件版本资源（零子进程、零黑窗）。
    """
    if not exe_path or not os.path.exists(exe_path):
        return None
    try:
        v = _pe_file_version(exe_path)
        if v:
            return v.split(".")[0]
    except Exception:
        pass
    return None


def _pe_file_version(path):
    """用 ctypes 读取 exe 的 VS_FIXEDFILEINFO，返回 "a.b.c.d" 或 None。
    纯 Python/ctypes 实现，不启动任何子进程 → 不会闪黑窗。"""
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version")
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return None
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD),
                ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD),
                ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD),
                ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD),
            ]

        info = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return "%d.%d.%d.%d" % ((ms >> 16) & 0xFFFF, ms & 0xFFFF,
                                (ls >> 16) & 0xFFFF, ls & 0xFFFF)
    except Exception:
        return None


def get_driver_version(driver_path):
    """读取驱动主版本号。

    ★ 不再运行 `drv --version`（会闪黑窗）：
      改为从驱动所在路径推断——selenium 缓存的驱动路径形如
      .../msedgedriver/win64/155.0.4283.62/msedgedriver.exe，版本号就在路径里。
      我们随包分发的驱动直接按文件名旁的 version.txt 记录（见 _driver_version_hint）。
    """
    if not driver_path or not os.path.exists(driver_path):
        return None

    # ① 优先读同目录的版本说明（打包时写入）
    try:
        hint = os.path.join(os.path.dirname(driver_path), "driver_version.txt")
        if os.path.exists(hint):
            with open(hint, "r", encoding="utf-8") as f:
                txt = f.read().strip()
            if txt and txt[:1].isdigit():
                return txt.split(".")[0]
    except Exception:
        pass

    # ② 从 selenyuan 缓存风格路径里提取（.../win64/155.0.4283.62/xxx.exe）
    try:
        parts = os.path.normpath(driver_path).split(os.sep)
        for seg in parts:
            if seg[:1].isdigit() and seg.count(".") >= 2:
                return seg.split(".")[0]
    except Exception:
        pass

    # ③ 最后才读 PE 版本资源（驱动 exe 本身也有版本信息，同样零黑窗）
    try:
        v = _pe_file_version(driver_path)
        if v:
            return v.split(".")[0]
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
