# _study — 参考资料存档（非本项目代码）

本目录是开发抖音接入时研读的**第三方参考资料**，全部只读、不参与构建、不被代码 import：

| 文件 | 来源 | 许可 |
|---|---|---|
| `DOUYIN_PLAN.md` | [SoraYjy/DanmuFree](https://github.com/SoraYjy/DanmuFree) 抖音接入实施计划（协议细节/字段号/坑位清单） | MIT |
| `DouyinProto.cs` / `DouyinMapper.cs` / `DouyinRoomResolver.cs` / `RichMessage.cs` / `BilibiliDanmuClient.cs` | 同上仓库的协议层源码 | MIT |

本项目的 `live_providers/douyin.py` 按这些资料记录的**协议事实**（URL/字段号/参数配方）
用 Python 独立实现，未翻译或包含任何 C# 代码行。协议事实不受版权保护；
为清晰起见在此声明出处。DanmuFree 同时是 sign.js 上游（saermart/DouyinLiveWebFetcher）
的维护跟随者，签名算法变更时优先参考其更新。
