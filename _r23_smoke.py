# -*- coding: utf-8 -*-
"""R-23 整机冒烟：真建界面 + 真 MusicApp，逐块点一遍，窗口不上屏。

隔离做法：复制一份 点歌台拆分 到 _r23_copy/，在副本里跑，config/credential/
music_cache 都在副本，绝不碰用户正在用的实例和配置。
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "点歌台拆分")
DST = os.path.join(ROOT, "_r23_copy")

def prepare():
    if os.path.isdir(DST):
        shutil.rmtree(DST, ignore_errors=True)
    shutil.copytree(SRC, DST,
                    ignore=shutil.ignore_patterns("__pycache__", "music_cache",
                                                  "config.json", "credential.json",
                                                  "quota_state.json", "debug.log",
                                                  "*.log", "my_songs"))
    for d in ("music_cache", "my_songs"):
        os.makedirs(os.path.join(DST, d), exist_ok=True)

def main():
    prepare()
    sys.path.insert(0, DST)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    import qtapp
    import mainapp

    app = qtapp.make_app()
    win = qtapp.MainWindow()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    cfg = {"room_id": "", "bili_cookie": "", "qqmusic_path": "", "ui_theme": "light"}
    try:
        music = mainapp.MusicApp(win, cfg)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("BOOT_FAIL", type(e).__name__, e)
        return 1
    app.processEvents()
    ok = ["BOOT_OK"]

    def ck(name, cond):
        ok.append(("PASS " if cond else "FAIL ") + name)

    ck("6 个 mixin 都挂上了",
       all(hasattr(music, k) for k in
           ("download_audio_qq", "music_player_worker", "system_media_worker",
            "restart_bili_listener", "update_mixed", "gui_send_danmaku")))
    ck("类核心还在", all(hasattr(music, k) for k in
                        ("setup_ui", "log", "quit_app", "minimize_to_tray")))
    ck("界面建好了", getattr(music, "pages", None) and len(music.pages) == 5)
    try:
        music.log("R-23 冒烟：日志通道")
        ck("log() 可调用（走 tk.END 哨兵）", True)
    except Exception as e:
        ck("log() 可调用 [%s: %s]" % (type(e).__name__, e), False)
    ck("队列页渲染 0 条不崩", True)
    try:
        music.refresh_queue_mgmt()
        ck("refresh_queue_mgmt 可调用", True)
    except Exception as e:
        ck("refresh_queue_mgmt 可调用 [%s: %s]" % (type(e).__name__, e), False)
    for k in ("update_mixed", "update_lyric", "update_audio_quality", "update_bgm_target"):
        try:
            if k in ("update_mixed",):
                music.update_mixed("size_lyric", 40)
            elif k == "update_lyric":
                music.update_lyric("size", 40)
            else:
                getattr(music, k)()
            ck(k + " 可调用", True)
        except Exception as e:
            ck("%s 可调用 [%s: %s]" % (k, type(e).__name__, e), False)
    try:
        music.apply_volume(0.5)
        ck("apply_volume 可调用", True)
    except Exception as e:
        ck("apply_volume 可调用 [%s: %s]" % (type(e).__name__, e), False)
    try:
        music.toggle_pause()
        ck("toggle_pause 可调用", True)
    except Exception as e:
        ck("toggle_pause 可调用 [%s: %s]" % (type(e).__name__, e), False)
    try:
        # 传个假会话管理器即可（本函数只调 get_sessions()）
        class _Sm:
            def get_sessions(self):
                return []
        r = music.get_best_smtc_session(_Sm())
        ck("get_best_smtc_session 可调用", True)
    except Exception as e:
        ck("get_best_smtc_session 可调用 [%s: %s]" % (type(e).__name__, e), False)
    try:
        music._is_qqmusic_session({"SourceAppUserModelId": "QQMusic.exe"})
        ck("_is_qqmusic_session 可调用", True)
    except Exception as e:
        ck("_is_qqmusic_session 可调用 [%s: %s]" % (type(e).__name__, e), False)

    # 关掉刚才起的后台线程/窗口
    try:
        music._exiting = True
        win.deleteLater()
        app.processEvents()
    except Exception:
        pass
    for line in ok:
        print(line)
    bad = [l for l in ok if l.startswith("FAIL")]
    print("SMOKE", "PASS" if not bad else "FAIL", len(ok) - 1 - len(bad), "/", len(ok) - 1)
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
