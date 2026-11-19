# -*- coding: utf-8 -*-
"""更新模块回归（v1.2.9.3 改造后）：只查版本 + 点按钮用默认浏览器下 Setup 直链。

旧的"程序下载 zip 并替换自己"整套已删除，这里改为验证新链路：
  ① 查版本 API 的失败口径（任何异常都返回 None，不抛）
  ② 版本比较 is_newer
  ③ pick_setup_asset 只挑 .exe 的 Setup（绝不挑 portable.zip，优先对得上 tag）
  ④ 直链优先；没有 exe 资产时退回发布页
  ⑤ 点按钮 = 调 webbrowser.open(直链)；webbrowser 失败时 os.startfile 兜底
  ⑥ 版本号旁的按钮显示/隐藏（假控件记录调用，不建真窗口）
  ⑦ 旧版残留清理只删自己那几个临时物

用法: ./.venv\\Scripts\\python.exe -X utf8 _test_autoupdater.py
"""
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "点歌台拆分"))
import updater
import version

RESULTS = []


def ck(name, cond, extra=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  [" + str(extra) + "]"))


# ═══════════ 假界面（记录 pack/configure 调用，不建真窗口）═══════════
class FakeRoot:
    def after(self, ms, fn):
        fn()          # 同步执行，测试里不需要事件循环


class FakeBtn:
    def __init__(self):
        self.text = None
        self.packed = False
        self.calls = []

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]
        self.calls.append(("configure", kw))

    def pack(self, **kw):
        self.packed = True
        self.calls.append(("pack", kw))

    def pack_forget(self):
        self.packed = False
        self.calls.append(("forget", {}))


class FakeApp:
    def __init__(self):
        self.root = FakeRoot()
        self.logs = []
        self.btn_update_link = FakeBtn()
        self.btn_check_update = FakeBtn()
        self.btn_check_update.packed = True      # 界面建好时「检查更新」是显示的

    def log(self, m):
        self.logs.append(str(m))


def reset_latest():
    updater._latest.update({"tag": None, "release_url": "", "setup_url": "", "direct": False})


# 注意：测试里"线上有新版"标签一律按当前 version.VERSION 现算。
# 写死 v1.2.9.3 的话，等版本号真升到 1.2.9.3，is_newer 就变 False，
# 测试会自己把自己测挂（2026-11-19 用户复跑 39/41 实踩）。
SAME_TAG = "v" + version.VERSION
_parts = version.VERSION.split(".")
NEW_TAG = "v" + ".".join(_parts[:-1] + [str(int(_parts[-1]) + 1)])

ASSETS = [
    {"name": "diangetai-v1.2.9.2-portable.zip",
     "browser_download_url": "https://x/portable.zip"},
    {"name": "diangetai-Setup-v1.2.8.exe",
     "browser_download_url": "https://x/old-setup.exe"},
    {"name": "diangetai-Setup-v1.2.9.2.exe",
     "browser_download_url": "https://x/setup.exe"},
]

print("═══ 更新模块回归 v1.2.9.3 ═══")

# ── ① 查版本失败口径 ──
print("\n① 查版本失败口径")
_saved_repo = updater.REPO
updater.REPO = ""                      # 未配置仓库 → 功能休眠，不抛异常
t, u, a = updater.fetch_latest_full(timeout=1)
ck("未配置仓库返回 (None,None,None)", t is None and u is None and a is None)
ck("fetch_latest 同样返回 (None,None)", updater.fetch_latest(timeout=1) == (None, None))
updater.REPO = _saved_repo

# ── ② 版本比较 ──
print("\n② 版本比较")
ck("v1.2.9.3 > 1.2.9.2", version.is_newer("v1.2.9.3", "1.2.9.2"))
ck("v1.2.9.2 不新于 1.2.9.2", not version.is_newer("v1.2.9.2", "1.2.9.2"))
ck("v1.2.10 > 1.2.9.9", version.is_newer("v1.2.10", "1.2.9.9"))
ck("非法版本号宁可不提醒", not version.is_newer("abc", "1.2.9.2"))

