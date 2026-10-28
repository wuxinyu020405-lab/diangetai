# -*- mode: python ; coding: utf-8 -*-
"""扫码点歌台 打包配置（PyInstaller）。

用法（在项目根目录）:
    .venv\\Scripts\\python.exe -m PyInstaller 点歌台拆分\\点歌台.spec --noconfirm

产物：dist\\点歌台\\点歌台.exe + 同目录依赖（onedir，启动快、易排错）
注意：exe 必须连同整个 dist\\点歌台\\ 目录一起分发，不能只拖 exe。
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

import glob
import os
import shutil

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

# selenium: 用 collect_submodules 兜底全量子模块。
# selenium 内部大量动态导入（webdriver.Edge → edge.webdriver → remote.webdriver
# → common.service → selenium_manager），静态分析会漏；实测漏过
# selenium.webdriver.edge.webdriver 导致打包后完全无法启动浏览器。
try:
    _sel = collect_submodules("selenium")
    hiddenimports += _sel
    # 数据文件（selenium-manager.exe、类型提示等）
    datas += collect_data_files("selenium")
    print(f"[spec] selenium 子模块收集: {len(_sel)} 个")
except Exception as e:
    print(f"[spec][WARN] collect_submodules(selenium) 失败: {e}")

# ── pywebview（内嵌浏览器登录）──────────────────────────────────
# 关键：
#  · webview/lib 里有两个版本的 WebView2 程序集（根目录=netcore，net462/=Framework），
#    必须整体作为 datas 带上，否则打包后浏览器起不来
#  · pythonnet / clr_loader 靠运行时反射加载 Python.Runtime.dll，
#    静态分析抓不到，必须 collect_all
#  · pythonnet 的 runtime/*.dll 也要带上（否则 netfx 加载器找不到）
for _pkg in ("webview", "pythonnet", "clr_loader"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
        print(f"[spec] {_pkg} 收集: datas={len(_d)} binaries={len(_b)} hidden={len(_h)}")
    except Exception as e:
        print(f"[spec][WARN] collect_all({_pkg}) 失败: {e}")

# pythonnet 的 Python.Runtime.dll 必须落到 _internal 根（PyInstaller 有时漏）
try:
    import pythonnet as _pn
    import glob as _g
    _pn_dir = os.path.dirname(_pn.__file__)
    for _dll in _g.glob(os.path.join(_pn_dir, "runtime", "*.dll")):
        binaries.append((_dll, "."))
        print(f"[spec] pythonnet runtime: {os.path.basename(_dll)}")
except Exception as e:
    print(f"[spec][WARN] pythonnet runtime 收集失败: {e}")

# pygame: collect_all 会漏掉部分 DLL（实测缺 libmodplug-1.dll、libopusfile-0.dll）。
# 那两个是 SDL2_mixer 的解码/音乐模块依赖，缺了可能导致某些格式放不出来。
try:
    _pg_d, _pg_b, _pg_h = collect_all("pygame")
    datas += _pg_d
    binaries += _pg_b
    hiddenimports += _pg_h
    print(f"[spec] pygame 收集: datas={len(_pg_d)} binaries={len(_pg_b)}")
except Exception as e:
    print(f"[spec][WARN] collect_all(pygame) 失败: {e}")

# 兜底：把 site-packages/pygame 下的所有 DLL 强制作为 binary 收集
try:
    import pygame as _pg
    _pgdir = os.path.dirname(_pg.__file__)
    _n = 0
    for _dll in glob.glob(os.path.join(_pgdir, "*.dll")):
        binaries.append((_dll, "pygame"))
        _n += 1
    print(f"[spec] pygame DLL 强制收集: {_n} 个")
except Exception as e:
    print(f"[spec][WARN] pygame DLL 强制收集失败: {e}")

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
    # ⚠️ 关键教训：selenium.webdriver.edge.webdriver / chrome.webdriver 这两个
    #    才是 webdriver.Edge()/Chrome() 实际实例化的模块。之前只写了
    #    .service/.options，漏了 .webdriver → 打包后运行时报
    #    ModuleNotFoundError: No module named 'selenium.webdriver.edge.webdriver'
    "selenium.webdriver",
    "selenium.webdriver.edge",
    "selenium.webdriver.edge.webdriver",
    "selenium.webdriver.edge.service",
    "selenium.webdriver.edge.options",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.webdriver",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.remote.webdriver",
    "selenium.webdriver.remote.service",
    "selenium.webdriver.remote.remote_connection",
    "selenium.webdriver.remote.command",
    "selenium.webdriver.remote.errorhandler",
    "selenium.webdriver.remote.file_detector",
    "selenium.webdriver.common.service",
    "selenium.webdriver.common.driver_finder",
    "selenium.webdriver.common.selenium_manager",
    "selenium.webdriver.common.options",
    "selenium.webdriver.common.proxy",
    "selenium.webdriver.common.by",
    "selenium.webdriver.common.utils",
    "selenium.webdriver.common.timeouts",
    "selenium.common.exceptions",
    "selenium.common.by",
    "selenium.types",
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
_dist = os.path.join(DISTPATH, "点歌台")
for _drv in ("msedgedriver.exe", "chromedriver.exe"):
    _src = os.path.join(SPECPATH, _drv)   # spec 与驱动同目录（点歌台拆分/）
    if os.path.exists(_src):
        _dst = os.path.join(_dist, _drv)
        os.makedirs(_dist, exist_ok=True)
        shutil.copy2(_src, _dst)
        print(f"[spec] 已随包分发驱动: {_drv} ({os.path.getsize(_src)//1024//1024} MB)")
        # 写版本提示文件：让 get_driver_version 免启动子进程即可得知版本（防黑窗）
        try:
            _ver = "156.0.0.0"   # 与本包一致的驱动版本；如需精确可改为读 PE
            with open(os.path.join(_dist, "driver_version.txt"), "w", encoding="utf-8") as _f:
                _f.write(_ver)
        except Exception:
            pass
    else:
        print(f"[spec][WARN] 未找到 {_drv}，分发包将依赖 Selenium Manager 联网下载")
