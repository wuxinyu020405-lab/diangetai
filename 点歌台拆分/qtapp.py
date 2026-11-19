# -*- coding: utf-8 -*-
"""(R-15) PySide6 + PySide6-Fluent-Widgets 界面层。

导航按"主播什么时候用"重排成 5 类：直播台 / 音质与播放 / 账号与弹幕 / OBS 挂件 / 运行日志，
版本与更新放侧栏底部「关于」。

与 mainapp 的契约沿用旧版（self.lbl_xxx / entry_xxx / sw_xxx / combo_xxx ...），
所以主程序逻辑几乎不用改：这里用 qtshim 的适配器把 Qt 控件包成 tkinter 那张脸。
"""

import os
import sys
import traceback

from PySide6.QtCore import Qt, QObject, QTimer, QMetaObject, Slot
from PySide6.QtGui import QIcon, QFont, QColor, QTextCursor
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QGridLayout, QLabel, QSizePolicy, QFrame)

from qfluentwidgets import (
    FluentWindow, ScrollArea, CardWidget, SubtitleLabel, BodyLabel, StrongBodyLabel,
    CaptionLabel, TitleLabel, PrimaryPushButton, PushButton, TransparentPushButton,
    ToolButton, HyperlinkButton, LineEdit, ComboBox, SwitchButton, Slider, SpinBox,
    PlainTextEdit, TabWidget, MessageBox, Dialog, FluentIcon, setTheme, Theme,
    NavigationItemPosition, IconWidget, InfoBar, InfoBarPosition,
    TabCloseButtonDisplayMode, setThemeColor, qconfig, ToolButton,
    RoundMenu, Action, isDarkTheme,
)

import fontlib
import qtshim
import settings
import state
import version
import updater


# ════════════════ 控件适配器（给 mainapp 用的老接口）════════════════

def _log_warn(what, exc):
    """日志自身出问题时带类型打一行到控制台，绝不静默吞（L-46）。"""
    try:
        print(f"[WARN] {what}: {type(exc).__name__}: {exc}")
    except Exception:
        pass


class LogAdapter:
    """日志框：mainapp 里调 log_text.insert(tk.END, ...) / .see(tk.END)。

    R-29：原来日志无限往里堆，条目一多就把界面挤满、新行也看不见。现在：
      · 限长 MAX_BLOCKS 行（setMaximumBlockCount，超出自动从顶部裁掉旧行）
      · 自动滚到底改用「光标移文末 + ensureCursorVisible」——原来的
        setValue(bar.maximum()) 可能在 append 后拿到布局前的旧 maximum，跟不住新行
      · 粘性滚动：用户手动往上翻读旧日志时不把他拽回底部；翻回底部后自动恢复跟随
    """

    MAX_BLOCKS = 300        # 日志框最多保留的行数（旧行从顶部自动裁掉）
    BOTTOM_EPS = 8          # 距底部 8px 内都算「正在看最新」

    def __init__(self, widget):
        self.w = widget
        self._follow = True   # 下一条日志是否要自动滚到底（insert 时按用户位置重算）
        try:
            self.w.setMaximumBlockCount(self.MAX_BLOCKS)
        except Exception as e:
            _log_warn("日志框限长设置失败（日志仍可显示，只是不会自动裁旧）", e)

    def _at_bottom(self):
        """当前是否停在底部附近。读不到就按「跟随」处理，宁可滚也不能看不到新日志。"""
        try:
            bar = self.w.verticalScrollBar()
            return bar.value() >= bar.maximum() - self.BOTTOM_EPS
        except Exception as e:
            _log_warn("读取日志滚动位置失败", e)
            return True

    def _apply_end_scroll(self):
        """把光标移到文末并确保可见（同步可靠，不依赖滚动条 maximum 的时机）。"""
        try:
            cur = self.w.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            self.w.setTextCursor(cur)
            self.w.ensureCursorVisible()
        except Exception as e:
            _log_warn("日志滚动到底失败", e)

    def _scroll_to_end(self):
        self._apply_end_scroll()
        # 兜底：append 后布局可能还没算完，下一轮事件循环再滚一次（0ms 延迟）
        try:
            QTimer.singleShot(0, self._apply_end_scroll)
        except Exception as e:
            _log_warn("日志滚动兜底调度失败", e)

    def insert(self, _index, text):
        # 先记下「用户此刻是不是在看最新」，再写日志——写完才判断就晚了
        self._follow = self._at_bottom()
        try:
            self.w.appendPlainText(str(text).rstrip())
        except Exception as e:
            _log_warn("日志写入失败", e)
            return
        if self._follow:
            self._scroll_to_end()

    def see(self, _index):
        # mainapp.log 是「先 insert 再 see」；这里沿用 insert 刚做出的跟随判断，
        # 否则无条件滚一次会把用户的粘性滚动打回底部。
        if self._follow:
            self._scroll_to_end()

    def configure(self, **_kw):
        return self


class ListBoxAdapter:
    """队列列表容器：mainapp.refresh_queue_mgmt 往里面塞行（改由 render_queue 统一画）。"""

    def __init__(self, widget):
        self.w = widget
        self.layout = QVBoxLayout(widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)


# ════════════════ 通用小工具 ════════════════

def _card(parent, title=None, desc=None):
    """一张 Fluent 卡片，返回 (卡片, 内容区 QVBoxLayout)。"""
    card = CardWidget(parent)
    outer = QVBoxLayout(card)
    outer.setContentsMargins(20, 16, 20, 18)
    outer.setSpacing(10)
    if title:
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(SubtitleLabel(title, card))
        if desc:
            lb = CaptionLabel(desc, card)
            lb.setTextColor(QColor(120, 120, 120), QColor(160, 160, 160))
            head.addWidget(lb)
        outer.addLayout(head)
    return card, outer


def _row(layout):
    """一行横排（返回 QHBoxLayout，已加入父布局）。"""
    row = QHBoxLayout()
    row.setSpacing(8)
    layout.addLayout(row)
    return row


def _label_row(parent_layout, text, widget):
    """「左侧说明 + 右侧控件」一行。"""
    row = _row(parent_layout)
    lb = BodyLabel(text, widget.parent() if widget.parent() else None)
    lb.setMinimumWidth(150)
    row.addWidget(lb)
    row.addWidget(widget)
    row.addStretch(1)
    return lb


