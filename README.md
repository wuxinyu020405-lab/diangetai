# 🎤 扫码点歌台

B 站直播间弹幕点歌 + OBS 可视化一体化工具（Windows）。

观众在直播间发弹幕 `点歌 歌名`，程序自动搜索 QQ 音乐 → 下载 → 播放；
OBS 画面实时显示点歌队列与滚动歌词；点歌间隙自动让位/恢复主播本地 BGM。

![平台](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-blue)
![版本](https://img.shields.io/badge/version-v1.0.0-green)
![许可](https://img.shields.io/badge/license-MIT-lightgrey)

## 功能一览

- **弹幕点歌 / 切歌**：`点歌 xxx` 入队，`切歌` 跳过；串行处理，逐首给明确结论
- **OBS 四种挂件**：综合 / 纯歌词 / 正在播放 / 点歌列表，样式全部可视化配置
- **三种歌词动效**：苹果高清滚动、景深滚动、静态（含逐行错峰与渐隐遮罩）
- **BGM 智能让位**：经系统媒体接口（SMTC）暂停/恢复你自己的 QQ 音乐播放
- **本地优先**：已缓存的歌秒进队列，不重复下载、不占配额
- **配额熔断**：日下载上限 + 连续失败自动冷却，防止账号被上游风控
- **零依赖分发**：内置 .NET 运行时，目标机器免装 Python/.NET/驱动

## 下载与安装

到 [Releases](../../releases) 下载：

| 文件 | 用法 |
|---|---|
| `点歌台_Setup_vX.Y.Z.exe` | 安装包（推荐）：双击安装，开始菜单/桌面出快捷方式 |
| `点歌台_vX.Y.Z_portable.zip` | 便携版：完整解压到任意文件夹，双击 `点歌台.exe` |

> ⚠️ 便携版必须**整个文件夹**一起用，只拷 exe 打不开。
> PyInstaller 产物可能被杀软误报，加入信任即可；源码在手，欢迎自验。

首次使用：打开程序 →「账号登录」页扫码登录 **B 站** 与 **QQ 音乐**
（音质取决于你自己的会员等级）→ 重启程序生效。

## OBS 挂件

程序运行时添加 OBS「浏览器」源：

```
http://127.0.0.1:8080/          综合挂件
http://127.0.0.1:8080/lyric     纯歌词
http://127.0.0.1:8080/playing   正在播放
http://127.0.0.1:8080/queue     点歌列表
```

（8080 被占用时程序自动改用 8081~8090，以运行日志/GUI 顶部按钮复制的地址为准。）

## 观众指令

| 弹幕 | 效果 |
|---|---|
| `点歌 晴天` | 搜索并点播《晴天》（下载成功才进队列） |
| `切歌` | 跳过当前歌曲 |

## 从源码运行

```powershell
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
pip install --no-deps "blivedm @ https://github.com/xfgryujk/blivedm/archive/refs/heads/master.tar.gz"
git clone --depth 1 https://github.com/r0x0r/pywebview && pip install ./pywebview
python 点歌台拆分\main.py            # 或 --selftest 做环境体检
```

要求 Python 3.12（winsdk 预发布版 wheel 上限）。模块划分与内部机制见
[点歌台拆分/README.md](点歌台拆分/README.md)。

## 打包与发版

```powershell
python -m PyInstaller 点歌台拆分\点歌台.spec --noconfirm
ISCC.exe /DMyAppVersion=1.0.0 点歌台.iss        # Inno Setup 安装包
```

版本单一来源 = `点歌台拆分/version.py`。发版：改版本号 → 提交 → 打 tag
`vX.Y.Z` → GitHub Actions 自动出安装包并发布 Release。详见 [打包说明.md](打包说明.md)。

## ⚖️ 免责与合规（务必阅读）

- 本工具**不内置任何账号或曲库**，点歌使用**你自己登录**的 QQ 音乐 / B 站账号，
  产生的账号风控、会员权限、下载限额问题由使用者自行承担。
- 通过本工具获取的歌曲音频**仅限直播间内个人使用**，请勿二次分发、录制传播，
  尊重音乐版权；由此引发的版权纠纷与本仓库无关。
- 弹幕自动化行为可能违反 B 站用户协议，风险自负；请勿用于任何违规场景。
- 代码按 MIT 许可提供，无任何担保。

## 常见问题速查

| 现象 | 处理 |
|---|---|
| 双击没反应 / 一闪而过 | 便携版是否完整解压（`_internal`、`dotnet` 须在同级） |
| 登录窗口打不开 | 运行 `点歌台.exe --selftest`，把 `自检报告.txt` 对照 [使用说明](使用说明.md) §Q1 |
| 点歌一直失败 | 看日志单行原因：配额熔断=等 10 分钟；设备受限=重扫 QQ 音乐 |
| 播完没恢复 BGM | 需装 QQ 音乐 PC 客户端并登录（SMTC 控制） |

完整说明：[使用说明.md](使用说明.md) · 缺陷清单：[点歌台拆分/README.md](点歌台拆分/README.md#已知缺陷v10-未修记录在案)

## License

[MIT](LICENSE)
