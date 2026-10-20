#define AppName "SampleApp"
#define AppVersion "1.1.0"
#define AppPublisher "Anildarga"

[Setup]
AppId={{04A866A7-D729-4C34-BF3A-9D5E132D37A8}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=SampleApp-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
Uninstallable=yes

[Files]
Source: "dist-modern\SampleApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\SampleApp.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SampleApp.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\SampleApp.exe"; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent
