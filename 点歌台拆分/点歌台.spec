# -*- mode: python ; coding: utf-8 -*-
"""扫码点歌台 打包配置（PyInstaller）。

用法（在项目根目录）:
    .venv\\Scripts\\python.exe -m PyInstaller 点歌台拆分\\点歌台.spec --noconfirm

产物：dist\\点歌台\\点歌台.exe + 同目录依赖（onedir，启动快、易排错）
注意：exe 必须连同整个 dist\\点歌台\\ 目录一起分发，不能只拖 exe。
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = []
binaries = []
hiddenimports = []

# ── 需要完整收集的包 ──────────────────────────────────────────────
# qqmusic_api: 大量动态导入（algorithms/models/modules）+ 可能带数据文件
# customtkinter: 必须带 assets（字体/主题 JSON），否则界面起不来
# blivedm: GitHub master 安装，clients/models 子包靠运行时导入
# winsdk: namespace 包，PyInstaller 静态分析抓不到，必须 collect_all
for pkg in ("qqmusic_api", "customtkinter", "blivedm", "winsdk"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec][WARN] collect_all({pkg}) 失败: {e}")

# ── 已知静态分析抓不到的动态导入 ──────────────────────────────────
hiddenimports += [
    # 源码 L1-L7 显式导入（qqmusic_api -> jsonpath_ng -> ply 传递依赖）
    # 注意：jsonpath_ng.ply_tables 是运行时 try/except 探测的可选模块，
    #      安装后实际不存在，不可写成 hidden import（会报 not found）
    "ply",
    "jsonpath_ng",
    "jsonpath_ng.ext",
    # aiohttp 的 web 子模块
    "aiohttp",
    "aiohttp.web",
    # selenium 各驱动实现（按需用到 Edge/Chrome）
    "selenium.webdriver",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.edge.service",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.edge.options",
    "selenium.webdriver.common.selenium_manager",
    # pygame 的 mixer（音频）
    "pygame",
    "pygame.mixer",
    # tkinter 文件对话框等
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.colorchooser",
    "tkinter.scrolledtext",
    # winsdk 常用子模块（collect_all 已覆盖，这里双保险）
    "winsdk.windows.media.control",
    "winsdk.windows.foundation",
    # qqmusic_api 顶层导出
    "qqmusic_api.core.request",
    "qqmusic_api.core.exceptions",
    "qqmusic_api.models",
    "qqmusic_api.models.song",
    "qqmusic_api.modules",
    "qqmusic_api.modules.song",
    "qqmusic_api.modules.search",
    "qqmusic_api.modules.lyric",
]

# ── 项目自身模块（拆分包之间互相 import）─────────────────────────
hiddenimports += [
    "state", "settings", "lyrics", "musiclib", "overlay",
    "smtc", "browserlogin", "danmaku", "mainapp", "ui_ctk",
]

# ── 运行期需要的非代码文件 ────────────────────────────────────────
# customtkinter 资源双保险
datas += collect_data_files("customtkinter")

a = Analysis(
    ["main.py"],                 # 入口（相对 spec 所在目录，即 点歌台拆分/）
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 明显用不到的大包，减小体积
        "matplotlib", "numpy", "scipy", "pandas", "PyQt5", "PyQt6",
        "PySide2", "PySide6", "IPython", "jupyter", "pytest",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="点歌台",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # 用 UPX 压缩易被安全软件误报，关闭
    console=False,               # 窗口程序；排查问题时可临时改 True
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="点歌台",
)

# ── 关键：把浏览器驱动复制到发布目录 ──────────────────────────────
# 朋友的电脑上没有 selenium 缓存，Selenium Manager 需要联网下载驱动，
# 而国内常连不上 msedgedriver 域名 → "打不开浏览器"。
# 把驱动随包分发，start_driver 会优先用本地驱动，完全不依赖网络。
import shutil as _shutil
import os as _os

_dist = _os.path.join(DISTPATH, "点歌台")
for _drv in ("msedgedriver.exe", "chromedriver.exe"):
    _src = _os.path.join(SPECPATH, _drv)   # spec 与驱动同目录（点歌台拆分/）
    if _os.path.exists(_src):
        _dst = _os.path.join(_dist, _drv)
        _os.makedirs(_dist, exist_ok=True)
        _shutil.copy2(_src, _dst)
        print(f"[spec] 已随包分发驱动: {_drv} ({_os.path.getsize(_src)//1024//1024} MB)")
    else:
        print(f"[spec][WARN] 未找到 {_drv}，分发包将依赖 Selenium Manager 联网下载")
