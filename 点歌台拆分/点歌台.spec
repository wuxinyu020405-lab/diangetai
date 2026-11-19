# -*- mode: python ; coding: utf-8 -*-
"""扫码点歌台 打包配置（PyInstaller）。

用法（在项目根目录）:
    .venv\\Scripts\\python.exe -m PyInstaller 点歌台拆分\\点歌台.spec --noconfirm

产物：dist\\点歌台\\点歌台.exe + 同目录依赖（onedir，启动快、易排错）
注意：exe 必须连同整个 dist\\点歌台\\ 目录一起分发，不能只拖 exe。
"""
from PyInstaller.utils.hooks import collect_all

import glob
import os
import shutil

datas = []
binaries = []
hiddenimports = []

# ── 版本单一来源：读同目录 version.py（exe 版本资源与运行时显示永不漂移）──
import importlib.util as _ilu
_vk = _ilu.spec_from_file_location("_version", os.path.join(SPECPATH, "version.py"))
_vmod = _ilu.module_from_spec(_vk); _vk.loader.exec_module(_vmod)
APP_VERSION = _vmod.VERSION                      # "1.0.0"
APP_TUPLE = tuple(_vmod.VERSION_TUPLE)           # (1, 0, 0, 0)

_version_file = os.path.join(SPECPATH, "version_info.txt")
with open(_version_file, "w", encoding="utf-8") as _f:
    _f.write("""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={t},
    prodvers={t},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('080404B0', [
      StringStruct('FileDescription', '扫码点歌台（B站弹幕点歌 + OBS 挂件）'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'DianGeTai'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', '点歌台.exe'),
      StringStruct('ProductName', '扫码点歌台'),
      StringStruct('ProductVersion', '{v}'),
    ])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""".format(t=APP_TUPLE, v=APP_VERSION))
print(f"[spec] 版本资源: {APP_VERSION} {APP_TUPLE} -> version_info.txt")

# 应用图标（_gen_icon.py 生成；同时作为 datas 带进去供 tkinter 设窗口图标）
APP_ICON = os.path.join(SPECPATH, "app.ico")
if os.path.exists(APP_ICON):
    datas.append((APP_ICON, "."))
else:
    APP_ICON = None
    print("[spec][WARN] 未找到 app.ico，exe 将无自定义图标")

# 抖音签名调用壳（sign_runner.js + package.json）随包分发到 exe 旁 douyin_sign/。
# 注意：sign.js（webmssdk 反混淆产物，版权归字节）不在仓库、不打包——
# 想启用抖音的用户按使用说明自备 sign.js 并安装 node；缺任一，抖音通道
# 自动"未启用"降级（live_providers.douyin.check_deps），B站主路不受影响。
_dy_sign = os.path.join(os.path.dirname(SPECPATH), "douyin_sign")
if os.path.isdir(_dy_sign):
    for _f in ("sign_runner.js", "package.json"):
        _fp = os.path.join(_dy_sign, _f)
        if os.path.exists(_fp):
            datas.append((_fp, "douyin_sign"))
    print("[spec] 抖音签名壳已打包: douyin_sign/ (sign.js 需用户自备)")
else:
    print("[spec][WARN] 未找到 douyin_sign/，抖音功能将始终未启用")

# ── 需要完整收集的包 ──────────────────────────────────────────────
# qqmusic_api: 大量动态导入（algorithms/models/modules）+ 可能带数据文件
# blivedm: GitHub master 安装，clients/models 子包靠运行时导入
# winsdk: namespace 包，PyInstaller 静态分析抓不到，必须 collect_all
for pkg in ("qqmusic_api", "blivedm", "winsdk"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec][WARN] collect_all({pkg}) 失败: {e}")

# selenium: 已不再使用（登录改为 pywebview 内嵌浏览器），故不收集。

