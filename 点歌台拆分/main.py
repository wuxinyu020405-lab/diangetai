"""
程序入口（customtkinter 界面）
"""

import json
import os

import customtkinter as ctk

import mainapp
import musiclib
import settings
import state


def launch_main_app(config):
    # 根窗口必须是 ctk.CTk（普通 tk.Tk 不支持 CTk 的配色参数）
    root = ctk.CTk()
    state.app = mainapp.MusicApp(root, config)
    root.mainloop()


if __name__ == '__main__':
    # 启动时清理损坏文件
    print("[INFO] 启动时扫描缓存目录，清理损坏文件...")
    musiclib.clean_corrupted_files(settings.CACHE_DIR)
    settings.load_credential()

    if os.path.exists(settings.CONFIG_FILE):
        with open(settings.CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        launch_main_app(config_data)
    else:
        launch_main_app({"room_id": "", "bili_cookie": "", "qqmusic_path": ""})
