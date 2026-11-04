# -*- coding: utf-8 -*-
"""live_providers：直播平台弹幕接入层（B站=blivedm 现有路径 / 抖音=本包）。

统一消息模型 DanmuMsg：provider 收到的任何弹幕/事件都映射成它，
danmaku.handle_message 是两平台共用的指令入口（点歌/切歌/暂停）。
参考架构：SoraYjy/DanmuFree 的 RichMessage + 统一 client 接口。
"""
from dataclasses import dataclass, field


@dataclass
class DanmuMsg:
    platform: str          # "bilibili" | "douyin"
    type: str              # chat | member | social | gift
    uname: str
    text: str
    extra: str = ""
    raw: dict = field(default_factory=dict)
