# C 档调研报告（2026-11-04）

> 对应待办清单 #2 抖音 / #3 网易云 / #4 平台选择。方法=先 GitHub 搜现成方案（#9 原则），
> 逐仓库核实活跃度，再评估接入路径与风险。**结论先行：两个平台都不该"直接开干"，
> 但都有可行路径，且必须先做架构准备（provider 抽象层）。**

---

## 一、抖音直播弹幕接入

### 官方路线（查证结果：个人主播基本走不通）
- 抖音开放平台有直播相关能力（easydouyin 等社区 SDK 佐证 API 存在），但定位是
  **主播自己的 App/小程序 + 企业开发者资质 + 用户 OAuth**；
- V2EX 实测讨论（v2ex.com/t/970630）：官方 SDK **没有开放写弹幕接口**，读弹幕
  也仅限自家应用场景；
- 我们是"个人主播在自己直播间收观众弹幕"——理论沾边，实际卡在**企业资质**门槛。

### 社区路线（查证结果：存在，但全部高维护成本）
| 仓库 | 星数 | 状态 | 技术路线 |
|---|---|---|---|
| isaackogan/TikTokLive | 高（#1 Python 库） | 活跃 | ❌ **只支持国际版 TikTok，不支持国内抖音**（协议/签名不同） |
| scx567888/live-room-watcher | ★511 | Java，半活跃 | 多平台逆向（抖音/快手/B站），protobuf 解析 |
| lulajax/DouyinLiveJava | ★18 | 小 | 抖音 WebSocket + protobuf 逆向 |
| youyouhe/douyin-live-chat | ★0 | 新 | **cookie 注入 + 真实 Chrome + 增量游标**（浏览器辅助路线） |
| xiaoyaocz/AllLive | ★5500 | Go | 多平台弹幕聚合（Unity/OBS 生态，非通用服务） |
| Evil0ctal/Douyin_TikTok_Download_API | 高 | issue 区"现在是不是抖音和tk都不行了" | 签名对抗的晴雨表 |

**技术本质**：抖音 web 直播弹幕 = WebSocket + protobuf + 动态签名（a_bogus/msToken 类），
签名持续轮换 → 纯逆向库"隔几个月死一次"是社区常态。两条活路：
1. **纯逆向**（轻，但每次抖音改版都要跟进，单人维护会疲于奔命）
2. **浏览器辅助**（Playwright/真实 Edge 进直播间页，注入 JS hook WebSocket 帧 →
   base64 protobuf → 解析。重 ~几十MB，但**签名由浏览器自己算**，抗改版能力最强，
   是 2025 后社区新势力的共同选择（youyouhe 方案即此类））

### 对本项目的判定
- ✅ 技术上可行，推荐**浏览器辅助路线**（与本项目"内嵌 WebView2 扫码"技术栈同源，
  登录态用观众扫码获得，复用 browserlogin 模式）
- ⚠️ 成本：首版 1~2 周 + **长期跟随抖音改版的维护承诺**；弹幕发送（回执）在抖音
  侧无稳定社区方案，比 B 站难
- ⚠️ 风险：抖音对自动化登录态检测比 B 站凶，观众账号有封禁风险
- **建议：暂缓。先做架构准备（见第三节），等真实需求出现（朋友真的开抖音直播）
  再立项，首战用 Playwright+Edge 方案做 spike（1 天验证能不能稳定收到弹幕再谈集成）**

---

## 二、网易云音乐接入

### 官方路线（查证结果：无通用播放 API）
- 网易云音乐开放平台（developer.music.163.com）存在，但面向**音乐人/版权方**
  （歌曲管理、数据），不提供第三方取播放 URL 的通用能力；个人申请无门。

### 社区路线（查证结果：能用，但头顶有律师函）
- **Binaryify/NeteaseCloudMusicApi**（★30233，事实标准）：**2024-01 被网易法务
  要求删库停更**（IT之家报道 m.ithome.com/html/746942.htm），GitHub 归档；
  作者转 npm 渠道维护（npm 页 2026-08 仍有版本），社区大量复活 fork
  （xgxdmx/NeteaseMusic-API、api-enhanced、gitee 镜像等）。
- 能力面：搜索/歌词/歌单/用户登录全有；**播放 URL**：免费歌可取，VIP 歌需
  用户自己的黑胶 VIP cookie（与 QQ 音乐模式一致）。

### 对本项目的判定（关键差异：法律姿态）
- QQ 音乐的 qqmusic-api-python 目前**没有**收到平台律师函的公开记录；
  网易云**有明确先例**——对一个 GitHub 公开分发的工具，把网易云取源代码
  **打进包里**是给自己递刀。
- **建议采用"适配器不打包"模式**：
  1. 本项目只实现一个 `NeteaseProvider`，它调用**用户自行部署**的
     NeteaseCloudMusicApi 兼容服务（HTTP，本地或自建）；
  2. 搜索/歌词/URL 全走这个外部服务，本项目代码里**零逆向、零签名**；
  3. README 写清自建方法。风险形态与"用户装个插件"等同，工具本体干净。
- 工程量：半天（HTTP 客户端 + 接口映射），前提是用户愿意跑一个 Node 服务
  ——对普通主播有门槛，对折腾型用户可行。
- **优先级：中。等 provider 抽象层就位后，这是最容易先落地的第二平台。**

---

## 三、#4 平台选择的前置：Provider 抽象层（真正的地基）

现状：`musiclib.py` 是隐式的"QQ 音乐实现"（搜索/取址/缓存命名 `{mid}_{tier}` 全耦合）。
接第二平台前必须抽层，否则每加一个平台就重写一遍 danmaku/mainapp：

```
providers/
  base.py       # 接口：search(keyword)->[SongRef] / get_stream(song,q)->url / get_lyric(song)->lrc
                # 平台名、能力声明（有无无损/要不要VIP）、缓存命名规则 {platform}_{mid}_{tier}
  qqmusic.py    # 现有 musiclib 逻辑平移（行为不变，_test_* 回归护航）
  netease.py    # 外部 API 适配器（第二节方案）
live_providers/
  bilibili.py   # 现有 blivedm + bilibili_send 平移
  douyin.py     # 未来 spike 落点（第一节方案）
```

弹幕语法（#4 的观众侧入口）：默认平台走 GUI 配置；
`网易点歌 xx` / `B站点歌 xx` 前缀覆盖单次。队列项加 `platform` 字段，
OBS 列表可显示平台角标。

**工作量**：抽象层重构 2~3 天（含回归），是 C 档所有后续的地基，
**建议列入 v1.3 主线**。

---

## 四、行动建议汇总

| 顺序 | 动作 | 依据 |
|---|---|---|
| 1 | v1.2 先出不依赖 C 档的东西（桌面歌词集成、B2/H2 已完成的发版） | 不阻塞 |
| 2 | v1.3 做 provider 抽象层（纯重构，行为不变） | 第三节 |
| 3 | 网易云适配器（外部 API 模式）最先接入 | 第二节：半天量、法律干净 |
| 4 | 抖音：1 天 spike（Playwright 收弹幕可行性）→ 成了再立项 | 第一节：先验风险 |
| 5 | #4 平台选择 UI 跟随 2/3 落地 | 依赖抽象层 |

> 调研引用（均为 2026-11-04 实时检索）：v2ex.com/t/970630、
> m.ithome.com/html/746942.htm、github.com/isaackogan/TikTokLive、
> github.com/Binaryify/NeteaseCloudMusicApi、github.com/youyouhe/douyin-live-chat、
> github.com/scx567888/live-room-watcher、developer.music.163.com