# ── Qt 界面（R-15 起 UI 是 PySide6 + qfluentwidgets；R-22 清掉 customtkinter）──
# PySide6 由 PyInstaller 自带官方 hook 处理；qfluentwidgets / qframelesswindow
# 的图标资源是打进 _rc/resource.py 的（包内没有任何数据文件，实测 0 个），
# 所以**不需要** collect_all / collect_data_files，静态分析就够。
# ⚠️ 反面教训（R-22 实测）：collect_all("qfluentwidgets") 会把 multimedia 等
#    用不到的子模块全拖进来，连带 require QtMultimedia；不排除 Qt 大模块时
#    PySide6 整包进 dist（Qt6WebEngineCore.dll 一个 203MB），包体从 299MB 涨到 877MB。

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
    # blivedm 运行时依赖（--no-deps 装的，静态分析偶尔漏收；Run#9 教训）
    "pure_protobuf",
    "paho.mqtt.client",
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
    "smtc", "browserlogin", "danmaku", "mainapp",
    # R-15：界面换成 PySide6（qtapp.py + qtshim.py），旧的 ui_ctk.py 已删除（R-22）
    "qtapp", "qtshim",
    "version", "updater",
    # v1.2.1：配置加密 + 自动更新（main.py 的 if 分支里 import，静态能抓到，
    # 但按项目惯例显式列出双保险）
    "secretstore",
    # v1.2.2：系统托盘（mainapp 方法内 import tray；tray 内 import pystray/PIL）
    "tray", "pystray", "pystray._win32", "PIL", "PIL._tkinter_finder",
    # R-28：子进程登记簿（quit_app 内 import，静态分析抓不到）
    "childproc",
    # v1.2.8：本地曲库（danmaku/mainapp 都 import，显式列出双保险）
    "locallib",
    # v1.2.8：字体候选与校验（qtapp / qtshim 顶部 import，显式列出双保险）
    "fontlib",
    # 抖音 provider 是函数内 import（main_async 里），静态分析抓不到，必须显式列，
    # 否则打包版启用抖音直接 ModuleNotFoundError
    "live_providers", "live_providers.douyin",
]

# ── 运行期需要的非代码文件 ────────────────────────────────────────

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
        "PySide2", "IPython", "jupyter", "pytest",
        # R-22：Qt 只用 Core/Gui/Widgets（外加 Svg/Xml），其余模块一律不收。
        # 不排除的话 Qt6WebEngineCore.dll(203MB) + WebEngine 资源(75MB) +
        # opengl32sw.dll(20MB) 全会被带进来。
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtSpatialAudio",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtSerialBus", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtHelp", "PySide6.QtDesigner", "PySide6.QtUiTools",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    ],
    noarchive=False,
    optimize=0,
)
# ══════════════════════════════════════════════════════════════════
# R-24 瘦身：在 Analysis 之后、COLLECT 之前，把用不到的 Qt 二进制/翻译剔掉。
# 依据（逐项实测，不是拍脑袋）：
#  · opengl32sw.dll(20MB)  = Qt 的软件 OpenGL 兜底实现。本程序 UI 是 Qt Widgets
#    的 raster 引擎，从不创建 QOpenGLContext；去掉后起窗口 5 页全切、深浅色切换、
#    OBS 服务、自检全部正常（R-24 实测）。
#  · Qt6Qml*/Qt6Quick/Qt6VirtualKeyboard = QML 运行时。全项目 grep 无任何
#    Qml/Quick import，qfluentwidgets/qframelesswindow 也不用；引它们的只有
#    qdirect2d 插件和虚拟键盘插件，一起剔。
#  · Qt6Pdf.dll + imageformats/qpdf.dll = 只在把 PDF 当图片加载时用，程序不做。
#  · Qt6OpenGL.dll = 只被 Qt6Quick 链接，Quick 走了它就没人要。
#  · translations 只留 简体/繁体中文 + 英文；Qt 默认语言就是英文，界面文案全在
#    我们自己代码里，翻译文件只影响 Qt 内置控件（右键菜单等）的措辞。
#  · qminimal/qoffscreen 平台插件体积很小(174KB)，是测试/无头环境兜底，保留。
# ⚠️ 保守项（拿不准，不动）：Qt6Network（TLS/网络插件依赖）、Qt6Svg/Xml、
#    imageformats 其余编解码器、qwindows、styles。
# ══════════════════════════════════════════════════════════════════
_DROP_BINARIES = {
    "opengl32sw.dll",
    "Qt6Qml.dll", "Qt6QmlMeta.dll", "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll",
    "Qt6Quick.dll", "Qt6VirtualKeyboard.dll", "Qt6Pdf.dll", "Qt6OpenGL.dll",
    "qdirect2d.dll", "qpdf.dll",
    "qtvirtualkeyboardplugin.dll", "qtuiotouchplugin.dll",
}
_KEEP_TRANSLATIONS = {
    "qt_zh_CN.qm", "qt_zh_TW.qm", "qt_en.qm",
    "qtbase_zh_CN.qm", "qtbase_zh_TW.qm", "qtbase_en.qm",
}


