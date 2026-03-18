; Tequila v2 — Inno Setup installer script (Sprint 15 §29.4)
;
; Build with:
;   iscc build\installer.iss
;
; Output: build\output\TequilaSetup-<version>.exe

#define MyAppName      "Tequila"
#define MyAppVersion   "0.1.0"
#define MyAppPublisher "Tequila"
#define MyAppURL       "https://github.com/tequila-ai/tequila"
#define MyAppExeName   "tequila.exe"
#define MyBundleDir    "..\dist\tequila"

[Setup]
AppId={{8B3F7C2A-4E6D-4A9B-B2C1-1F3D5E7A9C0E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=TequilaSetup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\frontend\public\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; Keep user data on uninstall by default (prompt on finish)
CreateUninstallRegKey=yes
; Minimum Windows 10
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";   Description: "{cm:CreateDesktopIcon}";   GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupentry";  Description: "Start Tequila automatically when Windows starts";  GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Main application bundle (entire dist\tequila\ directory)
Source: "{#MyBundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}";    Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";      Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Optional startup entry
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startupentry

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop any running Tequila process before uninstallation
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillTequila"

[UninstallDelete]
; Remove the data directory only if user confirms (handled by custom page below).
; By default we leave data in place.

[Code]
var
  DataDirPage: TInputOptionWizardPage;

procedure InitializeWizard;
begin
  // No custom wizard pages needed for basic installer
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath: string;
  KeepData: Boolean;
begin
  if CurUninstallStep = usUninstall then begin
    DataPath := ExpandConstant('{localappdata}\{#MyAppName}');
    // Ask whether to delete user data
    KeepData := MsgBox(
      'Would you like to keep your Tequila data (sessions, memories, backups)?'
      + #13#10 + DataPath
      + #13#10#13#10 + 'Click Yes to keep your data, No to delete it.',
      mbConfirmation,
      MB_YESNO
    ) = IDYES;

    if not KeepData then begin
      DelTree(DataPath, True, True, True);
    end;
  end;
end;
