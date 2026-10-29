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

[Languages]
; 语言包随仓库固定（官方 Inno 不带简体中文，这份取自 jrsoftware/issrc Unofficial）
Name: "chinesesimplified"; MessagesFile: "installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
; PyInstaller onedir 产物整体打入（排除运行残留）
Source: "dist\点歌台\*"; DestDir: "{app}"; Excludes: "自检报告.txt,debug.log,_st.log,music_cache\*,config.json,credential.json,quota_state.json,启动日志.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
; music_cache 空目录由程序自建，安装包不预置

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
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
