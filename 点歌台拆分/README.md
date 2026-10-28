# 扫码点歌台 v1.0（拆分版）

B 站直播间弹幕点歌 + OBS 可视化一体化工具。观众发「点歌 歌名」，程序自动
搜索 QQ 音乐 → 下载 → 播放，OBS 画面实时显示队列与滚动歌词；点歌间隙自动
恢复主播本地 BGM（SMTC 控制）。

由单文件 `扫码点歌台_优化首次成功_4.py` 拆分而来（原版已归档在 git 历史首
个基线提交），拆分后又落地了三批需求改造：串行点歌、两档音质、本地优先、
配额熔断、失败归因、端口顺延、pywebview 登录、customtkinter 界面。
**v1.0 已经朋友实机验证通过（2026-10-28）。**

## 运行

```powershell
cd D:\点歌台干活处
.\.venv\Scripts\Activate.ps1
python 点歌台拆分\main.py            # 首次需在"账号登录"页扫码 B站 + QQ音乐
python 点歌台拆分\main.py --selftest # 自检：依赖/WebView2/内嵌浏览器逐项体检
```

配置读 `点歌台拆分\config.json`、`credential.json`，音频缓存 `music_cache\`，
配额记账 `quota_state.json`（均相对程序目录；打包版在 exe 同级）。

## 模块划分

| 文件 | 职责 |
| --- | --- |
| `main.py` | 入口 + `--selftest` 自检 + .NET 运行时定位（coreclr/DOTNET_ROOT） |
| `mainapp.py` | `MusicApp`：customtkinter 控制台 + asyncio worker 编排 + 下载主流程 |
| `danmaku.py` | 弹幕指令解析（点歌/切歌）+ 串行点歌 worker（就绪才入列） |
| `overlay.py` | OBS 浏览器源：单页 HTML + `/`、`/lyric`、`/playing`、`/queue`、`/api/data` |
| `musiclib.py` | QQ 音乐取址/枚举探测、缓存管理、失败归因、配额记账（跨重启） |
| `settings.py` | 路径/配置合并/两档音质链/凭据存取/浏览器与驱动版本探测 |
| `browserlogin.py` | pywebview（WebView2）内嵌扫码登录 B站 / QQ音乐，无残留进程 |
| `ui_ctk.py` | customtkinter 界面（7 个标签页），只写配置不写业务 |
| `lyrics.py` | LRC 解析、当前行窗口计算 |
| `smtc.py` | 兜底：从 QQ 音乐窗口标题读正在播放 |
| `state.py` | 跨模块运行时状态（一律 `state.xxx` 属性访问，不用裸 global） |

## 关键行为

- **端口顺延**：OBS 服务从 8080 起试到 8090，实际端口写入 `state.overlay_port`，
  GUI 四个"复制挂件地址"按钮点击时读它；日志提示改用哪个端口。
- **串行点歌**：弹幕只进 `pending_requests`，单 worker 逐首出结论（就绪/缓存/
  配额拦截/失败原因），下载成功或缓存命中才进 `playlist`。
- **两档音质**：`flac → 默认` 降级链；旧配置值 master/hires 自动归一为 flac。
- **配额熔断**：日下载上限 150；连续 5 首配额类失败熔断 10 分钟（缓存中的歌
  仍可播）；记账持久化 `quota_state.json`，跨自然日归零。
- **单首预算**：45s，档位/重试/流式写盘三级检查，超时放弃整首不烧队列。
- **半包防护**：下载写 `.part` 完成后原子改名；启动清理 >10min 孤儿 `.part`。
- **BGM 让位**：点歌开始 SMTC 暂停本地播放，队列清空自动恢复（`local⇄api` 两态）。
- **启动兜底**：后台线程任何异常写进 GUI 日志 + 落盘 `启动日志.txt`，不静默卡死。

## 已知缺陷（v1.0 未修，记录在案）

- OBS 队列/静态歌词用 `innerHTML` 拼接，歌名或观众名含 HTML 标签会注入渲染
  （仅本地挂件画面，无 cookie 泄露面）；滚动歌词路径用 `textContent`，安全。
- LRC 重复时间戳行（`[a][b]文本`）第二个标记会当正文显示；`[..]//注释` 会显示。
- 启动时 `clean_corrupted_files` 在 mixer init 前调用，损坏校验分支不执行
  （只按体积清残片，行为可接受）；伴随一条无害的 SDL `can't open file` 输出。
- 无点歌去重/队列上限/按用户频控（串行 + 配额已天然限速）。

## 打包

```powershell
python -m PyInstaller 点歌台拆分\点歌台.spec --noconfirm --distpath dist --workpath build
```

产物 `dist\点歌台\`（onedir，约 278MB，内置 .NET 6 运行时，目标机免装）。
必须整个文件夹分发，只拷 exe 必然打不开。踩坑史与发布包构成见根目录 `打包说明.md`。