def _is_dropped_binary(dest):
    """dest 形如 'PySide6/Qt6Qml.dll' 或 'PySide6/plugins/imageformats/qpdf.dll'。"""
    name = os.path.basename(dest)
    if name in _DROP_BINARIES:
        return True
    # 翻译目录只保留中英文
    if "/translations/" in dest.replace("\\", "/") and name.endswith(".qm"):
        return name not in _KEEP_TRANSLATIONS
    return False


def _is_dropped_data(dest):
    # 翻译文件有时被 PyInstaller 归到 datas 而不是 binaries，两边都过一遍
    return _is_dropped_binary(dest)


for _field in ("binaries", "datas"):
    _before = getattr(a, _field)
    _after = [x for x in _before if not _is_dropped_binary(x[0])]
    setattr(a, _field, _after)
    _n = len(_before) - len(_after)
    if _n:
        print(f"[spec][瘦身] {_field}: 剔除 {_n} 项")

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
    icon=APP_ICON,               # 麦克风图标（_gen_icon.py 生成）
    version=_version_file,       # exe 属性页的版本信息（与 version.py 同源）
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="点歌台",
)

# ── 使用说明随包（v1.2.1 需求20：装完必须有说明可看）──────────────
# 仓库根的 使用说明.md → dist\点歌台\使用说明.md（Inno [Files] 与 portable
# zip 都从这里取材；更新白名单也含它，升级时自动刷新说明）
_doc = os.path.join(os.path.dirname(SPECPATH), "使用说明.md")
if os.path.exists(_doc):
    shutil.copy2(_doc, os.path.join(DISTPATH, "点歌台", "使用说明.md"))
    print("[spec] 使用说明.md 已随包")
else:
    print("[spec][WARN] 仓库根缺 使用说明.md，包内将没有使用说明")

# ── 抖音签名壳复制到 exe 同级 douyin_sign/（用户往这里放 sign.js 最直观）──
# datas 已把它带进 _internal，但用户看不到 _internal；再复制一份到 exe 旁，
# provider 的 sign_dir 候选第一优先级就是 exe 同级。sign.js 不打包（字节版权）。
_dy_src = os.path.join(os.path.dirname(SPECPATH), "douyin_sign")
_dy_dst = os.path.join(DISTPATH, "点歌台", "douyin_sign")
if os.path.isdir(_dy_src):
    os.makedirs(_dy_dst, exist_ok=True)
    for _f in ("sign_runner.js", "package.json"):
        _fp = os.path.join(_dy_src, _f)
        if os.path.exists(_fp):
            shutil.copy2(_fp, os.path.join(_dy_dst, _f))
    print("[spec] 抖音签名壳已复制到 exe 同级 douyin_sign/")

# ── 把 .NET 6 运行时打进发布目录（实现"目标机器无需预装 .NET"）────────
# 登录用 pywebview + WebView2，走 coreclr 需要 .NET 运行时；
# 普通用户机器通常没有 .NET 6+ → 必须自包含（微软官方 self-contained 做法）。
# 目录布局必须与真实 dotnet 安装一致，hostfxr 依赖它来定位共享框架。
# 版本可被 CI 覆盖：DIANGETAI_DOTNET_VER（本机默认 6.0.36）
_DOTNET_VER = os.environ.get("DIANGETAI_DOTNET_VER", "6.0.36")
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
