# CI 踩坑实录（diangetai v1.0.0 首发，2026-10-29）

> 8 轮红换来的清单。新项目搭 CI 前通读一遍，能省一半轮次。
> 结论先行：**8 轮里 3 轮是真实环境差异（必交学费），4 轮是我自己代码的坑（可避免），
> 1 轮是归因错误导致的重复（最冤）**。

## 一、真实环境差异（本机正常、CI 必挂，无法预判只能踩）

### 坑 A：pip 干净解析 vs 本机缓存
本机 venv 早就装好一切，`pip install -r` 秒过；CI 全新环境从零解析。
`--only-binary=:all:` 遇到只有 sdist 的包（本例 proxy_tools）直接拒绝。
**教训**：requirements 验证必须在**干净 venv** 里跑一遍，本机 venv 的结果不算数。

### 坑 B：git clone vs tar.gz（setuptools_scm 类包）
pywebview master 用 setuptools_scm 从 git 历史推版本号。本机是 clone 的有 .git；
CI 用 `pip install git+tar.gz` 拿到的 archive 没有 .git → 构建失败。
**教训**：凡"版本动态生成"的包（scm/hg 系），CI 里用 `git clone` + 本地路径安装。

### 坑 C：Windows Server SKU 缺桌面 API
GitHub 的 windows runner 是 **Server** 系统：没有 SMTC 媒体接口（winsdk 那行
selftest 必然 FAIL），也可能没有 WebView2。真实用户是 Win10/11，不受影响。
**教训**：自检步骤要区分"打包产物坏了"和"runner 环境先天缺"，对后者精确豁免
（只豁免具体行，别整个跳过），并写明豁免理由。

## 二、我自己写的代码坑（每一轮都本可避免）

### 坑 D：中文 print 在 cp1252 管道炸 UnicodeEncodeError（连红两轮，最冤）
`shell: python` 步骤 stdout 是重定向管道，英文 Windows 默认 cp1252，
print 中文（含中文冒号）直接抛异常退出码 1。Run#3、#4 都死在这。
**教训**：CI 里 Python 输出**一律纯 ASCII**，或显式 `PYTHONIOENCODING=utf-8`。
本机是 GBK 能编中文，所以本地测不出来——这是"本机正常 CI 挂"的镜像版本。

### 坑 E：windowed exe 的 input() 在 CI 里永远挂
`点歌台.exe --selftest` 结尾 `input("按回车退出")`；打包成无控制台程序后
stdin 是断的，桌面手动跑没事（8 秒兜底），CI 里直接卡满 4 分钟超时。
**教训**：CI 调 GUI exe 必须 `-RedirectStandardInput` 喂空输入；
并且**判定以产物文件为准**（报告在 input 之前已落盘），进程杀不杀无所谓。

### 坑 F：诊断通道放错位置 + 归因错误
"失败诊断注解"步骤一开始放在依赖安装后面——失败发生在更后面时它根本不触发。
且 Run#3 我误判成"版本断言误杀"（真凶是断言之前的中文 print），
导致 Run#4 换汤不换药又红一次。
**教训**：① 诊断/兜底步骤放 job **最末尾** + `if: failure()`；
② 第一次红了就**拿真实报错再动手**，拿不到就想办法建通道（本项目：把报错压进
`::error` 注解，`check-runs/{id}/annotations` 端点**匿名可读**——主日志要登录，
注解不要，这是给无 token 场景开的后门），别盲改。

## 三、GitHub 网络与认证（国内特有）

- 本机到 GitHub：**GET 通、push 被重置**（半通）。解法 = 本地代理 socks5 口。
- git 只对单仓库配代理：`git config http.proxy socks5h://127.0.0.1:PORT`
  （仓库级，不污染全局）。
- 匿名 API 限额 60 次/小时，轮询 CI 别快于 1 次/分钟；超限 403 只能等。
- 首次 push 弹 Git Credential Manager：选 **manager** + 勾 always，浏览器授权一次
  永久免密。GCM 存的 OAuth token 默认**没有 actions scope** → 拉不了日志正文，
  这就是上面"注解通道"存在的理由。

## 四、可复用的新项目 CI 清单

1. 先写一个**永远运行**的 `echo hello` workflow，确认 Actions 能跑、通知能收
2. 装依赖步骤：干净 venv 本地预演 + 失败时 `type` 全量日志 + 注解回传
3. 所有 Python 步骤默认 `PYTHONIOENCODING=utf-8`，或干脆不 print 非 ASCII
4. 调 GUI exe：喂空 stdin、带超时、以产物文件判定
5. 环境差异项（Server SKU、缺驱动、缺运行时）精确豁免 + 注释理由
6. 版本单一来源文件 + CI 里 tag↔文件一致性校验
7. 诊断步骤放最后 `if: failure()`，把关键日志尾部压成单行注解
