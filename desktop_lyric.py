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
        root.bind("c", lambda e: self.set_click_through(not cfg["click_through"]))
        root.bind("s", self._toggle_bar)
        root.bind("<Escape>", lambda e: root.destroy())
        self._dx = self._dy = 0
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

    def set_click_through(self, on):
        self.cfg["click_through"] = on
        self._apply_click_through()
        save_conf(self.cfg)
        if on:
            # 穿透后收不到键鼠：绑定恢复热键的唯一办法=再点一次 S 区域无效，
            # 故穿透模式仅在设置条里开，且提示恢复方式（托盘后续再加）
            self._bar_status("鼠标穿透已开：再按设置条按钮恢复（穿透时窗口收不到键鼠）")

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
        btn("穿透", lambda: self.set_click_through(True))
        btn("恢复鼠标", lambda: self.set_click_through(False))
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
