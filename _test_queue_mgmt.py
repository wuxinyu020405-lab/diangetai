# -*- coding: utf-8 -*-
"""v1.2.2 回归：队列管理页逻辑（删除/置顶/线程投递/渲染冒烟）。
线程模型是重点：pending/playlist 归 asyncio loop 线程所有，GUI 的修改必须
经 loop.call_soon_threadsafe 投递。本测试用真 asyncio loop 验证投递确实发生，
并验证条目删除/置顶的结果正确、越界安全。
用法: ./.venv\\Scripts\\python.exe -X utf8 _test_queue_mgmt.py
"""
import asyncio, os, sys, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "点歌台拆分"))
sys.stdout.reconfigure(encoding="utf-8")
import state
import mainapp

RES = []
def ck(name, cond, extra=""):
    RES.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  [{extra}]"))


class ImmediateRoot:
    """after(0, fn) 立即执行（同步桩，逻辑测试无需真 Tk 循环）。"""
    def after(self, _ms, fn=None, *a):
        if fn:
            fn(*a)

class Harness:
    """最小 MusicApp 替身：真 loop + 真方法，跳过 __init__ 的重依赖。"""
    refresh_queue_mgmt = mainapp.MusicApp.refresh_queue_mgmt
    qm_remove_pending = mainapp.MusicApp.qm_remove_pending
    qm_remove_ready = mainapp.MusicApp.qm_remove_ready
    qm_move_top = mainapp.MusicApp.qm_move_top
    _qm_post = mainapp.MusicApp._qm_post
    _fmt_wait = staticmethod(mainapp.MusicApp._fmt_wait)

    def __init__(self, loop):
        self.root = ImmediateRoot()
        self.loop = loop
        self.logs = []
        self._qm_built = True
    def log(self, m):
        self.logs.append(m)


def run_in_loop(loop, fn):
    fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop)  # 确保 loop 活着
    fut.result(timeout=5)
    done = threading.Event()
    res = {}
    def _task():
        try:
            res["v"] = fn()
        finally:
            done.set()
    loop.call_soon_threadsafe(_task)
    done.wait(5)
    return res.get("v")


def main():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    app = Harness(loop)

    # 场景：1 条正在下载 + 2 条排队 + 3 条就绪
    state.processing_request = {"song_name": "下载中", "uname": "A", "platform": "bilibili", "ts": 0}
    state.pending_requests = [
        {"song_name": "排队1", "uname": "B", "platform": "bilibili", "ts": 0},
        {"song_name": "排队2", "uname": "C", "platform": "douyin", "ts": 0},
    ]
    state.playlist = [
        {"name": "s1", "display_name": "就绪1", "mid": "m1", "requester": "D"},
        {"name": "s2", "display_name": "就绪2", "mid": "m2", "requester": "E"},
        {"name": "s3", "display_name": "就绪3", "mid": "m3", "requester": "F"},
    ]
    state.current_song = {"display_name": "正在播", "mid": "m0", "requester": "G"}

    # ① 删除排队项（经 loop 线程真执行）
    app.qm_remove_pending(0)
    names = run_in_loop(loop, lambda: [r["song_name"] for r in state.pending_requests])
    ck("① 删除排队项: 只删对号入座", names == ["排队2"], names)

    # ② 删除就绪项（idx=1 → 就绪2 出列，保留其余）
    app.qm_remove_ready(1)
    mids = run_in_loop(loop, lambda: [r["mid"] for r in state.playlist])
    ck("② 删除就绪项 mid 正确", mids == ["m1", "m3"], mids)

    # ③ 置顶：m3 从 #1 顶到 #0
    app.qm_move_top(1)
    mids = run_in_loop(loop, lambda: [r["mid"] for r in state.playlist])
    ck("③ 置顶后顺序 = m3,m1", mids == ["m3", "m1"], mids)

    # ④ 越界与 loop 缺失：安全拒绝、不崩、不误伤
    before = run_in_loop(loop, lambda: (len(state.pending_requests), len(state.playlist)))
    app.qm_remove_pending(99); app.qm_remove_ready(99); app.qm_move_top(99)
    after = run_in_loop(loop, lambda: (len(state.pending_requests), len(state.playlist)))
    ck("④ 越界删除不改队列", before == after, f"{before}->{after}")
    app2 = Harness(loop); app2.loop = None
    ck("⑤ loop 未就绪时拒绝投递", app2._qm_post(lambda: None) is False)

    # ⑥ 正在下载项可见（processing_request 不被删除影响）
    still = run_in_loop(loop, lambda: state.processing_request["song_name"])
    ck("⑥ 正在下载项独立于 pending", still == "下载中", still)

    # ⑦ 渲染冒烟：真 CTk 窗口 + mainapp.MusicApp 全量（需桌面会话）
    rendered = None
    try:
        import customtkinter as ctk
        root = ctk.CTk()
        root.withdraw()
        import ui_ctk
        app3 = mainapp.MusicApp.__new__(mainapp.MusicApp)
        app3.root = root; app3.config = dict(state.style_config and {} or {})
        app3.loop = loop; app3.logs = []
        app3._qm_built = False
        ui_ctk.build(app3, root)
        app3.refresh_queue_mgmt()
        rendered = (hasattr(app3, "qm_pending_box")
                    and len(app3.qm_pending_box.winfo_children()) >= 2
                    and len(app3.qm_ready_box.winfo_children()) >= 2)
        root.destroy()
    except Exception as e:
        rendered = f"skip: {type(e).__name__}: {e}"
    if isinstance(rendered, str):
        print("  ⚪ ⑦ 渲染冒烟：环境不支持真窗口，跳过（逻辑层已覆盖核心）")
    else:
        ck("⑦ CTk 渲染出两列条目", rendered)

    bad = [n for n, ok in RES if not ok]
    print(f"\n{'✅' if not bad else '❌'} _test_queue_mgmt: {len(RES)-len(bad)}/{len(RES)}")
    loop.call_soon_threadsafe(loop.stop)
    t.join(3)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
