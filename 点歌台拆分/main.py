"""
程序入口
"""

import tkinter as tk
import json
import os
import mainapp
import musiclib
import settings
import state

if __name__ == '__main__':
    # 启动时清理损坏文件
    print("[INFO] 启动时扫描缓存目录，清理损坏文件...")
    musiclib.clean_corrupted_files(settings.CACHE_DIR)
    settings.load_credential()
    def launch_main_app(config):
        main_root = tk.Tk(); global app
        state.app = mainapp.MusicApp(main_root, config); main_root.mainloop()
    if os.path.exists(settings.CONFIG_FILE):
        with open(settings.CONFIG_FILE, "r", encoding="utf-8") as f: config_data = json.load(f)
        launch_main_app(config_data)
    else:
        launch_main_app({"room_id": "", "bili_cookie": "", "qqmusic_path": ""})
