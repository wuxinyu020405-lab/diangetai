# -*- coding: utf-8 -*-
"""桌面歌词（独立原型 v0）—— 不依赖点歌台代码，只读它的 OBS 数据接口。

设计（按用户要求：先独立做好，不集成）：
  · 数据源：http://127.0.0.1:<port>/api/data （点歌台 OBS 服务，端口自动探测 8080~8090）
  · 渲染：无边框置顶窗 + 色键透明（黑底被抠成透明）+ 鼠标穿透可切换
  · 操作：拖拽移动 | 滚轮调字号 | C 切换鼠标穿透 | S 开关设置条 | Esc 退出
  · 配置：与本脚本同目录 desktop_lyric.json（不存在则用默认，改设置条即自动保存）

与点歌台的耦合方式 = 仅 HTTP 读，点歌台不运行/未启动 OBS 服务时显示占位文案，
互不干扰。满意后再谈集成（内嵌为子进程/合并进 GUI 均可）。

用法:  python desktop_lyric.py [--port 8080]
"""
import argparse
import json
import os
import sys
import threading
import time
import tkinter as tk
import urllib.request

CONF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop_lyric.json")
DEFAULTS = {
    "x": 60, "y": 980,            # 初始位置（屏幕底部，QQ 音乐桌面歌词习惯位）
    "font": "Microsoft YaHei UI",
    "size": 42,                   # 当前行字号
    "next_ratio": 0.62,           # 下一行相对当前行的字号比例
    "color_active": "#00FFD0",
    "color_next": "#E8E8E8",
    "stroke": 3,                  # 描边像素（暗背景直播画面上保可读）
    "opacity": 0.92,              # 整窗不透明度（色键已抠黑，这里管整体淡出感）
    "click_through": False,
    "show_next": True,
    "port": 0,                    # 0=自动探测
}
KEY_COLOR = "#010101"             # 色键（近纯黑；歌词配色避开它即可）
HOTKEY_ID = 1                     # RegisterHotKey 的 id（本进程内唯一）
_MOD = 0x0002 | 0x0001            # MOD_CONTROL | MOD_ALT
_MODS = 0x0002 | 0x0001 | 0x0004  # + MOD_SHIFT
# 候选组合（依次尝试，第一个注册成功即用——某些软件会占用常见组合，
# 如本机 Ctrl+Alt+L 被占；从根上保证"总有可用热键 → 穿透永不锁死"）
HOTKEY_CANDIDATES = [
    (_MOD,  0x4C, "Ctrl+Alt+L"),
    (_MOD,  0x44, "Ctrl+Alt+D"),
    (_MODS, 0x4C, "Ctrl+Alt+Shift+L"),
    (_MOD,  0x7B, "Ctrl+Alt+F12"),
    (_MODS, 0x7B, "Ctrl+Alt+Shift+F12"),
]


class _HotkeyThread(threading.Thread):
    """系统级全局热键线程：穿透态下窗口收不到任何键鼠，靠全局热键恢复。
    核心不变量：注册失败 = 拒绝进入穿透态（从根上杜绝锁死）。

    关键实现点：RegisterHotKey 第一参传 None → 热键消息投递到**本线程**队列
    （若传 Tk 的 HWND，消息会进 Tk 主线程队列，本线程 PeekMessage 永远取不到）。
    同理 PeekMessage 的 hwnd 也传 None=收本线程所有消息。"""

    def __init__(self, on_fire):
        super().__init__(daemon=True)
        self.on_fire = on_fire
        self._stop = threading.Event()
        self._registered = False
        self._label = ""

    def run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        WM_HOTKEY = 0x0312
        try:
            # 关键顺序：RegisterHotKey(NULL) 要求调用线程**已有消息队列**，
            # 而队列是第一次 PeekMessage/GetMessage 时才隐式创建的。
            # 先 PM_NOREMOVE(2) 取一次空消息把队列建起来，再注册热键。
            dummy = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(dummy), None, 0, 0, 2)  # PM_NOREMOVE
            # 依次尝试候选组合，第一个成功即用（常见组合可能被别的软件占用）
            chosen = None
            for mod, vk, label in HOTKEY_CANDIDATES:
                if user32.RegisterHotKey(None, HOTKEY_ID, mod, vk):
                    chosen = label
                    break
            if chosen is None:
                return
            self._label = chosen
            self._registered = True
            msg = wintypes.MSG()
            while not self._stop.is_set():
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                        try:
                            self.on_fire()
                        except Exception:
                            pass
                time.sleep(0.05)
        except Exception:
            self._registered = False
        finally:
            try:
                if self._registered:
                    user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass

    def stop(self):
        self._stop.set()

    @property
    def registered(self):
        """热键是否注册成功（线程启动后数毫秒内确定）。"""
        return self._registered

    @property
    def label(self):
        """实际生效的热键组合名（UI 提示用）。"""
        return self._label


