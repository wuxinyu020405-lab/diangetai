# -*- coding: utf-8 -*-
"""系统托盘（v1.2.2 需求21：缩到托盘）。

设计（用户拍板）：
  - 点窗口 X = 缩到托盘，程序继续收点歌/播放，只有托盘图标在；
  - 托盘**右键菜单**才有"退出"——真退出必走这里，顺带保证进程干净退出（修 #18）。

pystray 约定：
  - icon.run() 阻塞 → 放独立 daemon 线程；菜单回调在 pystray 线程触发，
    凡是要动 Tk 的一律 root.after(0, ...) 编组回主线程（与暂停/切歌按钮同规矩）。
  - 首次最小化时弹一次气泡（notify），告诉用户"还在后台运行"，避免找不到出口。
  - 任何环节失败（老 Windows、缺 DLL、被安全策略拦）都退回普通最小化，
    绝不因托盘起不来而让整个程序崩。

图标：优先 exe 同级/​_MEIPASS 的 app.ico（spec 已带），读不到就用 PIL 现画一个。
"""

import os
import sys
import threading

import pystray
from pystray import MenuItem as Item
from PIL import Image, ImageDraw


def _patch_pystray_filter():
    """R-26：修「托盘未就绪: PermissionError: [WinError 5] 拒绝访问」。

    根因（本机实测）：pystray 0.19.5 建托盘时对新建的消息窗口调用
    ChangeWindowMessageFilterEx(hwnd, WM_TASKBARCREATED, MSGFLT_ALLOW, ...)，
    用来让自己在"提权运行"时也能收到任务栏重建消息。这个调用在不少
    Windows 环境下会直接失败（返回 0 + WinError 5），而 pystray 把它当致命
    错误往上抛 → 托盘整个起不来。

    实际上这个滤波只影响"Explorer 崩溃重启后图标能不能自己回来"这种边缘场景；
    失败也不会影响托盘图标本身的创建与使用（实测：吞掉异常后托盘正常显示、
    右键菜单正常、退出正常）。

    这里把它换成"失败就当成功"的版本。只影响 pystray 内部这一处，
    不动用户环境、不动系统设置。
    """
    try:
        import pystray._util.win32 as _pwin
        _orig = getattr(_pwin, "ChangeWindowMessageFilterEx", None)
        if _orig is None or getattr(_orig, "_r26_patched", False):
            return
        def _safe(hwnd, message, action, pchange):
            try:
                return _orig(hwnd, message, action, pchange)
            except Exception:
                return True          # 当作成功：滤波失败不阻塞托盘
        _safe._r26_patched = True
        _pwin.ChangeWindowMessageFilterEx = _safe
    except Exception:
        pass

import state
import version



def _load_image():
    """托盘图标图像：app.ico → PIL 现画麦克风色块兜底。"""
    try:
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        ico = os.path.join(base, "app.ico")
        if os.path.exists(ico):
            img = Image.open(ico)
            img = img.resize((64, 64), Image.LANCZOS)
            return img
    except Exception:
        pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 58], radius=14, fill=(37, 99, 235, 255))
    d.ellipse([24, 14, 40, 34], fill=(255, 255, 255, 255))       # 麦头
    d.rectangle([30, 30, 34, 44], fill=(255, 255, 255, 255))     # 麦杆
    d.arc([20, 26, 44, 46], 0, 180, fill=(255, 255, 255, 255), width=3)
    return img


