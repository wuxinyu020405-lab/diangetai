"""
运行时共享状态：跨模块可变的全局，一律以 state.xxx 读写
"""


# ================= 全局状态 =================
playlist = []        # 就绪队列：只含"缓存命中或下载成功"的歌（需求1）

pending_requests = []  # 需求3：点歌待处理队列（串行：本首出结论才处理下一首）

# 第5步：配额保护记账（下载侧；缓存播放不受其约束）
# 持久化在 quota_state.json（跨重启有效：服务端配额并不会因重启而重置）
quota_state = {"date": "", "downloaded": 0, "fail_streak": 0, "cooldown_until": 0.0}

current_song = None

skip_event = None

app = None

system_media_info = {"title": "暂无播放", "artist": ""}

current_lyric_info = {"lines": [], "all_lines": [], "active_idx": -1}

lyric_cache = {}  

qq_credential = None 

# 👇 完整独立配置结构（含歌词对齐与第6步恢复的歌词透明度 lyric.opacity）
style_config = {
    "mixed": {
        "show_playing": True, "show_queue": True, "show_lyric": True,
        "font_playing": "'PingFang SC', 'Microsoft YaHei', sans-serif", "color_playing": "#00FFFF", "size_playing": 32, "bold_playing": False,
        "font_lyric": "'PingFang SC', 'Microsoft YaHei', sans-serif", "color_lyric": "#FFE600", "size_lyric": 28, "effect_lyric": "static", "bold_lyric": False,
        "font_queue": "'PingFang SC', 'Microsoft YaHei', sans-serif", "color_queue": "#FFFFFF", "size_queue": 36, "bold_queue": False,
        # ── 第6步：综合挂件独立成一套（修 16.3 三个失效项 + 高价值3/5/6）──
        "show_prefix": True, "show_icon": True, "max_chars": 0,        # 16.3-①②；#3 图标/文字分开控制
        # 综合源歌词：#2 默认只两行（当前行 + 下一行）、默认静态无滚动、默认左对齐
        "align": "left", "lines_prev": 0, "lines_next": 1,
        "max_items": 0,                            # 高价值3：0=不限(=现状)
        "show_index": True, "show_requester": True, "requester_sep": "-"   # 高价值5/6
    },
    "lyric": {
        "font": "'PingFang SC', 'Microsoft YaHei', sans-serif",
        "color": "#FFE600", "size": 28, "align": "center",
        "effect": "apple_hd", "lines_prev": 2, "lines_next": 2,
        "pure_text": "纯音乐, 请欣赏..", "is_bold": False,
        "opacity": 1.0,             # 第6步·高价值1：T-A 系数，0~2.0（1.0=原样，>1 提亮暗行）
        "line_spacing": 142         # #6 行间距百分比（142=现状 line-height 1.42）
    },
    "playing": {
        "font": "'PingFang SC', 'Microsoft YaHei', sans-serif",
        "color": "#00FFFF", "size": 32, "show_prefix": True, "is_bold": False
    },
    "queue": {
        "font": "'PingFang SC', 'Microsoft YaHei', sans-serif",
        "color": "#FFFFFF", "size": 36, "max_chars": 30, "is_bold": False,
        "max_items": 0, "show_index": True,
        "show_requester": True, "requester_sep": "-"
    },
    "global": {"volume": 1.0},         # 第6步·高价值2：点歌播放音量（pygame）
    "audio_quality": "flac",
    "max_cache_files": 100,
    "max_cache_size_mb": 500
}

overlay_port = 8080   # OBS 挂件实际监听端口（8080 被占时自动顺延，GUI 复制地址读这里）

current_play_mode = "local"

is_local_playing = True    

bgm_paused_by_bot = False

active_lrc_lines = []

active_song_start_ts = 0.0

active_song_base_pos = 0.0
