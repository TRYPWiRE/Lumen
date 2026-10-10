; Inno Setup 6.3+ script for Lumen. build.bat calls:  ISCC /DMyAppVersion=x.y.z installer\lumen.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Lumen"
#define MyAppExe "Lumen.exe"
#define MyAppMutex "LumenImageEditorMutex"

[Setup]
AppId={{8C4E2B7A-5D1F-4E8B-9A3C-2F6D7E1B4A90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=TRYPWiRE
AppPublisherURL=https://github.com/TRYPWiRE/Lumen
AppSupportURL=https://github.com/TRYPWiRE/Lumen/issues
AppUpdatesURL=https://github.com/TRYPWiRE/Lumen/releases
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
; Per-user install by default (no admin prompt, so in-app updates are seamless)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=LumenSetup-{#MyAppVersion}
SetupIconFile=..\assets\lumen.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "openwith"; Description: "Add Lumen to ""Open with"" for image files"; GroupDescription: "Integration:"

[InstallDelete]
; clear the previous build's bundled files so nothing stale survives an upgrade
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Lumen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".png"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".jpg"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".jpeg"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".bmp"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".gif"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".webp"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".tif"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".tiff"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.png\OpenWithList\{#MyAppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.jpg\OpenWithList\{#MyAppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.jpeg\OpenWithList\{#MyAppExe}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.webp\OpenWithList\{#MyAppExe}"; Flags: uninsdeletekey; Tasks: openwith

[Run]
; also runs after a silent in-app update, so Lumen reopens by itself
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall

[Code]
// Wait for a running Lumen (which launched this updater) to finish closing.
function InitializeSetup(): Boolean;
var
  Tries: Integer;
begin
  Result := True;
  Tries := 0;
  while CheckForMutexes('{#MyAppMutex}') and (Tries < 40) do
  begin
    Sleep(250);
    Tries := Tries + 1;
  end;
  while CheckForMutexes('{#MyAppMutex}') do
  begin
    if SuppressibleMsgBox('Lumen is still running.' + #13#10 + 'Please close it, then click Retry.',
                          mbError, MB_RETRYCANCEL, IDCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  if CheckForMutexes('{#MyAppMutex}') then
  begin
    MsgBox('Please close Lumen before uninstalling.', mbError, MB_OK);
    Result := False;
  end;
end;
