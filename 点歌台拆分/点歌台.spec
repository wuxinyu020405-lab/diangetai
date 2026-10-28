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

# selenium: 已不再使用（登录改为 pywebview 内嵌浏览器），故不收集。

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
    # 注意：selenium 已随登录改造移除（改用 pywebview 内嵌浏览器），
    #      不再需要任何 selenium hidden import。保留条目会让 PyInstaller
    #      去收集一个已不存在的包，产生 "hidden import not found" 噪声。
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

# ── 把 .NET 6 运行时打进发布目录（实现"目标机器无需预装 .NET"）────────
# 登录用 pywebview + WebView2，走 coreclr 需要 .NET 运行时；
# 普通用户机器通常没有 .NET 6+ → 必须自包含（微软官方 self-contained 做法）。
# 目录布局必须与真实 dotnet 安装一致，hostfxr 依赖它来定位共享框架。
_DOTNET_VER = "6.0.36"
_DOTNET_SRC = r"C:\Program Files\dotnet"
_dist = os.path.join(DISTPATH, "点歌台")
_dst = os.path.join(_dist, "dotnet")

_src_core = os.path.join(_DOTNET_SRC, "shared", "Microsoft.NETCore.App", _DOTNET_VER)
if os.path.isdir(_src_core):
    if os.path.isdir(_dst):
        shutil.rmtree(_dst, ignore_errors=True)
    os.makedirs(_dst, exist_ok=True)

    # dotnet.exe（apphost）
    _e = os.path.join(_DOTNET_SRC, "dotnet.exe")
    if os.path.exists(_e):
        shutil.copy2(_e, os.path.join(_dst, "dotnet.exe"))

    # host/fxr/<ver>/hostfxr.dll —— 运行时启动的关键
    _fxr_src = os.path.join(_DOTNET_SRC, "host", "fxr", _DOTNET_VER)
    if os.path.isdir(_fxr_src):
        _fxr_dst = os.path.join(_dst, "host", "fxr", _DOTNET_VER)
        os.makedirs(_fxr_dst, exist_ok=True)
        for _f in os.listdir(_fxr_src):
            shutil.copy2(os.path.join(_fxr_src, _f), os.path.join(_fxr_dst, _f))

    # shared/<framework>/<ver>
    _bytes = 0
    for _fw in ("Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App"):
        _s = os.path.join(_DOTNET_SRC, "shared", _fw, _DOTNET_VER)
        if not os.path.isdir(_s):
            print(f"[spec][WARN] 缺少 {_fw}/{_DOTNET_VER}")
            continue
        _d = os.path.join(_dst, "shared", _fw, _DOTNET_VER)
        os.makedirs(_d, exist_ok=True)
        for _f in os.listdir(_s):
            _p = os.path.join(_s, _f)
            if os.path.isfile(_p):
                shutil.copy2(_p, os.path.join(_d, _f))
                _bytes += os.path.getsize(_p)
    print(f"[spec] 已内置 .NET {_DOTNET_VER} 运行时: {_bytes/1024/1024:.1f} MB")
else:
    print(f"[spec][WARN] 未找到 .NET {_DOTNET_VER}，分发包将要求用户预装 .NET 运行时")
