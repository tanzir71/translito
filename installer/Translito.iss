#define MyAppName "Translito"
#define MyAppExeName "Translito.exe"
#define MyAppVersion "1.1.3"
#ifndef SourceDir
  #define SourceDir "dist\Translito"
#endif

#ifndef OutputDir
  #define OutputDir "output"
#endif

[Setup]
AppId={{7B302C7E-747D-4D88-9B10-3A75A974321E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Translito
DefaultDirName={autopf}\Translito
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=TranslitoSetup-{#MyAppVersion}
SetupIconFile=Translito.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
ArchiveExtraction=full
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "startup"; Description: "Open at login"; Flags: unchecked
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "virtualmic"; Description: "Install virtual microphone for Speak Mode (VB-CABLE by VB-Audio, donationware)"; GroupDescription: "Optional audio driver:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "redist\vbcable\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "redist\vbcable\*"; DestDir: "{app}\redist\vbcable"; Flags: ignoreversion
Source: "vbcable.sha256"; DestDir: "{app}\redist\vbcable"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "https://vb-audio.com/Services/licensing.htm"; Description: "Support VB-Audio / donate for VB-CABLE"; Flags: shellexec postinstall skipifsilent unchecked

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Translito"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: startup; Flags: uninsdeletevalue

[Code]
const
  VBCableHash = 'b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb';
  VBCableSetupHash = '734c35dfa6d98f48782a451633ceb471166ec70d60482fd89a1123d0ee3c4f41';

var
  ArchivedRuntime, OriginalRuntime: String;
  InstallFilesDone: Boolean;

function GetFileAttributesW(FileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

procedure CheckNormalDirectory(Path: String);
begin
  if (GetFileAttributesW(Path) and $400) <> 0 then
    RaiseException('The runtime upgrade will not move a linked directory. Choose a normal Translito installation folder.');
end;

procedure ArchivePreviousRuntime;
var
  AppPrefix, RuntimeDir, HistoryDir, BackupBase, BackupDir: String;
  Suffix: Integer;
begin
  if ArchivedRuntime <> '' then
    Exit;
  AppPrefix := AddBackslash(ExpandFileName(ExpandConstant('{app}')));
  RuntimeDir := ExpandFileName(AppPrefix + '_internal');
  if not DirExists(RuntimeDir) then
    Exit;
  HistoryDir := ExpandFileName(AppPrefix + 'runtime-history');
  BackupBase := HistoryDir + '\' + GetDateTimeString('yyyymmdd-hhnnss', '-', '-');
  BackupDir := ExpandFileName(BackupBase);
  Suffix := 0;
  while DirExists(BackupDir) or FileExists(BackupDir) do
  begin
    Suffix := Suffix + 1;
    BackupDir := ExpandFileName(BackupBase + '-' + IntToStr(Suffix));
  end;
  { Verify both absolute move targets remain inside the chosen app folder. }
  if (CompareText(Copy(RuntimeDir, 1, Length(AppPrefix)), AppPrefix) <> 0) or
     (CompareText(Copy(BackupDir, 1, Length(AppPrefix)), AppPrefix) <> 0) then
    RaiseException('The runtime archive path is outside the installation folder.');
  CheckNormalDirectory(RemoveBackslashUnlessRoot(AppPrefix));
  CheckNormalDirectory(RuntimeDir);
  if DirExists(HistoryDir) then
    CheckNormalDirectory(HistoryDir);
  if not ForceDirectories(HistoryDir) then
    RaiseException('Unable to create the runtime backup folder. The previous runtime was preserved.');
  CheckNormalDirectory(HistoryDir);
  if not RenameFile(RuntimeDir, BackupDir) then
    RaiseException('Close Translito and try the upgrade again. The previous runtime was preserved.');
  OriginalRuntime := RuntimeDir;
  ArchivedRuntime := BackupDir;
  Log('Archived the previous runtime at ' + BackupDir);
end;

procedure InstallVirtualMic;
var
  ArchivePath, DriverDir, DriverExe: String;
  ErrorCode: Integer;
begin
  if WizardSilent or not WizardIsTaskSelected('virtualmic') then
    Exit;
  if MsgBox('Install VB-CABLE by VB-Audio for Speak Mode?' + #13#10#13#10 +
    'VB-CABLE is donationware. Origin: https://vb-audio.com/Cable/' + #13#10 +
    'Donate / licensing: https://vb-audio.com/Services/licensing.htm' + #13#10#13#10 +
    'Review the included vendor license in redist\vbcable\VBCABLE_Driver_Pack45.zip before continuing.' + #13#10 +
    'Only the driver installer will ask for administrator permission. Windows may also show its driver-publisher prompt. A restart may be needed.' + #13#10#13#10 +
    'Install the optional driver now?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;
  try
    ArchivePath := ExpandConstant('{app}\redist\vbcable\VBCABLE_Driver_Pack45.zip');
    if Lowercase(GetSHA256OfFile(ArchivePath)) <> VBCableHash then
      RaiseException('VB-CABLE package verification failed. The driver was not started.');
    DriverDir := ExpandConstant('{tmp}\vbcable');
    ForceDirectories(DriverDir);
    ExtractArchive(ArchivePath, DriverDir, '', True, nil);
    DriverExe := DriverDir + '\VBCABLE_Setup_x64.exe';
    if Lowercase(GetSHA256OfFile(DriverExe)) <> VBCableSetupHash then
      RaiseException('VB-CABLE setup verification failed. The driver was not started.');
    if not ShellExec('runas', DriverExe, '-i -h', DriverDir, SW_SHOWNORMAL, ewWaitUntilTerminated, ErrorCode) then
      MsgBox('Windows cancelled or could not start the optional VB-CABLE installer. Translito is installed; use Speak setup to try again.', mbInformation, MB_OK)
    else
      MsgBox('VB-CABLE setup has finished. If CABLE Input / CABLE Output are missing, restart Windows to finish installation. Then open Speak Mode and run Test virtual mic.', mbInformation, MB_OK);
  except
    MsgBox(GetExceptionMessage, mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    ArchivePreviousRuntime;
  if CurStep = ssPostInstall then
  begin
    InstallFilesDone := True;
    InstallVirtualMic;
  end;
end;

procedure DeinitializeSetup;
begin
  { Restore only when no replacement directory was created. Partial replacements
    and every previous runtime remain available rather than being deleted. }
  if (not InstallFilesDone) and (ArchivedRuntime <> '') and
     DirExists(ArchivedRuntime) and (not DirExists(OriginalRuntime)) then
    if RenameFile(ArchivedRuntime, OriginalRuntime) then
      Log('Restored the previous runtime after an interrupted installation.');
end;
