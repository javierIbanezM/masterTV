@echo off
rem ============================================================================
rem  Firma un ejecutable con signtool (Windows SDK).
rem  Uso:   firma\firmar.bat  ruta\al\archivo.exe
rem
rem  Variables de entorno (no se pasan por la linea de comandos para no dejar la
rem  contrasena en el historial):
rem    SIGN_PFX   ruta del certificado .pfx                      (obligatoria)
rem    SIGN_PWD   contrasena del .pfx                            (si la tiene)
rem    SIGN_TS    URL del servidor de sellado de tiempo; "none" para no usar
rem               (por defecto http://timestamp.digicert.com)
rem
rem  Con certificado propio (autofirmado, ver crear_certificado_interno.ps1) la
rem  firma es valida solo en los PC que confien en ese certificado. Para que
rem  Windows SmartScreen no avise en cualquier PC hace falta un certificado de
rem  firma de codigo emitido por una autoridad reconocida (OV/EV).
rem ============================================================================
setlocal
if "%~1"=="" ( echo Uso: firmar.bat archivo.exe & exit /b 2 )
if not defined SIGN_PFX ( echo Falta la variable SIGN_PFX con la ruta del .pfx & exit /b 2 )
if not exist "%SIGN_PFX%" ( echo No existe el certificado: %SIGN_PFX% & exit /b 2 )

set SIGNTOOL=
for /f "delims=" %%F in ('dir /b /s "%ProgramFiles(x86)%\Windows Kits\10\bin\signtool.exe" 2^>nul ^| findstr /i "\\x64\\"') do set "SIGNTOOL=%%F"
if not defined SIGNTOOL for /f "delims=" %%F in ('where signtool 2^>nul') do set "SIGNTOOL=%%F"
if not defined SIGNTOOL ( echo No se encuentra signtool.exe ^(instala el Windows SDK^) & exit /b 2 )

if not defined SIGN_TS set SIGN_TS=http://timestamp.digicert.com
set TSARGS=/tr %SIGN_TS% /td sha256
if /i "%SIGN_TS%"=="none" set TSARGS=

set PWDARGS=
if defined SIGN_PWD set PWDARGS=/p "%SIGN_PWD%"

"%SIGNTOOL%" sign /fd sha256 %TSARGS% /f "%SIGN_PFX%" %PWDARGS% /d "Android TV Master" "%~1" || exit /b 1
"%SIGNTOOL%" verify /pa "%~1" >nul 2>&1
if errorlevel 1 (
    echo Firmado. Aviso: Windows no confia en este certificado en este PC ^(normal si es autofirmado^).
) else (
    echo Firmado y verificado correctamente: %~1
)
endlocal
