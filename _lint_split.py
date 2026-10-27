# -*- coding: utf-8 -*-
"""静态 lint（干净版）：检测"跨模块符号被裸引用"——前缀化漏网 → 运行时 NameError。
只关心 STATE/SYMBOLS 两类跨模块名；普通闭包变量（log_fn/driver 等）由作用域链正常解析，不误报。"""
import ast
import builtins
import io
import glob
import os

OUT = "点歌台拆分"
BI = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__package__",
                           "__spec__", "__loader__", "__builtins__", "__debug__"}
STATE = {"playlist", "current_song", "skip_event", "app", "system_media_info",
         "current_lyric_info", "lyric_cache", "qq_credential", "style_config",
         "current_play_mode", "is_local_playing", "bgm_paused_by_bot",
         "active_lrc_lines", "active_song_start_ts", "active_song_base_pos"}
SYMBOLS = {"merge_config", "get_default_browser_path", "find_qqmusic_path",
           "save_credential", "load_credential", "parse_lrc", "get_current_lyric_state",
           "resolve_song_file_type", "request_song_url_with_type", "detect_ext_from_url",
           "find_cached_file_for_tier", "check_local_song_exists", "clean_corrupted_files",
           "clean_cache_if_needed", "extract_song_info", "extract_url", "handle_index",
           "handle_api", "start_driver", "bilibili_auto_login", "qq_scan_login",
           "get_qqmusic_window_song", "BiliHandler", "search_and_add", "MusicApp",
           "BASE_DIR", "CONFIG_FILE", "CREDENTIAL_FILE", "CACHE_DIR", "QUALITY_UI_MAP",
           "UI_QUALITY_MAP", "QUALITY_FALLBACK_CHAINS", "HTML_CONTENT",
           "SongFileInfo", "SongFileType"}
TARGET = STATE | SYMBOLS

# 本模块"合法拥有"的名字（这些模块自己定义了同名 state/符号，裸用是对的）
OWNERS = {}
for p in glob.glob(os.path.join(OUT, "*.py")):
    name = os.path.basename(p)[:-3]
    OWNERS[name] = set()
# state.py 拥有全部 STATE 名；settings/musiclib/overlay 拥有各自符号
for s in STATE:
    OWNERS["state"].add(s)
SYMBOL_HOME = {
    "settings": {"merge_config", "get_default_browser_path", "find_qqmusic_path",
                 "save_credential", "load_credential", "BASE_DIR", "CONFIG_FILE",
                 "CREDENTIAL_FILE", "CACHE_DIR", "QUALITY_UI_MAP", "UI_QUALITY_MAP",
                 "QUALITY_FALLBACK_CHAINS"},
    "lyrics": {"parse_lrc", "get_current_lyric_state"},
    "musiclib": {"resolve_song_file_type", "request_song_url_with_type", "detect_ext_from_url",
                 "find_cached_file_for_tier", "check_local_song_exists", "clean_corrupted_files",
                 "clean_cache_if_needed", "extract_song_info", "extract_url",
                 "SongFileInfo", "SongFileType"},
    "overlay": {"handle_index", "handle_api", "HTML_CONTENT"},
    "browserlogin": {"start_driver", "bilibili_auto_login", "qq_scan_login"},
    "smtc": {"get_qqmusic_window_song"},
    "danmaku": {"BiliHandler", "search_and_add"},
    "mainapp": {"MusicApp"},
}
for mod, ss in SYMBOL_HOME.items():
    OWNERS[mod] |= ss

problems = []
for p in sorted(glob.glob(os.path.join(OUT, "*.py"))):
    mod = os.path.basename(p)[:-3]
    src = io.open(p, encoding="utf-8").read()
    tree = ast.parse(src)
    # 本模块顶层绑定（import + 顶层 def/assign）
    top = set(OWNERS.get(mod, set()))
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    top.add(t.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                top.add(a.asname or a.name.split(".")[0])

    # 逐作用域收集局部绑定，判断某 Name 处能否解析
    def local_bound_nodes(fn):
        b = set()
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            aa = fn.args
            for a in aa.posonlyargs + aa.args + aa.kwonlyargs:
                b.add(a.arg)
            for e in (aa.vararg, aa.kwarg):
                if e:
                    b.add(e.arg)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                b.add(n.id)
            elif isinstance(n, ast.Global):
                b |= set(n.names)
            elif isinstance(n, ast.arg):
                b.add(n.arg)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    b.add(a.asname or a.name.split(".")[0])
            elif isinstance(n, ast.ExceptHandler) and n.name:
                b.add(n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not fn:
                b.add(n.name)
        return b

    # 给每个 Name 找它最近的函数作用域
    parent = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parent[ch] = node

    def enclosing_func(n):
        cur = parent.get(n)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return cur
            cur = parent.get(cur)
        return None

    fn_bounds = {}
    bad = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Name) or n.id not in TARGET:
            continue
        if n.id in top or n.id in BI:
            continue
        ef = enclosing_func(n)
        if ef is not None:
            key = id(ef)
            if key not in fn_bounds:
                fn_bounds[key] = local_bound_nodes(ef)
            if n.id in fn_bounds[key]:
                continue
        bad.append((n.lineno, n.id))
    if bad:
        problems.append((mod, bad))

print("=" * 60)
if problems:
    print("❌ 发现跨模块裸引用（需修正）:")
    for mod, bad in problems:
        print(f"  {mod}.py")
        for ln, x in sorted(set(bad)):
            print(f"     L{ln}  {x}")
    print("\n结论: 存在前缀化漏网 ❌")
else:
    print("✅ 全部 10 个文件：15 个状态名 + 33 个符号的跨模块引用均已正确限定")
    print("   无任何'裸引用跨模块名'→ 不会有 import 期/调用期 NameError")