def load_conf():
    cfg = dict(DEFAULTS)
    try:
        with open(CONF_PATH, encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    except Exception:
        pass
    return cfg


def save_conf(cfg):
    try:
        with open(CONF_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[WARN] 配置保存失败:", e)


def probe_port(preferred=0):
    """探测点歌台 OBS 服务端口：优先指定口，否则扫 8080~8090。"""
    ports = ([preferred] if preferred else []) + list(range(8080, 8091))
    for p in ports:
        if not p:
            continue
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/api/data" % p,
                                         headers={"User-Agent": "desktop-lyric"})
            with urllib.request.urlopen(req, timeout=0.4) as r:
                d = json.loads(r.read().decode("utf-8"))
            if isinstance(d, dict) and "lyric" in d:
                return p
        except Exception:
            continue
    return None


def fetch_state(port):
    """返回 (当前行, 下一行, 歌名) 或 None（服务不可用）。"""
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/api/data" % port,
                                     headers={"User-Agent": "desktop-lyric"})
        with urllib.request.urlopen(req, timeout=1.2) as r:
            d = json.loads(r.read().decode("utf-8"))
        lyric = d.get("lyric") or {}
        lines = lyric.get("lines") or []
        cur = nxt = ""
        act_i = -1
        for i, l in enumerate(lines):
            if l.get("active"):
                act_i = i
                break
        if act_i >= 0:
            cur = lines[act_i].get("text", "")
            # 下一行 = active 之后的第一行（此前 bug：误取了窗口里 active 之前的行）
            for l in lines[act_i + 1:]:
                t = l.get("text", "")
                if t:
                    nxt = t
                    break
        elif lines:
            cur = lines[-1].get("text", "")
        song = d.get("system_playing") or ""
        return cur, nxt, song
    except Exception:
        return None


