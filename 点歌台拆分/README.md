# 扫码点歌台（拆分版）

由单文件 `扫码点歌台_优化首次成功_4.py`（2170 行）按子系统拆成 10 个模块。
**纯搬家**：逻辑、算法、文案、HTML 模板、注释全部逐字保留，未修复任何已知缺陷。

## 运行

```powershell
cd D:\点歌台干活处
.\.venv\Scripts\Activate.ps1
python 点歌台拆分\main.py
```

配置文件仍读 `点歌台拆分\config.json`、`点歌台拆分\credential.json`（相对各模块所在目录）。
若要复用现有配置，把 `D:\点歌台干活处\config.json`、`credential.json`、`music_cache\`
放到 `main.py` 同级目录，或改 `settings.py` 里的 `BASE_DIR`。

## 模块划分

| 文件 | 职责 | 原行号 |
| --- | --- | --- |
| `main.py` | 程序入口 | 2159–2171 |
| `mainapp.py` | `MusicApp`：tkinter 控制台 + asyncio worker 编排 | 1266–2113 |
| `danmaku.py` | `BiliHandler`、`search_and_add`：弹幕指令解析与入队 | 2115–2156 |
| `overlay.py` | OBS 浏览器源：HTML 模板 + `/`、`/api/data` 路由 | 784–1263 |
| `musiclib.py` | QQ 音乐取址/音质枚举探测、缓存文件管理、搜索/URL 解析 | 191–410 等 |
| `smtc.py` | 从 QQ 音乐窗口标题兜底读取正在播放 | 448–475 |
| `browserlogin.py` | Selenium 扫码登录 B 站 / QQ 音乐 | 516–762 |
| `settings.py` | 路径/配置合并/音质映射表/凭据存取/客户端探测 | 59–182 等 |
| `lyrics.py` | LRC 解析、歌词窗口计算 | 411–446 |
| `state.py` | 15 个跨模块运行时状态 | 81–189 |

## 关键改动：全局状态访问方式

原文件用模块级 `global`，拆成多文件后 `from state import x` 只是值快照，
对被整体重新赋值的变量（`current_song = None` 等）不会回传。因此所有跨模块引用
改为**属性访问** `state.xxx` / `settings.xxx` / `musiclib.xxx`：

```python
# 原
global current_song; current_song = playlist.pop(0)
# 拆分后
state.current_song = state.playlist.pop(0)
```

残留的 `global` 声明是原代码文本的一部分（纯搬家未删），现已是无害装饰——真正的读写都走 `state.`。

## 验证（四道，均通过）

1. **AST 等价**：把 `state.`/`settings.` 等前缀还原后，25 个函数/类 + 24 个顶层常量与原文件逐个 AST 一致；HTML 模板 18708 字节逐字节相同 → 证明逻辑零改动。
2. **静态 lint**：10 个文件无任何"裸引用跨模块名"，排除 import 期/调用期 NameError。
3. **行为烟测**：跨模块赋值→读取可见、`skip_event` set/clear、歌词链路、OBS 服务真实起停、全模块导入。
4. **真实启动对比**：原版与拆分版同条件各起一个隔离进程，`/api/data` 的 5 个字段、`style`(1088 字节)、HTML(sha256 相同) 全部逐项相等。

## 未做的事

- 未修复审阅报告里任何缺陷（音质 Hi-Res 失效、XSS、BGM 不恢复等原样保留）。
- 未改文件名/日志文案；`import ply/jsonpath_ng`（PyInstaller hiddenimports 所需）与两处未使用的 `subprocess/urllib.parse` 按"纯搬家"原则保留，均加了注释。
- 未做端到端联网测试（连真实直播间/下载真实歌曲），需要有效凭据与桌面音频环境，由你在本机跑 `main.py` 验证。

## 打包提示

原 `.spec` 入口从 `扫码点歌台_优化首次成功.py` 改为 `点歌台拆分\main.py`，
`hiddenimports` 里的 `ply/jsonpath_ng/pygame` 保持不变，并新增对 `mainapp/danmaku/overlay/musiclib/settings/state/lyrics/smtc/browserlogin` 的收集（PyInstaller 一般能自动跟进，若漏则加入 hiddenimports）。
