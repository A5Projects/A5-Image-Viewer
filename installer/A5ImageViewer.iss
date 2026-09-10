#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "A5ImageViewer"
#define MyAppExeName "A5ImageViewer.exe"
#define MyAppProgId "A5ImageViewer.Image"

[Setup]
AppId={{E66D1E97-574B-4A34-B487-5654FD24978E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={localappdata}\Programs\{#MyAppName}
AppendDefaultDirName=no
DefaultGroupName={#MyAppName}
UsePreviousAppDir=yes
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\output_exe
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
SetupIconFile=..\A5ImageViewer.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} Installer

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "windowsintegration"; Description: "Register A5ImageViewer for supported image formats"; GroupDescription: "Windows integration:"; Flags: checkedonce
Name: "windowsintegration\defaultsettings"; Description: "Open Windows Default Apps after installation"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{app}\{#MyAppExeName}"
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "staging\A5ImageViewer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}"; ValueType: string; ValueName: ""; ValueData: "Image file"; Flags: uninsdeletekey; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: windowsintegration

Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: windowsintegration

Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Fast image viewing and basic editing"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\{#MyAppExeName},0"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\A5ImageViewer\Capabilities"; Flags: uninsdeletevalue; Tasks: windowsintegration

Root: HKCU; Subkey: "Software\Classes\.jpg\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\.jpeg\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\.png\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\.bmp\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\.webp\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\.gif\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\.tif\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\.tiff\OpenWithProgids"; ValueType: none; ValueName: "{#MyAppProgId}"; Flags: uninsdeletevalue; Tasks: windowsintegration

Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".jpg"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".jpeg"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".png"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".bmp"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".webp"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".gif"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".tif"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: none; ValueName: ".tiff"; Tasks: windowsintegration

Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpg"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpeg"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".png"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".bmp"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".webp"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".gif"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tif"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration
Root: HKCU; Subkey: "Software\A5ImageViewer\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tiff"; ValueData: "{#MyAppProgId}"; Tasks: windowsintegration

[Run]
Filename: "ms-settings:defaultapps?registeredAppUser=A5ImageViewer"; Description: "Choose A5ImageViewer default formats"; Flags: shellexec postinstall skipifsilent; Tasks: windowsintegration\defaultsettings
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure RemoveRegistration;
begin
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\A5ImageViewer.Image');
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\Applications\A5ImageViewer.exe');
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\A5ImageViewer\Capabilities');
  RegDeleteValue(HKCU, 'Software\RegisteredApplications', 'A5ImageViewer');
  RegDeleteValue(HKCU, 'Software\Classes\.jpg\OpenWithProgids', 'A5ImageViewer.Image');
  RegDeleteValue(HKCU, 'Software\Classes\.jpeg\OpenWithProgids', 'A5ImageViewer.Image');
  RegDeleteValue(HKCU, 'Software\Classes\.png\OpenWithProgids', 'A5ImageViewer.Image');
  RegDeleteValue(HKCU, 'Software\Classes\.bmp\OpenWithProgids', 'A5ImageViewer.Image');
  RegDeleteValue(HKCU, 'Software\Classes\.webp\OpenWithProgids', 'A5ImageViewer.Image');
  RegDeleteValue(HKCU, 'Software\Classes\.gif\OpenWithProgids', 'A5ImageViewer.Image');
  RegDeleteValue(HKCU, 'Software\Classes\.tif\OpenWithProgids', 'A5ImageViewer.Image');
  RegDeleteValue(HKCU, 'Software\Classes\.tiff\OpenWithProgids', 'A5ImageViewer.Image');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and
     (not WizardIsTaskSelected('windowsintegration')) then
    RemoveRegistration;
end;
