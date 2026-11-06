"""
运行时共享状态：跨模块可变的全局，一律以 state.xxx 读写
"""


# ===== v1.2.5：单实例互斥体 + 外部"优雅退出"通道 =====
# 两个都是 Windows 命名内核对象，**必须与 点歌台.iss 里的
# AppMutex / QuitEventName 逐字一致**，否则安装器认不出、也通知不到运行中的实例。
#   APP_MUTEX_NAME：单实例锁（main._acquire_single_instance 创建；进程活着就一直在，
#                   安装器靠它判断"点歌台是否还在跑"）
#   QUIT_EVENT_NAME：外部退出事件（mainapp._start_quit_watcher 监听；安装包覆盖
#                   升级时置位 → 程序走 quit_app 落盘后自行退出，不做强杀）
APP_MUTEX_NAME = "Local\\DianGeTai_SingleInstance_v1"
QUIT_EVENT_NAME = "Local\\DianGeTai_Quit_v1"


# ================= 全局状态 =================
playlist = []        # 就绪队列：只含"缓存命中或下载成功"的歌（需求1）

pending_requests = []  # 需求3：点歌待处理队列（串行：本首出结论才处理下一首）

processing_request = None  # v1.2.2·队列管理页：song_request_worker 正在处理的那条（出列≠消失）

# 第5步：配额保护记账（下载侧；缓存播放不受其约束）
# 持久化在 quota_state.json（跨重启有效：服务端配额并不会因重启而重置）
quota_state = {"date": "", "downloaded": 0, "fail_streak": 0, "cooldown_until": 0.0}

current_song = None

# ===== v1.2.4：直播间弹幕历史（环形缓存，供本机 AI 接口 /api/danmaku 读取）=====
# 容量可调：config.json 的 danmaku_history_size（默认 200，0=关闭不收）。
# 只存内存，不落盘（隐私+无痕）。每条 {ts, platform, uname, text, is_cmd}
danmaku_history = []
danmaku_history_size = 200

skip_event = None

pause_event = None   # v1.1·N1：暂停意图（set=暂停当前歌播放；实测 pygame pause 期间 get_pos 冻结，歌词天然同步）

paused = False       # 当前实际暂停态（GUI 按钮/日志用；只停播放，队列下载不受影响=用户拍板）

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
        "show_requester": True, "requester_sep": "-",
        "align": "left"          # v1.1·N3：点歌列表对齐（left/center/right，默认=旧行为左对齐）
    },
    "global": {"volume": 1.0},         # 第6步·高价值2：点歌播放音量（pygame）
    "audio_quality": "flac",
    "max_cache_files": 100,
    "max_cache_size_mb": 500
}

overlay_port = 8080   # OBS 挂件实际监听端口（8080 被占时自动顺延，GUI 复制地址读这里）

douyin_status = ""    # v1.2·抖音通道状态（provider 写、GUI 轮询读）：连接中/已连接/停用原因

current_play_mode = "local"

is_local_playing = True    

bgm_paused_by_bot = False

active_lrc_lines = []

active_song_start_ts = 0.0

active_song_base_pos = 0.0