# ════════════════ 主窗口（同时充当 tk root 的替身）════════════════

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        # R-17：关掉云母/亚克力背景，文字才用得上 ClearType 亚像素渲染。
        # 开着 mica 时整窗是半透明的，Qt 会把文字降级成灰色抗锯齿，
        # 在 175%~200% 缩放下看着发虚（实测彩边像素占比 0.02% → 1.34%）。
        try:
            self.setMicaEffectEnabled(False)
        except Exception:
            pass
        # 云母关掉后，窗口底色是 Qt 自己画的；库不会在换主题时重刷这层，
        # 不补这一下，启动时（或刚切完主题）会看到「浅色内容 + 深色底」。
        try:
            qconfig.themeChangedFinished.connect(self._sync_window_background)
        except Exception:
            pass
        self._close_cb = None
        self._pending = []
        self._pages = {}
        # R-26 问题3：默认打开 = 屏幕正中 + 高度取最小允许值。
        # 宽度给 900（= 最小宽度，保证导航栏和内容都不挤），高度取最小值 680。
        self.setMinimumSize(900, 680)
        self.resize(900, 680)
        # R-26 问题2：关掉切页的"从下往上滑入"动画。
        # 那个动画是库自带的 PopUpAniStackedWidget（新页从 y+76 滑上来 + 300ms 缓动），
        # 在本机 200% 缩放下逐帧移动像素、又叠着窗口重绘，肉眼就是"抖动"。
        # 用户此前明确说过讨厌"慢慢变清晰"的过渡，所以这里直接关掉，改瞬间切换。
        try:
            self.stackedWidget.setAnimationEnabled(False)
        except Exception:
            pass
        try:
            self.navigationInterface.setMinimumExpandWidth(600)   # 别按窗口宽度自动收起
            self.navigationInterface.setExpandWidth(210)
            self.navigationInterface.expand(useAni=False)
        except Exception:
            pass
        self._about = None
        # 标题栏右上角的明暗切换（默认跟随系统，点一下变深色/浅色并记住）
        try:
            self.btn_theme = ToolButton(_icon("BRIGHTNESS", _icon("SETTING")), self.titleBar)
            self.btn_theme.setToolTip("切换深色 / 浅色")
            self.btn_theme.clicked.connect(self.toggle_theme)
            self.btn_theme.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.btn_theme.customContextMenuRequested.connect(self.show_theme_menu)
            layout = self.titleBar.hBoxLayout
            self._titlebar_layout = layout
            layout.insertWidget(max(0, layout.count() - 1), self.btn_theme, 0,
                                Qt.AlignmentFlag.AlignRight)
        except Exception:
            self.btn_theme = None
        # R-18：标题栏「界面字体大小」按钮（点一下选档位）
        try:
            self.btn_scale = ToolButton(FluentIcon.FONT_SIZE, self.titleBar)
            self.btn_scale.setToolTip("界面字体大小：标准（点一下可改）")
            self.btn_scale.clicked.connect(self.show_scale_menu)
            self._titlebar_layout.insertWidget(
                max(0, self._titlebar_layout.count() - 1), self.btn_scale, 0,
                Qt.AlignmentFlag.AlignRight)
        except Exception:
            self.btn_scale = None

    # ── tk root 兼容接口（mainapp 直接调这些名字）──
    def after(self, ms, fn):
        handle = {"cancelled": False}
        self._pending.append((int(ms), fn, handle))
        try:
            QMetaObject.invokeMethod(self, "_drain_pending", Qt.ConnectionType.QueuedConnection)
        except Exception:
            try:
                fn()
            except Exception:
                traceback.print_exc()
        return handle

    @Slot()
    def _drain_pending(self):
        items = list(self._pending)
        self._pending.clear()
        for ms, fn, handle in items:
            QTimer.singleShot(ms, lambda f=fn, h=handle: self._run_pending(f, h))

    def _run_pending(self, fn, handle):
        if handle.get("cancelled"):
            return
        try:
            fn()
        except Exception:
            traceback.print_exc()

    def after_cancel(self, handle):
        try:
            handle["cancelled"] = True
        except Exception:
            pass

    def title(self, text):
        try:
            self.setWindowTitle(str(text))
        except Exception:
            pass

    def geometry(self, *args):
        """tk 的 root.geometry("980x850") 与 Qt 自己的 geometry() 共用一个名字：
        不带参数 = 交给 Qt 读矩形；带字符串 = 按 tk 写法改尺寸。"""
        if not args:
            return FluentWindow.geometry(self)
        try:
            w, h = str(args[0]).split("x")
            self.resize(int(w), int(h))
        except Exception:
            pass

    def protocol(self, name, fn):
        if str(name).upper().startswith("WM_DELETE"):
            self._close_cb = fn

    # ── R-26：补上 mainapp/tray 一直在用、但 Qt 版窗口没实现的 tk 名字 ──
    # 之前缺这几个，出现两个后果：
    #   ① 托盘起不来走降级分支时调 self.root.iconify() → AttributeError
    #      → WM_DELETE_WINDOW 回调整体失败 → 点 X 既不缩托盘也不最小化，
    #      用户只能任务管理器强杀（用户实测反馈的原话）。
    #   ② 托盘菜单「显示主界面」里 deiconify/lift/focus_force 同样缺失。
    def iconify(self):
        """最小化到任务栏（tk root.iconify 的替身）。"""
        try:
            self.showMinimized()
        except Exception:
            pass

    def withdraw(self):
        """隐藏窗口但进程继续跑（缩托盘用）。"""
        try:
            self.hide()
        except Exception:
            pass

    def deiconify(self):
        """从隐藏/最小化恢复显示。"""
        try:
            self.showNormal()
            self.show()
        except Exception:
            pass

    def lift(self):
        try:
            self.raise_()
        except Exception:
            pass

    def focus_force(self):
        try:
            self.activateWindow()
        except Exception:
            pass

    def wm_attributes(self, *args, **kwargs):
        """窗口属性（-topmost 之类）。目前只做无害兼容。"""
        return None

    def attributes(self, *args, **kwargs):
        return None

    def state(self, arg=None):
        if arg is None:
            return "withdrawn" if (self.isMinimized() or not self.isVisible()) else "normal"
        if str(arg).lower() == "normal":
            self.showNormal()
            self.raise_()
            self.activateWindow()
            return "normal"
        if str(arg).lower() in ("withdrawn", "iconic"):
            self.hide()
            return "withdrawn"
        return "normal"

    def iconbitmap(self, path):
        try:
            if path and os.path.exists(path):
                self.setWindowIcon(QIcon(path))
        except Exception:
            pass

    def configure(self, **_kw):
        return None

    def minsize(self, w, h):
        try:
            self.setMinimumSize(int(w), int(h))
        except Exception:
            pass

    def closeEvent(self, event):
        if self._close_cb is not None:
            try:
                self._close_cb()
            except Exception:
                traceback.print_exc()
            event.ignore()
            return
        event.accept()

    def _sync_window_background(self):
        """按当前明暗把窗口底色重画一遍（关云母后库不会自动做这件事）。"""
        try:
            self.setBackgroundColor(self._normalBackgroundColor())
            self.update()
        except Exception:
            pass

    # ── R-16 深色模式：跟随系统为默认，点一下切明暗，右键三选一并记住 ──

    def _remember_theme(self, name):
        """把用户选的模式写进配置，下次启动照这个来。"""
        app = getattr(self, "music_app", None)
        if app is None:
            return
        try:
            app.config["ui_theme"] = name
            app.schedule_save_style()
        except Exception:
            pass

    def set_theme(self, name):
        """切到指定模式：auto(跟随系统) / light(浅色) / dark(深色)。"""
        apply_theme(name)
        self._remember_theme(current_theme_name())
        self.update_theme_button()

    def toggle_theme(self):
        """点一下：浅色 <-> 深色（跟随系统时按当前实际明暗反过来）。"""
        self.set_theme("light" if isDarkTheme() else "dark")

    def show_theme_menu(self, pos=None):
        """右键菜单：跟随系统 / 浅色 / 深色。"""
        btn = getattr(self, "btn_theme", None)
        if not btn:
            return
        menu = RoundMenu(parent=btn)
        cur = current_theme_name()
        for key, label in (("auto", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            act = Action(FluentIcon.ACCEPT if key == cur else FluentIcon.BRIGHTNESS,
                         label, menu)
            act.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            menu.addAction(act)
        try:
            point = btn.mapToGlobal(pos or btn.rect().center())
            menu.exec(point)
        except Exception:
            pass

    def update_theme_button(self):
        if not getattr(self, "btn_theme", None):
            return
        cur = {"auto": "跟随系统", "light": "浅色",
               "dark": "深色"}.get(current_theme_name(), "跟随系统")
        tip = "外观：%s · 点一下切%s · 右键可选「跟随系统/浅色/深色」" % (
            cur, "深色" if not isDarkTheme() else "浅色")
        try:
            self.btn_theme.setToolTip(tip)
        except Exception:
            pass

    def _remember_scale(self, key):
        app = getattr(self, "music_app", None)
        if app is None:
            return
        try:
            app.config["ui_scale"] = key
            app.schedule_save_style()
        except Exception:
            pass

    def set_ui_scale(self, key):
        """切字号档位（立即生效，不用重启），并记住。"""
        apply_ui_scale(self, key)
        self._remember_scale(current_ui_scale_key())
        self.update_scale_button()

    def show_scale_menu(self, pos=None):
        btn = getattr(self, "btn_scale", None)
        if not btn:
            return
        menu = RoundMenu(parent=btn)
        cur = current_ui_scale_key()
        for key, text, value in _UI_SCALE_CHOICES:
            act = Action(FluentIcon.ACCEPT if key == cur else FluentIcon.FONT_SIZE,
                         "%s（%d%%）" % (text, round(value * 100)), menu)
            act.triggered.connect(lambda _=False, k=key: self.set_ui_scale(k))
            menu.addAction(act)
        try:
            menu.exec(btn.mapToGlobal(pos or btn.rect().center()))
        except Exception:
            pass

    def update_scale_button(self):
        btn = getattr(self, "btn_scale", None)
        if not btn:
            return
        text = _UI_SCALE_TEXT.get(current_ui_scale_key(), "标准")
        try:
            btn.setToolTip("界面字体大小：%s（点一下可改）" % text)
        except Exception:
            pass

    def show_about(self):
        """打开「关于」。R-20：以前这里抛异常会被 Qt 的信号机制吞掉，
        界面上就是「点了没反应」，所以整段包起来、出错写进运行日志。"""
        try:
            if self._about is not None:
                try:
                    self._about.close()
                except Exception:
                    pass
            self._about = AboutDialog(self)
            try:
                apply_ui_scale(self._about, current_ui_scale_key())
            except Exception:
                pass
            self._about.exec()
        except Exception as e:
            traceback.print_exc()
            try:
                app = getattr(self, "music_app", None)
                if app is not None:
                    app.log("⚠️ 「关于」窗口打不开：%s: %s" % (type(e).__name__, e))
            except Exception:
                pass


class AboutDialog(MessageBox):
    """侧栏底部「关于」：版本号 + 检查更新 + 下载新版（沿用 updater 的浏览器直链）。"""

    def __init__(self, parent):
        super().__init__("点歌台 " + version.DISPLAY,
                         "开源 GPL-3.0 · 仅供自用/朋友间私发，请勿商用。\n\n"
                         "点「检查更新」看看有没有新版；有新版时点「下载新版」，"
                         "浏览器会直接开始下载 Setup 安装包。\n\n"
                         "外观（深色/浅色、字体大小）在右上角那个小太阳/字号按钮里调。",
                         parent)
        self.app = getattr(parent, "music_app", None)
        self.yesButton.setText("检查更新")
        self.cancelButton.setText("关闭")
        # R-20：qfluentwidgets 1.11 的 MessageBox 没有 addButton（老版本才有）。
        # 之前这里抛 AttributeError，被 Qt 信号机制吞掉 → 点了「关于」毫无反应。
        self.dlButton = PushButton("下载新版", self)
        placed = False
        for how in ("insertWidget", "addWidget"):
            try:
                if how == "insertWidget":
                    self.buttonLayout.insertWidget(1, self.dlButton, 1,
                                                   Qt.AlignmentFlag.AlignVCenter)
                else:
                    self.buttonLayout.addWidget(self.dlButton, 1,
                                                Qt.AlignmentFlag.AlignVCenter)
                placed = True
                break
            except Exception:
                continue
        self.dlButton.clicked.connect(lambda _=False: self._download())
        # 库的「确定」只负责关窗，不会调我们的 _on_yes；这里手动接一次「检查更新」
        try:
            self.yesButton.clicked.connect(lambda _=False: self._on_yes())
        except Exception:
            pass
        self._refresh()

    def _refresh(self):
        info = updater.latest_info() if hasattr(updater, "latest_info") else {}
        tag = (info or {}).get("tag")
        if tag:
            self.contentLabel.setText("发现新版本 %s（当前 %s）。\n点「下载新版」用默认浏览器下载安装包。"
                                      % (tag, version.DISPLAY))

    def _download(self):
        if self.app is not None:
            updater.open_setup_download(self.app)
        else:
            try:
                updater.open_setup_download()
            except Exception:
                pass

    def _on_yes(self):
        # 点「检查更新」
        if self.app is not None:
            updater.manual_check(self.app)
        self._refresh()


# ════════════════ 入口 ════════════════

_THEME_BY_NAME = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
_THEME_NAME = {Theme.AUTO: "auto", Theme.LIGHT: "light", Theme.DARK: "dark"}

# 用户选的是「跟随系统 / 浅色 / 深色」这个偏好本身；
# qconfig.theme 只反映系统解析后的结果（系统是深色时 AUTO 也会变成 DARK），
# 所以要单独记住偏好，否则分不清「跟随系统」和「手动深色」。
_theme_pref = "auto"


def apply_theme(name):
    """按名字切主题：auto(跟随系统) / light(浅色) / dark(深色)。"""
    global _theme_pref
    key = str(name or "auto").lower()
    if key not in _THEME_BY_NAME:
        key = "auto"
    _theme_pref = key
    try:
        setTheme(_THEME_BY_NAME[key])
    except Exception:
        pass
    return _THEME_BY_NAME[key]


def current_theme_name():
    """当前偏好：auto / light / dark。"""
    return _theme_pref


# ════════════════ R-18 界面字号档位 ════════════════
# 只放大/缩小文字，窗口大小不动；卡片会跟着长高，列表页可以滚。
# 为什么不用 QT_SCALE_FACTOR：那是启动前就要设好的环境变量，改完必须重启；
# 而且它会连图标、间距一起放大，在 200% 缩放的屏上窗口直接顶出屏幕。

_UI_SCALE_CHOICES = (
    ("small", "小", 0.8),
    ("normal", "标准", 1.0),
    ("large", "大", 1.2),
    ("xlarge", "特大", 1.4),
)
_UI_SCALE_VALUE = {k: v for k, _t, v in _UI_SCALE_CHOICES}
_UI_SCALE_TEXT = {k: t for k, t, _v in _UI_SCALE_CHOICES}
_ui_scale_key = "normal"


def ui_scale_value(key):
    return _UI_SCALE_VALUE.get(str(key or "normal"), 1.0)


def current_ui_scale_key():
    return _ui_scale_key


def _font_bases(root):
    """记下每个控件「原本的字号」：缩放时按原值×系数重算，来回切不会越滚越大。"""
    bases = getattr(root, "_font_bases", None)
    if bases is None:
        bases = {}
        try:
            root._font_bases = bases
        except Exception:
            pass
    widgets = [root]
    try:
        widgets.extend(root.findChildren(QWidget))
    except Exception:
        pass
    for w in widgets:
        if w in bases:
            continue
        try:
            f = w.font()
        except Exception:
            continue
        if f.pixelSize() > 0:
            bases[w] = ("px", f.pixelSize())
        elif f.pointSizeF() > 0:
            bases[w] = ("pt", f.pointSizeF())
    return bases


def apply_ui_scale(root, key):
    """按档位把 root 这棵控件树的字号放大/缩小（root 可以是整窗，也可以是新造的一行）。"""
    global _ui_scale_key
    key = str(key or "normal")
    if key not in _UI_SCALE_VALUE:
        key = "normal"
    _ui_scale_key = key
    k = _UI_SCALE_VALUE[key]
    bases = _font_bases(root)
    for w, (kind, size) in list(bases.items()):
        try:
            f = QFont(w.font())
            if kind == "px":
                f.setPixelSize(max(8, int(round(size * k))))
            else:
                f.setPointSizeF(max(6.0, round(size * k, 2)))
            w.setFont(f)
        except RuntimeError:
            bases.pop(w, None)     # 控件已经销毁
        except Exception:
            pass
    try:
        root.updateGeometry()
        root.update()
    except Exception:
        pass


def make_app():
    """建 QApplication（必须在 GUI 线程、且只建一次）。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    # R-16：默认跟随系统（Win11 设置里是浅色就浅色、深色就深色），
    # 用户也能在标题栏一键切换并记住选择。
    apply_theme("auto")       # 默认跟随系统，build 时再按配置恢复
    try:
        setThemeColor(QColor("#0067C0"))   # 主色统一成 Windows 蓝（库会按明暗自动配深浅）
    except Exception:
        pass
    try:
        app.setStyleSheet("")   # 交给 Fluent 主题
    except Exception:
        pass
    return app


# ════════════════ 页面 ════════════════

def _icon(name, fallback=FluentIcon.DOCUMENT):
    return getattr(FluentIcon, name, fallback)


class BasePage(ScrollArea):
    def __init__(self, route, app, parent=None):
        super().__init__(parent)
        self.setObjectName(route)
        self.app = app
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.viewport().setStyleSheet("background:transparent;")
        self.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._host = QWidget()
        self._host.setStyleSheet("background:transparent;")
        self.body = QVBoxLayout(self._host)
        self.body.setContentsMargins(20, 6, 20, 20)
        self.body.setSpacing(14)
        self.setWidget(self._host)
        self.view = self.body

    def add_card(self, title=None, desc=None):
        card, lay = _card(self._host, title, desc)
        self.body.addWidget(card)
        return card, lay

    def finish(self):
        self.body.addStretch(1)


class LivePage(BasePage):
    """直播台：在播 + 队列 + 切歌/暂停 + 快速加歌。"""

    def __init__(self, app, parent=None):
        super().__init__("livePage", app, parent)
        self.setObjectName("livePage")

        # 当前在播
        card, lay = self.add_card("正在播放", "直播中你最常看的就是这一块")
        self.lbl_now = StrongBodyLabel("——", card)
        f = QFont(self.lbl_now.font())
        f.setPointSize(16)
        self.lbl_now.setFont(f)
        lay.addWidget(self.lbl_now)
        self.lbl_requester = CaptionLabel("", card)
        lay.addWidget(self.lbl_requester)
        row = _row(lay)
        self.btn_pause = PrimaryPushButton("⏸ 暂停播放", card)
        self.btn_pause.clicked.connect(lambda: app.toggle_pause())
        row.addWidget(self.btn_pause)
        self.btn_skip = PushButton("⏭ 切歌", card)
        self.btn_skip.clicked.connect(lambda: app.request_skip())
        row.addWidget(self.btn_skip)
        self.lbl_room_state = CaptionLabel("", card)
        row.addWidget(self.lbl_room_state)
        row.addStretch(1)

        # 快速加歌
        card, lay = self.add_card("快速加歌", "自己试歌用；观众那边是发弹幕「点歌 歌名」")
        row = _row(lay)
        self.entry_add_song = LineEdit(card)
        self.entry_add_song.setPlaceholderText("输入歌名，回车或点右边按钮")
        self.entry_add_song.setClearButtonEnabled(True)
        self.entry_add_song.setMinimumWidth(320)
        row.addWidget(self.entry_add_song, 1)
        btn = PrimaryPushButton("点歌", card)
        btn.clicked.connect(self._add_online)
        row.addWidget(btn)
        btn2 = PushButton("本地点歌", card)
        btn2.clicked.connect(self._add_local)
        row.addWidget(btn2)
        self.entry_add_song.returnPressed.connect(self._add_online)

        # 队列
        card, lay = self.add_card("点歌队列", "处理中＝正在下载；已就绪＝下载好等播")
        row = _row(lay)
        self.lbl_qm_summary = BodyLabel("", card)
        row.addWidget(self.lbl_qm_summary, 1)
        btn = ToolButton(_icon("SYNC"), card)
        btn.setToolTip("刷新队列")
        btn.clicked.connect(lambda: app.refresh_queue_mgmt())
        row.addWidget(btn)

        cap = CaptionLabel("处理中", card)
        lay.addWidget(cap)
        self.qm_pending_box = QWidget(card)
        self.qm_pending_layout = QVBoxLayout(self.qm_pending_box)
        self.qm_pending_layout.setContentsMargins(0, 0, 0, 0)
        self.qm_pending_layout.setSpacing(6)
        lay.addWidget(self.qm_pending_box)

        cap = CaptionLabel("已就绪待播", card)
        lay.addWidget(cap)
        self.qm_ready_box = QWidget(card)
        self.qm_ready_layout = QVBoxLayout(self.qm_ready_box)
        self.qm_ready_layout.setContentsMargins(0, 0, 0, 0)
        self.qm_ready_layout.setSpacing(6)
        lay.addWidget(self.qm_ready_box)
        self.finish()

    def _add_online(self):
        name = self.entry_add_song.text().strip()
        if not name:
            return
        self.entry_add_song.clear()
        import danmaku
        danmaku.handle_message(self.app, "点歌 " + name, "主播(控制台)")

    def _add_local(self):
        name = self.entry_add_song.text().strip()
        if not name:
            return
        self.entry_add_song.clear()
        import danmaku
        danmaku.handle_message(self.app, "本地点歌 " + name, "主播(控制台)")


class AudioPage(BasePage):
    """音质与播放。"""

    def __init__(self, app, parent=None):
        super().__init__("audioPage", app, parent)
        cfg = state.style_config

        card, lay = self.add_card("点歌音质与音量", "没对应音源时自动降级")
        self.combo_quality_top = ComboBox(card)
        self.combo_quality_top.addItems(list(settings.QUALITY_UI_MAP.values()))
        self.combo_quality_top.setCurrentText(
            settings.QUALITY_UI_MAP.get(settings.normalize_quality_key(
                app.config.get("audio_quality", "flac")), "FLAC 无损品质"))
        self.combo_quality_top.currentTextChanged.connect(
            lambda v: app.update_audio_quality(value=v))
        _label_row(lay, "首选音质", self.combo_quality_top)

        self.scale_volume = Slider(Qt.Orientation.Horizontal, card)
        self.scale_volume.setRange(0, 100)
        self.scale_volume.setValue(int(round(app.get_volume() * 100)))
        self.scale_volume.setMinimumWidth(280)
        self.lbl_volume_pct = BodyLabel("%d%%" % self.scale_volume.value(), card)
        self.scale_volume.valueChanged.connect(
            lambda v: (app.apply_volume(slider_val=int(v)),
                       self.lbl_volume_pct.setText("%d%%" % int(v))))
        row = _row(lay)
        lb = BodyLabel("点歌音量", card)
        lb.setMinimumWidth(150)
        row.addWidget(lb)
        row.addWidget(self.scale_volume, 1)
        row.addWidget(self.lbl_volume_pct)

        self.combo_bgm_target = ComboBox(card)
        bg = {"auto": "自动识别", "qqmusic": "只暂停 QQ音乐", "off": "不暂停"}
        self.combo_bgm_target.addItems(list(bg.values()))
        self.combo_bgm_target.setCurrentText(
            bg.get(app.config.get("bgm_target") or "auto", "自动识别"))
        self.combo_bgm_target.currentTextChanged.connect(
            lambda v: app.update_bgm_target({v2: k for k, v2 in bg.items()}.get(v, "auto")))
        _label_row(lay, "点歌时暂停谁的 BGM", self.combo_bgm_target)

        card, lay = self.add_card("本地曲库", "观众发「本地点歌 歌名」只在这里找")
        btn = PushButton("📂 打开本地曲库文件夹", card)
        btn.clicked.connect(lambda: app.open_local_songs_folder())
        lay.addWidget(btn)
        lay.addWidget(CaptionLabel(
            "把录好的歌命名成歌名放进 my_songs；支持 mp3/wav/flac/ogg，别建子文件夹。", card))

        card, lay = self.add_card("QQ音乐客户端", "无损解码用")
        self.entry_qq_path = LineEdit(card)
        self.entry_qq_path.setText(app.config.get("qqmusic_path", "") or "")
        self.entry_qq_path.setMinimumWidth(340)
        self.entry_qq_path.textChanged.connect(
            lambda v: app.config.__setitem__("qqmusic_path", v.strip()))
        row = _row(lay)
        lb = BodyLabel("客户端路径", card)
        lb.setMinimumWidth(150)
        row.addWidget(lb)
        row.addWidget(self.entry_qq_path, 1)
        btn = PushButton("浏览", card)
        btn.clicked.connect(lambda: app.browse_qq_path())
        row.addWidget(btn)

        card, lay = self.add_card("缓存上限", "超出后按最旧优先删除")
        self.entry_max_files = LineEdit(card)
        self.entry_max_files.setText(str(cfg.get("max_cache_files", 100)))
        self.entry_max_files.setFixedWidth(110)
        _label_row(lay, "最多保留文件数", self.entry_max_files)
        self.entry_max_size = LineEdit(card)
        self.entry_max_size.setText(str(cfg.get("max_cache_size_mb", 500)))
        self.entry_max_size.setFixedWidth(110)
        _label_row(lay, "最多占用 (MB)", self.entry_max_size)
        btn = PushButton("保存上限", card)
        btn.clicked.connect(lambda: app.update_cache_settings())
        lay.addWidget(btn)
        self.finish()


class AccountPage(BasePage):
    """账号与弹幕：开播前在这里配好。"""

    def __init__(self, app, parent=None):
        super().__init__("accountPage", app, parent)
        import browserlogin

        card, lay = self.add_card("B站直播间", "弹幕来源；登录后自动连上")
        self.lbl_bili_status = BodyLabel("⏳ 检测中...", card)
        lay.addWidget(self.lbl_bili_status)
        self.entry_bili_room = LineEdit(card)
        self.entry_bili_room.setText(str(app.config.get("room_id", "") or ""))
        self.entry_bili_room.setFixedWidth(220)
        self.entry_bili_room.textChanged.connect(self._room_changed)
        _label_row(lay, "房间号", self.entry_bili_room)
        row = _row(lay)
        btn = PrimaryPushButton("登录 B站", card)
        btn.clicked.connect(lambda: browserlogin.bilibili_auto_login(app))
        row.addWidget(btn)
        btn = PushButton("重连弹幕", card)
        btn.clicked.connect(lambda: app.gui_restart_bili_listener())
        row.addWidget(btn)
        btn = PushButton("刷新状态", card)
        btn.clicked.connect(lambda: app.update_account_status())
        row.addWidget(btn)
        row.addStretch(1)

        card, lay = self.add_card("抖音直播间", "匿名监控，免登录；改完重启生效")
        self.entry_dy_room = LineEdit(card)
        self.entry_dy_room.setText(str(app.config.get("douyin_room_id", "") or ""))
        self.entry_dy_room.setFixedWidth(220)
        self.entry_dy_room.textChanged.connect(
            lambda v: (app.config.__setitem__("douyin_room_id", v.strip()),
                       app.schedule_save_style()))
        _label_row(lay, "房间号", self.entry_dy_room)

        card, lay = self.add_card("QQ音乐账号", "VIP 音质需要")
        self.lbl_qq_status = BodyLabel("⏳ 检测中...", card)
        lay.addWidget(self.lbl_qq_status)
        btn = PrimaryPushButton("扫码登录 QQ音乐", card)
        btn.clicked.connect(lambda: browserlogin.qq_scan_login(app))
        lay.addWidget(btn)

        card, lay = self.add_card("发弹幕", "用你的账号在直播间发言；登录后立即生效")
        self.lbl_dm_status = BodyLabel("⏳ 检测中...", card)
        lay.addWidget(self.lbl_dm_status)
        row = _row(lay)
        btn = PushButton("刷新发送器", card)
        btn.clicked.connect(lambda: app.reload_bili_sender())
        row.addWidget(btn)
        btn = PushButton("测试发送", card)
        btn.clicked.connect(lambda: app.test_send_danmaku())
        row.addWidget(btn)
        row.addStretch(1)

        self.sw_dm_enabled = SwitchButton(card)
        self.sw_dm_enabled.setChecked(bool(app.config.get("danmaku_send_enabled", True)))
        self.sw_dm_enabled.checkedChanged.connect(lambda _v: app.update_danmaku_settings())
        _label_row(lay, "启用发弹幕", self.sw_dm_enabled)

        self.entry_dm_per_min = LineEdit(card)
        self.entry_dm_per_min.setText(str(app.config.get("danmaku_sends_per_min", 3)))
        self.entry_dm_per_min.setFixedWidth(90)
        self.entry_dm_per_min.textChanged.connect(lambda _v: app.update_danmaku_settings())
        _label_row(lay, "每分钟上限", self.entry_dm_per_min)

        self.entry_dm_gap_sec = LineEdit(card)
        self.entry_dm_gap_sec.setText(str(app.config.get("danmaku_min_gap_sec", 3)))
        self.entry_dm_gap_sec.setFixedWidth(90)
        self.entry_dm_gap_sec.textChanged.connect(lambda _v: app.update_danmaku_settings())
        _label_row(lay, "最小间隔（秒）", self.entry_dm_gap_sec)

        row = _row(lay)
        self.entry_send_dm = LineEdit(card)
        self.entry_send_dm.setPlaceholderText("手动发一条弹幕（最多 40 字）")
        self.entry_send_dm.setMinimumWidth(320)
        row.addWidget(self.entry_send_dm, 1)
        btn = PrimaryPushButton("发送", card)
        btn.clicked.connect(lambda: app.gui_send_danmaku())
        row.addWidget(btn)
        self.lbl_send_dm_result = CaptionLabel("", card)
        lay.addWidget(self.lbl_send_dm_result)
        self.finish()

    def _room_changed(self, v):
        self.app.config["room_id"] = v.strip()
        self.app.schedule_save_style()


def _scroll_tab(parent, route):
    """子页签里的滚动页：透明底，交给 Fluent 画背景。"""
    sc = ScrollArea(parent)
    sc.setObjectName(route)
    sc.setWidgetResizable(True)
    sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
    host = QWidget()
    host.setStyleSheet("background:transparent;")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(14)
    sc.setWidget(host)
    return sc, host, lay


# ════════════════ R-19 字体选择器 ════════════════

def _qt_font_families():
    """本机已装字体（小写集合）；拿不到就返回空集 = 判断不了。"""
    try:
        from PySide6.QtGui import QFontDatabase
        return {str(f).lower() for f in QFontDatabase.families()}
    except Exception:
        return set()


class _FontPicker(QWidget):
    """字体选择器（照旧版 make_font_picker）：内置字体下拉 + 「自定义字体…」现输。

    选完直接回调 on_change(CSS font-family 值)，和旧版写进配置的字符串一致。
    """

    def __init__(self, current_css, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._css = str(current_css or "")
        self._loading = True
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.combo = ComboBox(self)
        self.combo.addItems(fontlib.display_list())
        self.combo.setMinimumWidth(220)
        lay.addWidget(self.combo)
        self.hint = CaptionLabel("", self)
        lay.addWidget(self.hint, 1)
        self._show_label(self._css)
        self._loading = False
        self.combo.currentTextChanged.connect(self._picked)

    # ── 显示 ──
    def _show_label(self, css):
        label = fontlib.label_for_css(css)
        items = [self.combo.itemText(i) for i in range(self.combo.count())]
        if label not in items:                  # 自定义字体：先加进下拉框再选中
            self.combo.addItem(label)
        self.combo.setCurrentText(label)

    def _restore_label(self):
        self._loading = True
        try:
            self._show_label(self._css)
        finally:
            self._loading = False

    # ── 选择 ──
    def _picked(self, text):
        if self._loading:
            return
        if str(text).startswith(fontlib.CUSTOM_LABEL[:-1]):
            self._ask_custom()
            return
        for css_fam, disp, _aliases in fontlib.CURATED_FONTS:
            if disp == text:
                self._apply(fontlib.to_css(css_fam), "")
                return

    def _ask_custom(self):
        cur = fontlib.from_css(self._css)
        dlg = Dialog("自定义字体",
                     "输入字体名（中英文都行，例如：站酷快乐体 / Source Han Sans）。\n"
                     "字体必须装在「放 OBS 的那台电脑」上才会生效。",
                     self.window())
        edit = LineEdit(dlg)
        edit.setText("" if cur == "Microsoft YaHei" else cur)
        try:
            edit.setPlaceholderText("字体名")
            dlg.textLayout.addWidget(edit, 0)
        except Exception:
            pass
        if not dlg.exec():
            self._restore_label()
            return
        css, tip = fontlib.parse_custom(edit.text())
        if not css:
            self.hint.setText(tip)
            self._restore_label()
            return
        fam = fontlib.from_css(css)
        if not tip and not fontlib.is_available(fam, avail=_qt_font_families()):
            tip = "本机没找到「%s」，会回落到默认字体" % fam
        self._apply(css, tip)

    def _apply(self, css, tip):
        self._css = css
        try:
            self._on_change(css)
        except Exception:
            pass
        try:
            self.hint.setText(tip or "")
        except Exception:
            pass
        self._restore_label()


class OverlayPage(QWidget):
    """OBS 挂件：四种地址 + 四种挂件的样式，用子页签分开。"""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setObjectName("overlayPage")
        self.app = app
        cfg = state.style_config
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 20)
        root.setSpacing(12)

        # R-21：地址区压成一行（原来 4 个地址各占一条大行，把下面的样式设置挤得没地方）。
        # 地址平时用不着看，主要动作是「复制」：按钮上直接写挂件名，鼠标悬停显示完整地址。
        card, lay = _card(self, "挂件地址", "点按钮复制地址，粘到 OBS 的「浏览器」源里")
        row = _row(lay)
        for text, path in (("综合挂件", ""), ("纯歌词", "/lyric"),
                           ("正在播放", "/playing"), ("点歌列表", "/queue")):
            url = "http://127.0.0.1:%d%s" % (state.overlay_port, path)
            btn = PushButton(text, card)
            btn.setToolTip("复制 " + url)
            btn.clicked.connect(lambda _c=False, u=url: app.copy_to_clipboard(u))
            row.addWidget(btn)
        row.addStretch(1)
        lay.addWidget(CaptionLabel(
            "端口 %d（被占用会自动顺延）" % state.overlay_port, card))
        root.addWidget(card)

        self.tabs = TabWidget(self)
        try:
            self.tabs.setCloseButtonDisplayMode(TabCloseButtonDisplayMode.NEVER)
        except Exception:
            pass
        for att in ("setAddButtonVisible",):
            try:
                getattr(self.tabs, att)(False)
            except Exception:
                pass
        root.addWidget(self.tabs, 1)

        self._build_mix(cfg["mixed"])
        self._build_lyric(cfg["lyric"])
        self._build_playing(cfg["playing"])
        self._build_queue(cfg["queue"])

    # ── 小控件工厂 ──
    def _sw(self, lay, title, key, sect, val):
        s = SwitchButton()
        try:
            s.setText("")          # 别在开关旁边多一个 Off/On
        except Exception:
            pass
        s.setChecked(bool(val))
        s.checkedChanged.connect(lambda v, k=key: getattr(self.app, "update_" + sect)(k, v))
        _label_row(lay, title, s)
        return s

    def _cb(self, lay, title, items, mapping, val, on_change):
        cb = ComboBox()
        cb.addItems(items)
        rev = {v: k for k, v in mapping.items()}
        cb.setCurrentText(rev.get(val, items[0]))
        cb.currentTextChanged.connect(lambda t: on_change(mapping.get(t, val)))
        _label_row(lay, title, cb)
        return cb

    def _sld(self, lay, title, lo, hi, val, on_change):
        s = Slider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(int(val))
        s.setMinimumWidth(260)
        s.valueChanged.connect(lambda v: on_change(int(v)))
        lb = BodyLabel(str(int(val)))
        s.valueChanged.connect(lambda v: lb.setText(str(int(v))))
        row = _row(lay)
        t = BodyLabel(title)
        t.setMinimumWidth(150)
        row.addWidget(t)
        row.addWidget(s, 1)
        row.addWidget(lb)
        return s

    def _num(self, lay, title, lo, hi, val, on_change):
        sp = SpinBox()
        sp.setRange(lo, hi)
        sp.setValue(int(val))
        sp.setFixedWidth(150)
        # 库的 SpinBox 有个坑：里面那个输入框会被挤成 1px，数字看不见（只剩箭头）。
        # 补一个最小宽度，数字才显示出来。
        try:
            sp.lineEdit().setMinimumWidth(60)
        except Exception:
            pass
        sp.valueChanged.connect(lambda v: on_change(int(v)))
        _label_row(lay, title, sp)
        return sp

    def _txt(self, lay, title, val, on_change):
        e = LineEdit()
        e.setText(str(val))
        e.setMinimumWidth(220)
        e.textChanged.connect(on_change)
        _label_row(lay, title, e)
        return e

    def _font(self, lay, title, current_css, on_change):
        """字体一行：说明 + 字体下拉（含自定义）。"""
        row = _row(lay)
        t = BodyLabel(title)
        t.setMinimumWidth(150)
        row.addWidget(t)
        row.addWidget(_FontPicker(current_css, on_change), 1)
        return row

    def _color(self, lay, title, val, on_pick, attr_prefix):
        row = _row(lay)
        t = BodyLabel(title)
        t.setMinimumWidth(150)
        row.addWidget(t)
        lbl = QLabel(str(val))
        ad = qtshim.LabelAdapter(lbl)
        ad.configure(text=str(val), text_color=str(val))
        setattr(self.app, attr_prefix, ad)
        row.addWidget(ad.w)
        btn = PushButton("换颜色")
        btn.clicked.connect(on_pick)
        row.addWidget(btn)
        row.addStretch(1)

    # ── 四个子页签 ──
    def _build_mix(self, mx):
        tab, host, lay = _scroll_tab(self.tabs, "mixTab")
        self.tabs.addTab(tab, "综合挂件")
        card, cl = _card(host, "显示内容", "综合挂件里显示哪几块")
        lay.addWidget(card)
        for t, k in (("正在播放", "show_playing"), ("实时歌词", "show_lyric"), ("点歌列表", "show_queue")):
            self._sw(cl, t, k, "mixed", mx.get(k, True))
        card, cl = _card(host, "歌词", "默认两行：当前行 + 下一行")
        lay.addWidget(card)
        self._cb(cl, "滚动效果", ["无滚动 (静态)", "高清平滑滚动", "苹果景深滚动"],
                 {"无滚动 (静态)": "static", "高清平滑滚动": "apple_hd", "苹果景深滚动": "apple_blur"},
                 mx.get("effect_lyric", "static"),
                 lambda v: self.app.update_mixed("effect_lyric", v))
        self._cb(cl, "对齐", ["左", "居中", "右"], {"左": "left", "居中": "center", "右": "right"},
                 mx.get("align", "left"), lambda v: self.app.update_mixed("align", v))
        self._num(cl, "上方已播行数", 0, 6, mx.get("lines_prev", 0),
                  lambda v: self.app.update_mixed("lines_prev", v))
        self._num(cl, "下方未播行数", 0, 6, mx.get("lines_next", 1),
                  lambda v: self.app.update_mixed("lines_next", v))
        self._sld(cl, "歌词字号", 10, 80, mx.get("size_lyric", 28),
                  lambda v: self.app.update_mixed("size_lyric", v))
        self._color(cl, "歌词颜色", mx.get("color_lyric", "#FFE600"),
                    lambda: self.app.pick_mixed("color_lyric", "lbl_mix_color_lyric"),
                    "lbl_mix_color_lyric")
        self._sw(cl, "歌词加粗", "bold_lyric", "mixed", mx.get("bold_lyric", False))
        self._font(cl, "字体", mx.get("font_lyric", "'Microsoft YaHei', sans-serif"),
                   lambda css: self.app.update_mixed("font_lyric", css))
        card, cl = _card(host, "正在播放", "可分别隐藏图标与文字")
        lay.addWidget(card)
        self._sld(cl, "字号", 10, 80, mx.get("size_playing", 32),
                  lambda v: self.app.update_mixed("size_playing", v))
        self._color(cl, "颜色", mx.get("color_playing", "#00FFFF"),
                    lambda: self.app.pick_mixed("color_playing", "lbl_mix_color_playing"),
                    "lbl_mix_color_playing")
        self._sw(cl, "显示图标", "show_icon", "mixed", mx.get("show_icon", True))
        self._sw(cl, "显示文字前缀", "show_prefix", "mixed", mx.get("show_prefix", True))
        self._sw(cl, "加粗", "bold_playing", "mixed", mx.get("bold_playing", False))
        self._font(cl, "字体", mx.get("font_playing", "'Microsoft YaHei', sans-serif"),
                   lambda css: self.app.update_mixed("font_playing", css))
        card, cl = _card(host, "点歌列表")
        lay.addWidget(card)
        self._sld(cl, "字号", 10, 80, mx.get("size_queue", 36),
                  lambda v: self.app.update_mixed("size_queue", v))
        self._color(cl, "颜色", mx.get("color_queue", "#FFFFFF"),
                    lambda: self.app.pick_mixed("color_queue", "lbl_mix_color_queue"),
                    "lbl_mix_color_queue")
        self._num(cl, "最多显示条数（0=不限）", 0, 50, mx.get("max_items", 0),
                  lambda v: self.app.update_mixed("max_items", v))
        self._num(cl, "单行最长字数（0=不限）", 0, 200, mx.get("max_chars", 0),
                  lambda v: self.app.update_mixed("max_chars", v))
        self._sw(cl, "显示序号", "show_index", "mixed", mx.get("show_index", True))
        self._sw(cl, "显示请求者", "show_requester", "mixed", mx.get("show_requester", True))
        self._sw(cl, "加粗", "bold_queue", "mixed", mx.get("bold_queue", False))
        self._txt(cl, "请求者分隔符", mx.get("requester_sep", "-"),
                  lambda v: self.app.update_mixed("requester_sep", v or "-"))
        self._font(cl, "字体", mx.get("font_queue", "'Microsoft YaHei', sans-serif"),
                   lambda css: self.app.update_mixed("font_queue", css))
        lay.addStretch(1)

    def _build_lyric(self, ly):
        tab, host, lay = _scroll_tab(self.tabs, "lyricTab")
        self.tabs.addTab(tab, "纯歌词")
        card, cl = _card(host, "字体与颜色")
        lay.addWidget(card)
        self._font(cl, "字体", ly.get("font", "'Microsoft YaHei', sans-serif"),
                   lambda css: self.app.update_lyric("font", css))
        self._sld(cl, "字号", 10, 100, ly.get("size", 28),
                  lambda v: self.app.update_lyric("size", v))
        self._sld(cl, "透明度系数（100=原样）", 20, 200, int(float(ly.get("opacity", 1.0)) * 100),
                  lambda v: self.app.update_lyric("opacity", v / 100.0))
        self._sld(cl, "行间距（%）", 100, 200, ly.get("line_spacing", 142),
                  lambda v: self.app.update_lyric("line_spacing", v))
        self._color(cl, "歌词颜色", ly.get("color", "#FFE600"),
                    lambda: self.app.pick_lyric("color"), "lbl_lyric_color")
        self._sw(cl, "字体加粗", "is_bold", "lyric", ly.get("is_bold", False))
        card, cl = _card(host, "排版与滚动")
        lay.addWidget(card)
        self._cb(cl, "对齐", ["居中对齐", "左对齐", "右对齐"],
                 {"居中对齐": "center", "左对齐": "left", "右对齐": "right"},
                 ly.get("align", "center"),
                 lambda v: (setattr(self.app, "combo_lyric_align", _FakeCombo(
                     {"center": "居中对齐", "left": "左对齐", "right": "右对齐"}.get(v, "居中对齐"))),
                     self.app.update_lyric_align(None)))
        self._cb(cl, "滚动效果", ["无滚动 (静态)", "高清平滑滚动", "苹果景深滚动"],
                 {"无滚动 (静态)": "static", "高清平滑滚动": "apple_hd", "苹果景深滚动": "apple_blur"},
                 ly.get("effect", "apple_hd"),
                 lambda v: (setattr(self.app, "combo_effect", _FakeCombo(
                     {"static": "无滚动 (静态)", "apple_hd": "高清平滑滚动",
                      "apple_blur": "苹果景深滚动"}.get(v, "高清平滑滚动"))),
                     self.app.update_effect(None)))
        self._num(cl, "上方已播行数", 0, 6, ly.get("lines_prev", 2),
                  lambda v: self.app.update_lyric("lines_prev", v))
        self._num(cl, "下方未播行数", 0, 6, ly.get("lines_next", 2),
                  lambda v: self.app.update_lyric("lines_next", v))
        self._txt(cl, "纯音乐提示", ly.get("pure_text", "纯音乐, 请欣赏.."),
                  lambda v: self.app.update_lyric("pure_text", v))
        lay.addStretch(1)

    def _build_playing(self, pl):
        tab, host, lay = _scroll_tab(self.tabs, "playingTab")
        self.tabs.addTab(tab, "正在播放")
        card, cl = _card(host, "样式")
        lay.addWidget(card)
        self._font(cl, "字体", pl.get("font", "'Microsoft YaHei', sans-serif"),
                   lambda css: self.app.update_playing("font", css))
        self._sld(cl, "字号", 10, 100, pl.get("size", 32),
                  lambda v: self.app.update_playing("size", v))
        self._color(cl, "颜色", pl.get("color", "#00FFFF"),
                    lambda: self.app.pick_playing("color"), "lbl_playing_color")
        self._sw(cl, "显示文字前缀", "show_prefix", "playing", pl.get("show_prefix", True))
        self._sw(cl, "加粗", "is_bold", "playing", pl.get("is_bold", False))
        lay.addStretch(1)

    def _build_queue(self, q):
        tab, host, lay = _scroll_tab(self.tabs, "queueTab")
        self.tabs.addTab(tab, "点歌列表")
        card, cl = _card(host, "样式")
        lay.addWidget(card)
        self._font(cl, "字体", q.get("font", "'Microsoft YaHei', sans-serif"),
                   lambda css: self.app.update_queue("font", css))
        self._sld(cl, "字号", 10, 100, q.get("size", 36),
                  lambda v: self.app.update_queue("size", v))
        self._color(cl, "颜色", q.get("color", "#FFFFFF"),
                    lambda: self.app.pick_queue("color"), "lbl_queue_color")
        self._num(cl, "最多显示条数（0=不限）", 0, 50, q.get("max_items", 0),
                  lambda v: self.app.update_queue("max_items", v))
        self._num(cl, "单行最长字数", 0, 200, q.get("max_chars", 30),
                  lambda v: self.app.update_queue("max_chars", v))
        self._sw(cl, "显示序号", "show_index", "queue", q.get("show_index", True))
        self._sw(cl, "显示请求者", "show_requester", "queue", q.get("show_requester", True))
        self._sw(cl, "加粗", "is_bold", "queue", q.get("is_bold", False))
        self._txt(cl, "请求者分隔符", q.get("requester_sep", "-"),
                  lambda v: self.app.update_queue("requester_sep", v or "-"))
        card, cl = _card(host, "内容")
        lay.addWidget(card)
        self._cb(cl, "对齐", ["居中对齐", "左对齐", "右对齐"],
                 {"居中对齐": "center", "左对齐": "left", "右对齐": "right"},
                 q.get("align", "left"),
                 lambda v: (setattr(self.app, "combo_queue_align", _FakeCombo(
                     {"center": "居中对齐", "left": "左对齐", "right": "右对齐"}.get(v, "左对齐"))),
                     self.app.update_queue_align(None)))
        lay.addStretch(1)


class _FakeCombo:
    """给老方法的 .get() 用（对齐/效果这两个方法只从控件里读一个字符串）。"""

    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class LogPage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setObjectName("logPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 20)
        root.setSpacing(10)
        card, lay = _card(self, "运行日志", "出问题时把这页的内容发出来")
        self.text = PlainTextEdit(card)
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(420)
        lay.addWidget(self.text)
        row = _row(lay)
        self.lbl_engine_status = BodyLabel("⏳ 正在检测音频驱动...", card)
        row.addWidget(self.lbl_engine_status, 1)
        btn = PushButton("清空", card)
        btn.clicked.connect(lambda: self.text.clear())
        row.addWidget(btn)
        # 旧版底部状态栏那条「OBS 源」也补回来（端口可能被占用后顺延，所以现读 state）
        self.lbl_obs_src = CaptionLabel("OBS 源：http://127.0.0.1:%d" % state.overlay_port, card)
        lay.addWidget(self.lbl_obs_src)
        root.addWidget(card, 1)

        # R-27：关闭行为（点标题栏 X 时做什么）。
        # 放在运行日志页而不是「关于」：关于是个弹窗，设置项塞弹窗里不好找。
        try:
            c2, l2 = _card(self, "关闭行为", "点窗口右上角 X 的时候做什么")
            self.combo_close = ComboBox(c2)
            self.combo_close.addItems(["缩小到托盘（后台继续运行）", "直接退出程序"])
            _label_row(l2, "点 X 时", self.combo_close)
            cur_action = str((app.config or {}).get("close_action") or "tray").lower()
            self.combo_close.setCurrentText(
                "直接退出程序" if cur_action == "quit" else "缩小到托盘（后台继续运行）")

            def _on_close_change(text):
                val = "quit" if text.startswith("直接退出") else "tray"
                try:
                    app.config["close_action"] = val
                    app.schedule_save_style()      # 走现有落盘链路
                except Exception:
                    pass
                try:
                    app.log("⚙️ 关闭行为已改为：%s" % (
                        "直接退出" if val == "quit" else "缩小到托盘"))
                except Exception:
                    pass

            self.combo_close.currentTextChanged.connect(_on_close_change)
            root.addWidget(c2)
        except Exception:
            self.combo_close = None

        self.log_adapter = LogAdapter(self.text)


# ════════════════ 组装 ════════════════

def build(app, root):
    """把界面建出来并回填 mainapp 依赖的属性（与旧 ui_ctk.build 同签名）。"""
    cfg = state.style_config

    live = LivePage(app)
    audio = AudioPage(app)
    account = AccountPage(app)
    overlay = OverlayPage(app)
    logp = LogPage(app)

    root.addSubInterface(live, _icon("HOME"), "直播台")
    root.addSubInterface(audio, _icon("MUSIC", _icon("SPEAKERS")), "音质与播放")
    root.addSubInterface(account, _icon("PEOPLE"), "账号与弹幕")
    root.addSubInterface(overlay, _icon("TV", _icon("GLOBE")), "OBS 挂件")
    root.addSubInterface(logp, _icon("DOCUMENT"), "运行日志")
    try:
        root.navigationInterface.addItem(
            routeKey="aboutItem", icon=_icon("INFO", _icon("SETTING")), text="关于",
            onClick=root.show_about, selectable=False,
            position=NavigationItemPosition.BOTTOM)
    except Exception:
        pass

    # ── mainapp 依赖的属性（名字沿用旧版契约）──
    app.pages = {"live": live, "audio": audio, "account": account,
                 "overlay": overlay, "log": logp}
    app.log_text = logp.log_adapter

    app.btn_pause = live.btn_pause
    app.lbl_qm_summary = live.lbl_qm_summary
    app.qm_pending_box = live.qm_pending_box
    app.qm_ready_box = live.qm_ready_box
    app.qm_pending_layout = live.qm_pending_layout
    app.qm_ready_layout = live.qm_ready_layout
    app.lbl_now_playing = live.lbl_now

    app.combo_quality_top = qtshim.ComboAdapter(audio.combo_quality_top)
    app.scale_volume = qtshim.SliderAdapter(audio.scale_volume)
    app.lbl_volume_pct = qtshim.LabelAdapter(audio.lbl_volume_pct)
    app.entry_qq_path = qtshim.EntryAdapter(audio.entry_qq_path)
    app.combo_bgm_target = qtshim.ComboAdapter(audio.combo_bgm_target)
    app.entry_max_files = qtshim.EntryAdapter(audio.entry_max_files)
    app.entry_max_size = qtshim.EntryAdapter(audio.entry_max_size)
    app.var_audio_quality = _FakeCombo(audio.combo_quality_top.currentText())

    app.lbl_bili_status = qtshim.LabelAdapter(account.lbl_bili_status)
    app.entry_bili_room = qtshim.EntryAdapter(account.entry_bili_room)
    app.entry_dy_room = qtshim.EntryAdapter(account.entry_dy_room)
    app.lbl_qq_status = qtshim.LabelAdapter(account.lbl_qq_status)
    app.lbl_dm_status = qtshim.LabelAdapter(account.lbl_dm_status)
    app.sw_dm_enabled = qtshim.SwitchAdapter(account.sw_dm_enabled)
    app.entry_dm_per_min = qtshim.EntryAdapter(account.entry_dm_per_min)
    app.entry_dm_gap_sec = qtshim.EntryAdapter(account.entry_dm_gap_sec)
    app.entry_send_dm = qtshim.EntryAdapter(account.entry_send_dm)
    app.lbl_send_dm_result = qtshim.LabelAdapter(account.lbl_send_dm_result)

    app.lbl_engine_status = qtshim.LabelAdapter(logp.lbl_engine_status)

    # 版本/更新：侧栏底部「关于」里有；顶栏再放一个下载按钮，方便一眼看到
    app.btn_check_update = None
    app.btn_update_link = None
    app._qm_built = False
    root.music_app = app

    # R-16：按上次保存的偏好还原主题（没存过就跟随系统）
    try:
        apply_theme((app.config or {}).get("ui_theme") or "auto")
        root.update_theme_button()
    except Exception:
        pass
    # R-18：按上次保存的档位缩放字号（没存过就是「标准」）
    try:
        apply_ui_scale(root, (app.config or {}).get("ui_scale") or "normal")
        root.update_scale_button()
    except Exception:
        pass

    root.title("点歌台控制台 · 房间 %s · %s"
               % (app.config.get("room_id") or "未配置", version.DISPLAY))

    updater.register_update_link(app)
    logp.log_adapter.insert(None, "点歌台 %s 已启动（PySide6 界面）" % version.DISPLAY)
    return root


def set_label(widget, text=None, color=None, bg=None):
    """旧 ui_ctk.set_label 的替身：支持适配器或裸 Qt 控件。"""
    if widget is None:
        return
    w = getattr(widget, "w", widget)
    try:
        if text is not None:
            if hasattr(w, "setText"):
                w.setText(str(text))
            elif hasattr(widget, "configure"):
                widget.configure(text=text)
        if color:
            css = "color:%s;" % color
            if bg:
                css += "background:%s;" % bg
            w.setStyleSheet(css)
    except Exception:
        pass


def render_queue(app):
    """重画队列两段（mainapp.refresh_queue_mgmt 调这里）。"""
    from PySide6.QtWidgets import QLabel as _QL
    try:
        boxes = ((app.qm_pending_layout, app.douyin_status if False else None))
    except Exception:
        pass
    layouts = (getattr(app, "qm_pending_layout", None), getattr(app, "qm_ready_layout", None))
    for lay in layouts:
        if lay is not None:
            qtshim.clear_layout(lay)

    def row_widget(text, color=None, buttons=()):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        lb = BodyLabel(text)
        if color:
            lb.setStyleSheet("color:%s;" % color)
        h.addWidget(lb, 1)
        for text_b, cb in buttons:
            b = PushButton(text_b)
            b.setFixedWidth(64)
            b.clicked.connect(cb)
            h.addWidget(b)
        apply_ui_scale(w, current_ui_scale_key())   # R-18：新造的行也要跟当前档位
        return w

    pl = getattr(app, "qm_pending_layout", None)
    rl = getattr(app, "qm_ready_layout", None)
    proc = state.processing_request
    try:
        if pl is not None:
            if proc:
                pl.addWidget(row_widget("⬇ 正在下载：《%s》 - %s"
                                        % (proc.get("song_name", ""), proc.get("uname", "")),
                                        "#9A6700"))
            pend = list(state.pending_requests)
            for i, r in enumerate(pend):
                k = i
                pl.addWidget(row_widget("#%d 《%s》 - %s"
                                        % (i + 1, r.get("song_name", ""), r.get("uname", "")),
                                        None, (("删除", lambda _c=False, k=k: app.qm_remove_pending(k)),)))
            if not proc and not pend:
                pl.addWidget(BodyLabel("（空）"))
        if rl is not None:
            ready = list(state.playlist)
            for i, r in enumerate(ready):
                k = i
                btns = []
                if i > 0:
                    btns.append(("置顶", lambda _c=False, k=k: app.qm_move_top(k)))
                btns.append(("删除", lambda _c=False, k=k: app.qm_remove_ready(k)))
                lead = "▶ " if i == 0 else "#%d " % (i + 1)
                rl.addWidget(row_widget("%s《%s》 - %s"
                                        % (lead, r.get("display_name", ""), r.get("requester", "")),
                                        "#0F7B0F" if i == 0 else None, btns))
            if not ready:
                rl.addWidget(BodyLabel("（空）"))
    except Exception:
        traceback.print_exc()


def _center_window(win):
    """R-26 问题3：把窗口摆到当前屏幕正中。

    放在 show() 之前调用：show() 之后 Qt 会按它自己的策略摆一次，再居中会闪。
    多显示器取"鼠标所在屏幕"，找不到就退回主屏。
    """
    try:
        from PySide6.QtGui import QCursor
        scr = None
        try:
            scr = QApplication.screenAt(QCursor.pos())
        except Exception:
            scr = None
        if scr is None:
            scr = QApplication.primaryScreen()
        if scr is None:
            return
        area = scr.availableGeometry()
        g = win.frameGeometry()
        g.moveCenter(area.center())
        win.move(g.topLeft())
    except Exception:
        traceback.print_exc()


def run(config, factory):
    """启动 Qt 版主程序（main.py 调这里）。"""
    qapp = make_app()
    win = MainWindow()
    music_app = factory(win)       # MusicApp(win, config) 里会调 build(win)
    _center_window(win)
    win.show()
    try:
        win.navigationInterface.setMinimumExpandWidth(600)
        win.navigationInterface.setExpandWidth(210)
        win.navigationInterface.expand(useAni=False)
    except Exception:
        pass
    win.raise_()
    win.activateWindow()
    return qapp.exec()