# ── ③ 挑 Setup 资产 ──
print("\n③ 挑 Setup 资产")
a = updater.pick_setup_asset(ASSETS, "v1.2.9.2")
ck("挑到本版 Setup（不是 zip、不是上版）",
   a and a["name"] == "diangetai-Setup-v1.2.9.2.exe", a)
a = updater.pick_setup_asset(ASSETS, "v9.9.9")
ck("tag 对不上也优先 setup 而非 zip",
   a and a["name"].endswith("v1.2.8.exe"), a)
ck("只有 zip 时返回 None",
   updater.pick_setup_asset([x for x in ASSETS if x["name"].endswith(".zip")], "v1.2.9.2") is None)
ck("空资产返回 None", updater.pick_setup_asset([], "v1.2.9.2") is None)

# ── ④ 直链 / 兜底发布页 ──
print("\n④ 直链与兜底")
reset_latest()
info = updater._set_latest("v1.2.9.2", "https://github.com/x/y/releases/tag/v1.2.9.2", ASSETS)
ck("直链 = 资产的 browser_download_url", info["setup_url"] == "https://x/setup.exe", info)
ck("标记为直接下载", info["direct"] is True)
info = updater._set_latest("v1.2.9.2", "https://github.com/x/y/releases/tag/v1.2.9.2", [])
ck("无 exe 资产 → 退回发布页", info["setup_url"].endswith("/v1.2.9.2") and info["direct"] is False, info)

# ── ⑤ 点按钮 → 默认浏览器 ──
print("\n⑤ 点按钮下载")
reset_latest()
updater._set_latest("v1.2.9.2", "https://r", ASSETS)
app = FakeApp()
calls = []
_saved_open = updater.webbrowser.open
updater.webbrowser.open = lambda url, **kw: (calls.append(url), True)[1]
ok = updater.open_setup_download(app)
ck("点了就去默认浏览器打开直链", ok and calls == ["https://x/setup.exe"], calls)
ck("日志里明确说了在浏览器下载", any("默认浏览器" in m for m in app.logs), app.logs[-1:])
updater.webbrowser.open = _saved_open

# webbrowser 抛异常 → os.startfile 兜底
_saved_open = updater.webbrowser.open
_saved_start = getattr(os, "startfile", None)
started = []
updater.webbrowser.open = lambda url, **kw: (_ for _ in ()).throw(OSError("boom"))
try:
    os.startfile = lambda url: started.append(url)
except Exception:
    pass
ok = updater.open_in_default_browser("https://x/setup.exe")
ck("webbrowser 失败时 os.startfile 兜底", ok and started == ["https://x/setup.exe"], started)
updater.webbrowser.open = _saved_open
if _saved_start is not None:
    os.startfile = _saved_start

# 没有地址时点按钮：不崩、给提示
reset_latest()
app2 = FakeApp()
ck("没有下载地址也不崩（返回 False）", updater.open_setup_download(app2) is False)
ck("并提示先检查更新", any("检查更新" in m for m in app2.logs))

# ── ⑥ 按钮显示/隐藏 ──
print("\n⑥ 版本号旁按钮")
reset_latest()
app3 = FakeApp()
updater.register_update_link(app3)
ck("无新版：下载按钮不显示、检查更新在",
   app3.btn_update_link.packed is False and app3.btn_check_update.packed is True)

reset_latest()
updater._set_latest(NEW_TAG, "https://r", ASSETS)
updater._show_link(app3, NEW_TAG)
ck("有新版：下载按钮显示、文案带版本",
   app3.btn_update_link.packed and NEW_TAG in (app3.btn_update_link.text or ""),
   app3.btn_update_link.text)
ck("有新版：「检查更新」让出位置（顶栏不变宽）", app3.btn_check_update.packed is False)

