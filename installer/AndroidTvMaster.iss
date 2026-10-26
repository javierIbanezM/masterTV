; Instalador de Android TV Master (Inno Setup 6).
; Compilar:  ISCC.exe installer\AndroidTvMaster.iss   (o build.bat)
; Requiere haber generado antes dist\AndroidTvMaster\ con PyInstaller (build.bat).

#define AppName "Android TV Master"
#define AppVersion "1.4.0"
#define AppExe "AndroidTvMaster.exe"

[Setup]
; GUID fijo: permite que una versión nueva actualice a la anterior en vez de instalarse al lado.
AppId={{6C2B7F41-3E0A-4D55-9A6B-5C1D2E7A9B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Android TV Master
DefaultDirName={autopf}\AndroidTvMaster
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Por defecto instala solo para el usuario actual (sin pedir administrador); el asistente
; permite elegir "para todos los usuarios".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=AndroidTvMaster-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes
; No reutilizar las opciones de una instalación anterior: si alguien desmarcó el acceso directo una
; vez, las actualizaciones no deben dejarlo sin él. La casilla del escritorio sale siempre marcada.
UsePreviousTasks=no
; Los datos del usuario (%APPDATA%\AndroidTvMaster) no se tocan al desinstalar.

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
; Todo el contenido de la carpeta compilada: exe, _internal, tools\platform-tools (adb) y tools\scrcpy.
Source: "..\dist\AndroidTvMaster\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
{ Cierra el servidor de adb que dejó la aplicación en segundo plano: sigue vivo aunque se cierre la
  ventana y mantiene bloqueado tools\platform-tools\adb.exe, lo que hace fallar la actualización. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Adb, Params: String;
  Code: Integer;
begin
  Result := '';
  Adb := ExpandConstant('{app}\tools\platform-tools\adb.exe');
  if not FileExists(Adb) then Exit;
  Exec(Adb, 'kill-server', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(800);
  { Plan B: si sigue vivo, se termina solo el adb.exe de ESTA carpeta (no otros adb del equipo). }
  Params := '-NoProfile -WindowStyle Hidden -Command "Get-Process adb -ErrorAction SilentlyContinue | ' +
            'Where-Object { $_.Path -eq ''' + Adb + ''' } | Stop-Process -Force"';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_HIDE,
       ewWaitUntilTerminated, Code);
  Sleep(500);
end;

[UninstallRun]
; Cierra el servidor de adb que lance la aplicación para que no bloquee la carpeta al borrarla.
Filename: "{app}\tools\platform-tools\adb.exe"; Parameters: "kill-server"; Flags: runhidden skipifdoesntexist; RunOnceId: "AdbKill"