class DesktopLyric:
    def __init__(self, root, cfg, port):
        self.root = root
        self.cfg = cfg
        self.port = port
        root.overrideredirect(True)                       # 无边框
        try:
            root.attributes("-topmost", True)
            root.attributes("-transparentcolor", KEY_COLOR)  # 色键抠底（Windows）
        except tk.TclError:
            pass                                          # 非 Windows 退化为不透明
        root.configure(bg=KEY_COLOR)
        root.attributes("-alpha", max(0.3, min(1.0, cfg["opacity"])))
        root.geometry("%dx%d+%d+%d" % (1280, 190, cfg["x"], cfg["y"]))
        try:
            root.attributes("-toolwindow", True)          # 不进任务栏/Alt-Tab
        except tk.TclError:
            pass

        self.song_lbl = tk.Label(root, text="", bg=KEY_COLOR, fg="#9AA5B1",
                                 font=(cfg["font"], 14))
        self.song_lbl.pack(anchor="w", padx=14)
        self.cur_lbl = tk.Label(root, text="连接中…", bg=KEY_COLOR,
                                 fg=cfg["color_active"], font=self._font(True))
        self.cur_lbl.pack(anchor="w", padx=14)
        self.next_lbl = tk.Label(root, text="", bg=KEY_COLOR,
                                 fg=cfg["color_next"], font=self._font(False))
        self.next_lbl.pack(anchor="w", padx=14)

        # 设置条（S 开关）：字号/透明度实时调，穿透开关
        self.bar = tk.Frame(root, bg="#22262E")
        self._build_bar()

        # 交互
        self.cur_lbl.bind("<Button-1>", self._drag_start)
        self.song_lbl.bind("<Button-1>", self._drag_start)
        root.bind("<MouseWheel>", self._wheel)
        root.bind("c", lambda e: self.toggle_click_through())
        root.bind("s", self._toggle_bar)
        root.bind("<Escape>", lambda e: root.destroy())
        self._dx = self._dy = 0

        # 全局热键 Ctrl+Alt+L：穿透态下窗口收不到任何键鼠，这是唯一不依赖本窗口的退路
        self._hotkey_fired = False
        self._hk = _HotkeyThread(on_fire=lambda: setattr(self, "_hotkey_fired", True))
        self._hk.start()

        self._apply_click_through()

        self._tick()

    # ---------- 渲染 ----------
    def _font(self, active):
        size = self.cfg["size"] if active else max(12, int(self.cfg["size"] * self.cfg["next_ratio"]))
        return (self.cfg["font"], size, "bold" if active else "normal")

    def _restyle(self):
        for lbl, act in ((self.cur_lbl, True), (self.next_lbl, False)):
            lbl.configure(font=self._font(act),
                          fg=self.cfg["color_active"] if act else self.cfg["color_next"])
        self.root.attributes("-alpha", max(0.3, min(1.0, self.cfg["opacity"])))
        self.next_lbl.configure(text="" if not self.cfg["show_next"] else self.next_lbl.cget("text"))

    def _tick(self):
        st = fetch_state(self.port) if self.port else None
        # 全局热键 Ctrl+Alt+L：穿透态下唯一不依赖本窗口的退路（线程置标志，这里消费）
        if self._hotkey_fired:
            self._hotkey_fired = False
            if self.cfg["click_through"]:
                self.cfg["click_through"] = False
                self._apply_click_through()
                save_conf(self.cfg)
                self._set_status("穿透已关 · 鼠标恢复")
        if st is None:
            if self.port is None:
                self.port = probe_port(self.cfg.get("port") or 0)
            self.cur_lbl.configure(text="♪ 等待点歌台…（未运行或未找到 OBS 服务）")
            self.next_lbl.configure(text="")
            self.song_lbl.configure(text="")
        else:
            cur, nxt, song = st
            self.cur_lbl.configure(text=cur or "♪")
            self.next_lbl.configure(text=(nxt if self.cfg["show_next"] else ""))
            self.song_lbl.configure(text=song if song and song != "暂无播放" else "")
        self.root.after(300, self._tick)

    # ---------- 交互 ----------
    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()
        self.cur_lbl.bind("<B1-Motion>", self._drag_move)
        self.song_lbl.bind("<B1-Motion>", self._drag_move)

    def _drag_move(self, e):
        x, y = e.x_root - self._dx, e.y_root - self._dy
        self.cfg["x"], self.cfg["y"] = x, y
        self.root.geometry("+%d+%d" % (x, y))

    def _wheel(self, e):
        self.cfg["size"] = max(16, min(96, self.cfg["size"] + (1 if e.delta > 0 else -1)))
        self._restyle()
        save_conf(self.cfg)

    def _set_status(self, msg):
        """更新状态标签；穿透相关提示自动弹出设置条，确保用户看得见。"""
        try:
            self._bar_status.configure(text=msg)
            if not self.bar.winfo_manager():
                self.bar.pack(anchor="w", fill="x", padx=14, pady=(2, 6))
        except Exception:
            pass

    def toggle_click_through(self):
        """切换穿透态。核心不变量：热键未就绪 → 拒绝进入穿透，从根上杜绝锁死。
        退出穿透永远允许（热键线程独立于窗口，Ctrl+Alt+L 不受穿透影响）。"""
        if not self.cfg["click_through"]:
            # 进入穿透前确认热键已注册（线程启动后数毫秒即完成，这里给 0.5s 兜底）
            if not self._hk.registered:
                deadline = time.time() + 0.5
                while not self._hk.registered and time.time() < deadline:
                    time.sleep(0.02)
                if not self._hk.registered:
                    self._set_status("全局热键注册失败，穿透已禁用（Ctrl+Alt+L 被占用？）")
                    return
            self.cfg["click_through"] = True
            self._apply_click_through()
            self._set_status("穿透已开 · 按 %s 恢复鼠标" % (self._hk.label or "全局热键"))
        else:
            self.cfg["click_through"] = False
            self._apply_click_through()
            self._set_status("穿透已关 · 鼠标恢复")
        save_conf(self.cfg)

    def _apply_click_through(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            GWL = -20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL)
            if self.cfg["click_through"]:
                style |= 0x00000020 | 0x00000008   # WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~0x00000020
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL, style)
        except Exception as e:
            print("[WARN] 鼠标穿透设置失败:", e)

    # ---------- 设置条 ----------
    def _build_bar(self):
        def btn(text, cmd):
            b = tk.Button(self.bar, text=text, command=cmd, bg="#334155", fg="white",
                          relief="flat", font=("Microsoft YaHei UI", 9))
            b.pack(side="left", padx=3)
            return b
        btn("字号+", lambda: self._bump(2))
        btn("字号-", lambda: self._bump(-2))
        btn("透明+", lambda: self._bump_op(0.05))
        btn("透明-", lambda: self._bump_op(-0.05))
        btn("下一行", lambda: self._toggle_next())
        btn("穿透", lambda: (not self.cfg["click_through"]) and self.toggle_click_through())
        btn("恢复鼠标", lambda: self.cfg["click_through"] and self.toggle_click_through())
        self._bar_status = tk.Label(self.bar, text="", bg="#22262E", fg="#94A3B8",
                                    font=("Microsoft YaHei UI", 9))
        self._bar_status.pack(side="left", padx=8)
        self.bar.pack_forget()

    def _bump(self, d):
        self.cfg["size"] = max(16, min(96, self.cfg["size"] + d)); self._restyle(); save_conf(self.cfg)

    def _bump_op(self, d):
        self.cfg["opacity"] = max(0.3, min(1.0, round(self.cfg["opacity"] + d, 2)))
        self._restyle(); save_conf(self.cfg)

    def _toggle_next(self):
        self.cfg["show_next"] = not self.cfg["show_next"]; self._restyle(); save_conf(self.cfg)

    def _toggle_bar(self, _e=None):
        if self.bar.winfo_manager():
            self.bar.pack_forget()
        else:
            self.bar.pack(anchor="w", fill="x", padx=14, pady=(2, 6))


def main():
    ap = argparse.ArgumentParser(description="桌面歌词（点歌台 OBS 数据的独立显示端）")
    ap.add_argument("--port", type=int, default=0, help="OBS 服务端口（默认自动探测 8080~8090）")
    args = ap.parse_args()
    cfg = load_conf()
    if args.port:
        cfg["port"] = args.port
    port = probe_port(cfg["port"] or 0)
    root = tk.Tk()
    root.title("桌面歌词")
    DesktopLyric(root, cfg, port)
    root.mainloop()


if __name__ == "__main__":
    main()
