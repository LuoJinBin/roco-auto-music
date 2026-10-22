; Compile using Inno Setup ISCC. Never installs the Interception system driver.
#ifndef PayloadDir
  #error PayloadDir must point to the prepared release payload directory
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef AppVersion
  #define AppVersion "1.2.0-alpha.1"
#endif

[Setup]
AppId={{A0B340A8-9DB2-46A8-A3CD-E5A917C3890D}
AppName=洛克自动奏乐
AppVersion={#AppVersion}
AppPublisher=Roco Auto Music contributors
AppPublisherURL=https://github.com/LuoJinBin/roco-auto-music
AppSupportURL=https://github.com/LuoJinBin/roco-auto-music/issues
DefaultDirName={localappdata}\Programs\RocoAutoMusic
DefaultGroupName=洛克自动奏乐
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=RocoAutoMusic-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile={#PayloadDir}\LICENSE
InfoBeforeFile={#PayloadDir}\安装前说明.txt
UninstallDisplayIcon={app}\RocoAutoMusic.exe
CloseApplications=no
RestartApplications=no
Uninstallable=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\洛克自动奏乐"; Filename: "{app}\RocoAutoMusic.exe"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.md"
Name: "{autodesktop}\洛克自动奏乐"; Filename: "{app}\RocoAutoMusic.exe"; Tasks: desktopicon

; Intentionally no [Run] section: installing never starts music, installs a
; system driver, or restarts Windows. Uninstall removes application files only;
; user cache/log data and separately installed drivers are left unchanged.
