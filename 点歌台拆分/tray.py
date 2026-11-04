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
        self._lock = threading.Lock()

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
        （最多 2 秒）：run 里先置 ok、异常置 error，start 据 error 决定放行/退回。"""
        with self._lock:
            if self.icon is not None:
                return True
            try:
                self.icon = self._build()
            except Exception as e:
                self.app.log(f"⚠️ 托盘初始化失败: {e}")
                self.icon = None
                return False
            ready = threading.Event()
            self._error = None
            self._ok = False
            t = threading.Thread(target=self._run, args=(ready,), daemon=True)
            t.start()
            ready.wait(2.0)
            # 只有 setup 真正回调（_ok=True）才认定托盘可用；
            # 超时或异常都算失败——宁可退回最小化，也绝不 withdraw 后没托盘
            if not self._ok:
                self.app.log(f"⚠️ 托盘未就绪" + (f": {self._error}" if self._error else "（超时）")
                             + "（改为最小化窗口）")
                self.icon = None
                return False
            return True

    def _run(self, ready):
        try:
            def _setup(icon):
                icon.visible = True
                self._ok = True          # 确认信号：setup 被回调 = 消息循环真起来了
                ready.set()
            self.icon.run(setup=_setup)
        except Exception as e:
            self._error = f"{type(e).__name__}: {e}"
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