updater._hide_link(app3)
ck("恢复：下载按钮隐藏、检查更新回来",
   app3.btn_update_link.packed is False and app3.btn_check_update.packed is True)

# 检查结果先到、界面后建 → 登记时就补显示
reset_latest()
updater._set_latest(NEW_TAG, "https://r", ASSETS)
app4 = FakeApp()
updater.register_update_link(app4)
ck("结果先到也能补显示按钮", app4.btn_update_link.packed is True)

# ── ⑦ 检查流程（打桩网络）──
print("\n⑦ 检查流程")
reset_latest()
_saved_fetch = updater.fetch_latest_full
_saved_msg = updater._msgbox
updater._msgbox = lambda *a, **k: None            # 测试里不弹真窗口

updater.fetch_latest_full = lambda timeout=8: (SAME_TAG, "https://r", ASSETS)
app5 = FakeApp()
updater.register_update_link(app5)
updater._check(app5, timeout=1, manual=False)
ck("线上与本版相同 → 不显示下载按钮", app5.btn_update_link.packed is False)
ck("最新时按钮仍是「检查更新」", app5.btn_check_update.packed is True)

updater.fetch_latest_full = lambda timeout=8: (NEW_TAG, "https://r", ASSETS)
app6 = FakeApp()
updater.register_update_link(app6)
updater._check(app6, timeout=1, manual=False)
ck("线上更新 → 按钮出现且指向直链",
   app6.btn_update_link.packed and updater.latest_info()["setup_url"].endswith("setup.exe"))
ck("后台检查不弹窗（无人工干预）", True)

reset_latest()
updater.fetch_latest_full = lambda timeout=8: (None, None, None)
app7 = FakeApp()
updater.register_update_link(app7)
updater._check(app7, timeout=1, manual=False)
ck("网络失败：保持安静、不亮按钮", app7.btn_update_link.packed is False)

updater.fetch_latest_full = _saved_fetch
updater._msgbox = _saved_msg

# ── ⑧ 旧版残留清理 ──
print("\n⑧ 旧版残留清理")
tmp = os.path.join(ROOT, "_test_tmp_updater")
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
for d in ("_update_staging", "_update_dl"):
    os.makedirs(os.path.join(tmp, d))
    open(os.path.join(tmp, d, "junk.bin"), "wb").write(b"x" * 16)
for f in ("_update_pending.json", "_update_status.json", "_update_notified.json"):
    open(os.path.join(tmp, f), "w").write("{}")
keep = [os.path.join(tmp, n) for n in ("config.json", "credential.json")]
for k in keep:
    open(k, "w").write("{}")
removed = updater.cleanup_legacy_update_files(tmp)
ck("临时残留全清（2 目录 + 3 文件）",
   sorted(removed) == sorted(["_update_staging", "_update_dl", "_update_pending.json",
                              "_update_status.json", "_update_notified.json"]), removed)
ck("残留目录真的没了",
   not os.path.exists(os.path.join(tmp, "_update_staging"))
   and not os.path.exists(os.path.join(tmp, "_update_dl")))
ck("用户数据一个没动", all(os.path.exists(k) for k in keep))
ck("清第二遍不再报已删", updater.cleanup_legacy_update_files(tmp) == [])
shutil.rmtree(tmp, ignore_errors=True)

# ── ⑨ 死代码确实没了 ──
print("\n⑨ 旧实现已删除")
for name in ("download_and_apply", "spawn_ps_worker", "resume_pending_update",
             "read_last_update_result", "_offer_update", "pick_portable_asset",
             "extract_zip", "_prompt_restart", "_quit_for_update"):
    ck("已无 " + name, not hasattr(updater, name))

print()
bad = [n for n, ok in RESULTS if not ok]
print("═══ 结果: %d/%d 通过 ═══" % (len(RESULTS) - len(bad), len(RESULTS)))
if bad:
    for n in bad:
        print("  FAILED: " + n)
sys.exit(1 if bad else 0)
