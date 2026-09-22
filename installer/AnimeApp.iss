; Установщик AnimeApp для Windows (Inno Setup 6).
; Сборка: build_installer.bat (сначала PyInstaller, потом этот скрипт).

#define AppName "AnimeApp"
#define AppVersion "1.5.6"
#define AppExe "AnimeApp.exe"

[Setup]
AppId={{6B0E9C1D-5A4B-4F7E-9C3A-2D8E1F0A7B61}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AnimeApp
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Ставится без прав администратора — только для текущего пользователя
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=AnimeApp-Setup-{#AppVersion}
SetupIconFile=..\anime_app\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AnimeApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ Плеер Kodik работает на Microsoft Edge WebView2. В Windows 11 он есть всегда, в Windows 10 — почти всегда. }
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not WebView2Installed()) then
    MsgBox('Для озвучек через плеер Kodik нужен компонент Microsoft Edge WebView2.' + #13#10 +
           'Скачать бесплатно: https://go.microsoft.com/fwlink/p/?LinkId=2124703' + #13#10 +
           'Остальные функции работают и без него.', mbInformation, MB_OK);
end;
