; Inno Setup script for spory. Built by packaging/build.py, which passes /DAppVersion.
;
; Install:   copies the app, registers the elevated background service, optional tray at sign-in.
; Upgrade:   running a newer setup stops spory, replaces files, keeps settings, relaunches it.
; Uninstall: removes the service, restores the battery limit spory found, optionally deletes data.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: upgrades and uninstall find the existing install through it.
AppId={{6C4F2B8E-91D3-4A57-B0E6-3F8D2C71A945}
AppName=spory
AppVersion={#AppVersion}
AppVerName=spory {#AppVersion}
AppPublisher=Error0229
AppPublisherURL=https://github.com/Error0229/spory
AppSupportURL=https://github.com/Error0229/spory/issues
DefaultDirName={autopf}\spory
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=spory-setup-{#AppVersion}
SetupIconFile=spory.ico
; Shown before installing: the limit stops charging but never drains the battery.
InfoBeforeFile=notice.txt
UninstallDisplayIcon={app}\spory.exe
UninstallDisplayName=spory
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UsedUserAreasWarning=no

[Tasks]
Name: "autostart"; Description: "Start spory in the tray when I sign in"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\spory\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files from the previous version that the new one no longer ships.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\spory"; Filename: "{app}\spory.exe"
Name: "{autodesktop}\spory"; Filename: "{app}\spory.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "spory"; ValueData: """{app}\spory.exe"" --tray"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\spory.exe"; Parameters: "service install"; StatusMsg: "Starting the background service..."; \
    Flags: runhidden waituntilterminated
; Not skipped in silent mode, so in-app updates bring spory back afterwards.
Filename: "{app}\spory.exe"; Description: "Open spory"; Flags: nowait postinstall runasoriginaluser

[UninstallRun]
Filename: "{app}\spory.exe"; Parameters: "service uninstall"; Flags: runhidden waituntilterminated; \
    RunOnceId: "RemoveService"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM spory.exe"; Flags: runhidden waituntilterminated; \
    RunOnceId: "CloseTray"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  { Upgrading: stop the running service and tray app so their files can be replaced. }
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN spory', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM spory.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('Also delete your spory settings and charge history?', mbConfirmation,
              MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\spory'), True, True, True);
end;
