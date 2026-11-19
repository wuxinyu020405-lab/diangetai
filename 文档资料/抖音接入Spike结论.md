# 抖音弹幕接入 Spike 结论（2026-11-04，阶段①完成）

> 目标验证：**Python 端匿名接入抖音直播间收弹幕，全链路可行** ✅
> 实测证据：45 秒收到 85 条消息，含真实弹幕 2 条（"主播普通话不包准呀"）。
> 参考配方：DanmuFree（SoraYjy/DanmuFree）的 DouyinSign.cs + sign_runner.js。

## 打通的完整链路（5 步）

```
① GET live.douyin.com/           → 拿 ttwid cookie（匿名即可）
② feed 接口（带 X-Bogus 签名）    → 拿在播房间 room_id 列表
③ 构造 WS URL（13 字段 stub → MD5 → node 跑 sign.js 得 X-Bogus）
④ IP 直连 443 裸 socket 手写 WS 握手 → HTTP 101 Switching Protocols
⑤ 收帧 → gzip 解压 → 手写 protobuf 解析 → WebcastChatMessage = 弹幕
   （+ 9s 业务心跳 PushFrame{f8=gzip(空)}、+ ack 回写 internal_ext）
```

## 三个实测踩出来的关键坑（正式实现必须遵守）

1. **本地透明代理会劫持抖音 WS**：UniClash 按域名拦截，返回 502（带 `Proxy-Status` 头，
   极易误判为"抖音拒绝"）。**必须绕过代理直连 IP**（`socket.create_connection((ip,443))`
   + SNI 域名）。抖音是国内站，本来就该直连——正式实现里所有抖音请求都要显式禁代理。

2. **DEVICE_BLOCKED 的解药是完整参数**：只给基础参数会被 `Handshake-Msg: DEVICE_BLOCKED (415)`
   拒掉。必须带全 DanmuFree 配方：`did_rule=3`、`identity=audience`、`version_code=180800`、
   `webcast_sdk_version=1.3.0`、`cursor=d-1_u-1`、`internal_ext`（含 room_id/did）、
   `support_wrds=1`、`need_persist_msg_count=15`。签名参数名用 `signature=`（不是 X-Bogus=）。

3. **HTTP 头之后的字节是第一个 WS 帧**：裸 socket 读握手时一次读多了会把帧头丢掉，
   必须用带缓冲的读取器（Buf 类），帧边界从缓冲继续解析。

## 法律姿态（已定）

- `sign.js`（473KB，webmssdk 反混淆产物，版权归字节）**不进仓库**（.gitignore 已挡），
  与 DanmuFree 同做法；用户按文档自行获取。
- 仓库内只放 `sign_runner.js`（调用壳，30 行，无版权风险）+ package.json（jsdom 依赖声明）。
- README/文档需注明：抖音接口非官方、签名 JS 属字节、仅个人学习用途。

## 依赖与环境

- node（本机 v26 已有；打包分发方案在阶段④定：内置 node.exe vs 复用已有 WebView2）
- jsdom（sign.js 的补环境，npm 装一次）
- Python 侧零新依赖（socket/ssl/gzip/hashlib 全标准库；protobuf 手写解析 ~40 行）

## 保留的 spike 文件（阶段②的活教材）

| 文件 | 作用 |
|---|---|
| `_spike_douyin_feed.py` | ②：签名调 feed 拿在播房间列表 |
| `_spike_douyin_ws2.py` | ③④⑤：完整 WS 收弹幕闭环（含 protobuf 解析/心跳/ack） |
| `douyin_sign/sign_runner.js` | 签名调用壳（node sign_runner.js <md5> → X-Bogus） |
| `douyin_sign/sign.js` | webmssdk 反混淆产物（**不入库**，本地留存） |

## 下一步（阶段②：live_providers 抽象层）

1. 新建 `点歌台拆分/live_providers/`：`base.py`（接口：connect/disconnect/on_message 事件）
2. `bilibili.py`：现有 blivedm 逻辑平移（行为不变，回归护航）
3. `douyin.py`：spike 代码产品化——长连接保活重连（指数退避）、弹幕→现有
   `BiliHandler` 同款指令解析（点歌/切歌/暂停）、昵称/内容字段对齐
4. mainapp 同时起两路 provider，`pending_requests` 汇流；config 加 `douyin_room_id`
5. GUI 账号页加抖音房间号输入 + 连接状态灯；OBS 队列显示来源平台角标
6. 每步跑 `_gui_smoke.py` + 现有回归；最后真直播间双平台同测

## 风险登记

- 抖音签名算法会随 webmssdk 版本更新失效（DanmuFree 同款风险）→ 换 sign.js 文件即可，
  代码不动；关注 saermart/DouyinLiveWebFetcher 更新
- 匿名设备风控可能收紧（DEVICE_BLOCKED 变体）→ 心跳/重连策略要像 DanmuFree 一样带日志
- 打包体积：内置 node.exe ~80MB（阶段④权衡 WebView2 方案可省）