class Tray:
    """生命周期由 MusicApp 托管：minimize_to_tray 首次调用时惰性建，quit 时停。"""

    def __init__(self, app):
        self.app = app
        self.icon = None
        self._thread = None
        self._notified = False
        self._error = None
        self._added_ok = False   # R-28：Shell_NotifyIcon(NIM_ADD) 实测成功标记
        self._lock = threading.Lock()

    def _ensure_added(self):
        """R-28：同步执行 Shell_NotifyIcon(NIM_ADD) 并检查返回值。
        成功返回 True；失败返回 False 并把原因写 self._error。

        为什么必须自己来：
          - pystray 原版 _show() 跑在 Shell 回调线程里、返回值直接丢弃——
            NIM_ADD 失败（本机实测返回 0 + WinError 5，UIPI 限制）完全无声；
          - "setup 回调了 = 托盘可用"的老判定是假的 → 窗口 withdraw、图标没进
            Shell → "托盘不显示 + 进程残留"的幽灵状态（R-28 用户实测）。
        NOTIFYICONDATAW 参数与 pystray 原版 _show/_message 一致；注意原版
        hID= 是个不存在的字段名（真字段 uID），ctypes 静默忽略 → pystray
        全程 uID=0，这里必须跟它一致用 0，否则它的 NIM_DELETE 删不掉。
        """
        import ctypes
        try:
            from pystray._util import win32 as _w32
            icon = self.icon
            icon._assert_icon_handle()
            nid = _w32.NOTIFYICONDATAW(
                cbSize=ctypes.sizeof(_w32.NOTIFYICONDATAW),
                hWnd=icon._hwnd,
                uID=0,
                uFlags=_w32.NIF_MESSAGE | _w32.NIF_ICON | _w32.NIF_TIP,
                uCallbackMessage=_w32.WM_NOTIFY,
                hIcon=icon._icon_handle,
                szTip=icon.title or "")
            if _w32.Shell_NotifyIcon(_w32.NIM_ADD, nid):
                icon._visible = True        # 对齐内部态，跳过 setter 防重复 ADD
                self._added_ok = True
                return True
            self._error = "Shell_NotifyIcon(NIM_ADD) 被拒 WinError %s" % ctypes.GetLastError()
        except Exception as e:
            self._error = "%s: %s" % (type(e).__name__, e)
        self._added_ok = False
        return False

    def _cleanup_failed_icon(self):
        """NIM_ADD 失败后的回收：给托盘消息窗口发 WM_STOP → pystray 主循环
        正常收尾（销毁两个窗口、注销窗口类、线程退出）。不留任何托盘线程/
        窗口（幽灵状态防线之一）。"""
        icon = self.icon
        if icon is None:
            return
        try:
            from pystray._util import win32 as _w32
            if getattr(icon, "_hwnd", None):
                _w32.PostMessage(icon._hwnd, _w32.WM_STOP, 0, 0)
        except Exception:
            pass

    # ── 菜单动作：全部编组回 Tk 主线程，只投递意图，不在此线程直接动 Tk ──
    def _show(self, _icon=None, _item=None):
        self.app.root.after(0, self.app.show_from_tray)

    def _quit(self, _icon=None, _item=None):
        self.app.root.after(0, self.app.quit_app)

    def _toggle_pause(self, _icon=None, _item=None):
        self.app.root.after(0, self.app.toggle_pause)

    def _skip(self, _icon=None, _item=None):
        self.app.root.after(0, self.app.request_skip)

    def _pause_text(self, _item=None):
        # pystray 动态文本：打开菜单时实时取暂停态
        return "▶ 继续播放" if state.paused else "⏸ 暂停播放"

    def _build(self):
        menu = pystray.Menu(
            Item("显示主界面", self._show, default=True),
            Item(self._pause_text, self._toggle_pause),
            Item("⏭ 切歌", self._skip),
            Item("退出点歌台", self._quit),
        )
        icon = pystray.Icon("diangetai", _load_image(),
                           f"点歌台 {version.DISPLAY}", menu)
        return icon

    def start(self):
        """惰性建托盘线程。返回 True=托盘可用（可缩进去），False=起不来（调用方退回普通最小化/直接退）。

        关键防呆：icon.run() 在后台线程跑，若启动瞬间就抛异常，而窗口已经
        withdraw → 用户被困在"既无窗口也无托盘"状态。这里用 Event 等首帧确认
        （最多 2 秒）：setup 里**实测 NIM_ADD 注册进 Shell 成功**才置 ok；
        超时/异常/注册被拒都算失败——宁可退回最小化，也绝不 withdraw 后没托盘
        （R-28：老版本 setup 回调即算成功，注册被无声拒绝时就是幽灵状态）。"""
        with self._lock:
            if self.icon is not None:
                return True
            _patch_pystray_filter()      # R-26：先修掉那个必抛 WinError5 的调用
            try:
                self.icon = self._build()
            except Exception as e:
                self.app.log(f"⚠️ 托盘初始化失败: {e}")
                self.icon = None
                return False
            ready = threading.Event()
            self._error = None
            self._ok = False
            self._added_ok = False
            t = threading.Thread(target=self._run, args=(ready,), daemon=True)
            t.start()
            ready.wait(2.0)
            # 只有 setup 真正回调且 NIM_ADD 实测成功（_ok=True）才认定托盘可用
            if not self._ok:
                self.app.log(f"⚠️ 托盘未就绪" + (f": {self._error}" if self._error else "（超时）")
                             + "（改为最小化窗口）")
                self._cleanup_failed_icon()
                self.icon = None
                return False
            return True

    def _run(self, ready):
        try:
            def _setup(icon):
                # R-28：不再"回调即成功"。先同步把图标真注册进 Shell 并验返回值，
                # 失败就地回收，让 start() 走降级。**绝不允许"窗口已藏 + 托盘没
                # 注册 + 进程还活着"的幽灵状态**——那正是用户看到的
                # "托盘不显示但进程残留"。
                if self._ensure_added():
                    self._ok = True
                else:
                    self._cleanup_failed_icon()
                ready.set()
            self.icon.run(setup=_setup)
        except Exception as e:
            if self._error is None:
                self._error = f"{type(e).__name__}: {e}"
            self._cleanup_failed_icon()
            ready.set()

    def notify(self, title, text):
        """首次缩入时的一次性气泡。失败静默（不影响主流程）。"""
        if self._notified or self.icon is None:
            return
        self._notified = True
        try:
            self.icon.notify(text, title)
        except Exception:
            pass

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.visible = False
            except Exception:
                pass
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
