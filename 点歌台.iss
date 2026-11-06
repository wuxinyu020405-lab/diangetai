; 扫码点歌台 Inno Setup 安装包脚本
; 用法（本机或 CI，先跑 PyInstaller 产出 dist\点歌台\）：
;   ISCC.exe /DMyAppVersion=1.0.0 点歌台.iss
; 版本号的唯一来源是 点歌台拆分\version.py，CI 会解析它传进来。

#define MyAppName      "扫码点歌台"
#define MyAppExeName   "点歌台.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
; 固定 AppId：升级安装时靠它认出是同一个应用（切勿更改）
AppId={{7E1F4B08-9C2D-4A6E-B3F0-5D2A8C4E6F11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=点歌台开源项目
DefaultDirName={localappdata}\Programs\DianGeTai
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_out
OutputBaseFilename=diangetai-Setup-v{#MyAppVersion}
SetupIconFile=点歌台拆分\app.ico
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 按用户安装（lowest）：免 UAC，装到 %LOCALAPPDATA%\Programs\DianGeTai。
; 关键原因：程序要在 exe 同目录写 config.json / credential.json / music_cache，
; 装进 Program Files 普通权限根本写不进去 —— 必须用户目录。
PrivilegesRequired=lowest
LicenseFile=LICENSE

; ── v1.2.5 修复 ────────────────────────────────────────────────────────
; ① 升级时也能选安装目录：Inno 的 DisableDirPage 默认是 auto —— 检测到已安装
;    就**隐藏**目录页、直接沿上次路径覆盖。用户实测"想换目录根本没得选"。
;    显式置 no：目录页永远出现（默认值仍是上次的目录，回车即可，不打扰习惯）。
DisableDirPage=no
; ② 关掉 Restart Manager 的"关窗口"机制。它会向程序发 WM_CLOSE，而本程序把
;    WM_CLOSE 绑成了"缩到托盘"，结果就是 v1.2.4 实测的：GUI 关了、进程还活着、
;    文件被占用、装不进去。退出统一交给下面 [Code] 的 PrepareToInstall。
;    同时不设 AppMutex：那会让 Setup 在启动时弹"请先关闭应用"并卡住，
;    而我们要的是**自动**退出，不需要用户点。
CloseApplications=no
RestartApplications=no

[Languages]
; 语言包随仓库固定（官方 Inno 不带简体中文，这份取自 jrsoftware/issrc Unofficial）
Name: "chinesesimplified"; MessagesFile: "installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
; PyInstaller onedir 产物整体打入（排除运行残留）
Source: "dist\点歌台\*"; DestDir: "{app}"; Excludes: "自检报告.txt,debug.log,_st.log,music_cache\*,config.json,credential.json,quota_state.json,启动日志.txt,更新日志.txt,_update_pending.json,_update_dl\*,_update_staging\*"; Flags: ignoreversion recursesubdirs createallsubdirs
; music_cache 空目录由程序自建，安装包不预置
; 使用说明.md 由 spec 复制进 dist\点歌台\ 根，随上面通配进包（v1.2.1 需求20）

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
; v1.2.1·需求20：装完第一眼就能找到说明（开始菜单必有；勾桌面图标时桌面也放）
Name: "{group}\使用说明"; Filename: "{app}\使用说明.md"
Name: "{autodesktop}\使用说明"; Filename: "{app}\使用说明.md"; Tasks: desktopicon
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清掉运行期在程序目录生成的用户数据（凭据！公开版必须删干净）
Type: filesandordirs; Name: "{app}\music_cache"
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\credential.json"
Type: files; Name: "{app}\quota_state.json"
Type: files; Name: "{app}\启动日志.txt"
Type: files; Name: "{app}\自检报告.txt"
Type: files; Name: "{app}\更新日志.txt"
Type: files; Name: "{app}\_update_pending.json"
Type: filesandordirs; Name: "{app}\_update_dl"
Type: filesandordirs; Name: "{app}\_update_staging"

[Code]
{ ── v1.2.5：安装前把"已运行的点歌台"彻底请出去 ──────────────────────
  为什么不用 AppMutex / Restart Manager：
  1) AppMutex 只会在 Setup 启动时弹"应用正在运行，请关闭"，把活甩给用户；
  2) Restart Manager 发的是 WM_CLOSE，而本程序把 WM_CLOSE 绑成"缩托盘"，
     结果是 GUI 消失、进程仍在、DLL 被占用 —— 这正是 v1.2.4 实测的怪象。
  所以这里自己动手，两条腿走路：
    a. 新版有命名退出事件（Local\DianGeTai_Quit_v1）→ 置位，程序自己落盘后退出；
    b. 旧版没有这个通道（1.2.4 及以前）→ 等不到就 taskkill 强制结束
       （配置/歌单是即时落盘的，强杀不会丢数据）。
  名字必须与 点歌台拆分\state.py 里的 APP_MUTEX_NAME / QUIT_EVENT_NAME 逐字一致。}

const
  QuitEventName = 'Local\DianGeTai_Quit_v1';
  AppMutexName  = 'Local\DianGeTai_SingleInstance_v1';
  EVENT_MODIFY_STATE = $0002;
  SYNCHRONIZE = $00100000;

function OpenEventW(dwDesiredAccess: Cardinal; bInheritHandle: Boolean;
  lpName: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(hEvent: THandle): Boolean;
  external 'SetEvent@kernel32.dll stdcall';
function OpenMutexW(dwDesiredAccess: Cardinal; bInheritHandle: Boolean;
  lpName: String): THandle;
  external 'OpenMutexW@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

{ 单实例互斥体还在 = 进程还活着（比找窗口标题可靠，托盘隐藏时也能查到） }
function AppIsRunning(): Boolean;
var
  H: THandle;
begin
  Result := False;
  H := OpenMutexW(SYNCHRONIZE, False, AppMutexName);
  if H <> 0 then
  begin
    Result := True;
    CloseHandle(H);
  end;
end;

{ 给新版发"优雅退出"信号；事件不存在（旧版/没在跑）时静默返回 }
procedure RequestGracefulQuit();
var
  H: THandle;
begin
  H := OpenEventW(EVENT_MODIFY_STATE, False, QuitEventName);
  if H <> 0 then
  begin
    SetEvent(H);
    CloseHandle(H);
  end;
end;

{ 兜底：结束进程树（子进程 node/ffmpeg 之类一起清），先温和再强杀 }
procedure KillAppProcesses();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM "{#MyAppExeName}" /T', '',
       SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1500);
  if AppIsRunning() then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM "{#MyAppExeName}"', '',
         SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ PrepareToInstall：选完安装目录、真正开始写文件之前调用，此时安装目录已确定。
  返回非空字符串 = 中止安装并把它作为提示文案。 }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I: Integer;
begin
  Result := '';
  NeedsRestart := False;
  if not AppIsRunning() then
    Exit;                                  { 没在跑（含首次安装）→ 什么都不做 }

  RequestGracefulQuit();                   { 新版：落盘 → 停托盘 → 退干净 }
  for I := 1 to 60 do                      { 最多等 15 秒 }
  begin
    if not AppIsRunning() then
      Break;
    Sleep(250);
  end;

  if AppIsRunning() then
  begin
    KillAppProcesses();                    { 旧版无通道 / 卡死 → 强制结束 }
    for I := 1 to 20 do
    begin
      if not AppIsRunning() then
        Break;
      Sleep(250);
    end;
  end;

  if AppIsRunning() then
    Result := '检测到点歌台仍在运行且无法自动退出。' + #13#10 +
              '请右键任务栏托盘里的点歌台图标，选择「退出点歌台」，然后回来点「重试」。';
end;

