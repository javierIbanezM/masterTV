@echo off
rem ============================================================================
rem  Compila Android TV Master completo:
rem    1) .exe con PyInstaller (carpeta dist\AndroidTvMaster\)
rem    2) copia adb y scrcpy desde vendor\tools\ a dist\AndroidTvMaster\tools\
rem    3) ZIP portable   -> dist\AndroidTvMaster-<version>-portable.zip
rem    4) Instalador     -> dist\AndroidTvMaster-<version>-Setup.exe  (si hay Inno Setup 6)
rem ============================================================================
setlocal
cd /d "%~dp0"
set VERSION=1.4.0

python -m pip install -r requirements.txt || exit /b 1
rem Si falla alguna prueba automatica no se genera nada.
python -m unittest discover -s tests || exit /b 1
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean --windowed --name AndroidTvMaster ^
    --distpath dist --workpath build --specpath build main.py || exit /b 1

if exist vendor\tools (
    xcopy /e /i /y /q vendor\tools dist\AndroidTvMaster\tools >nul
) else (
    echo AVISO: no existe vendor\tools, el programa pedira la ruta de adb y scrcpy.
)

rem Firma opcional (ver firma\firmar.bat): se activa definiendo SIGN_PFX (y SIGN_PWD si lleva contrasena).
if defined SIGN_PFX call firma\firmar.bat dist\AndroidTvMaster\AndroidTvMaster.exe || exit /b 1

rem El antivirus suele bloquear unos segundos los ficheros recien creados: se reintenta.
powershell -NoProfile -Command "$ok=$false; foreach($i in 1..6){ try { Compress-Archive -Path 'dist\AndroidTvMaster' -DestinationPath 'dist\AndroidTvMaster-%VERSION%-portable.zip' -Force -ErrorAction Stop; $ok=$true; break } catch { Start-Sleep 4 } }; if(-not $ok){ exit 1 }"
if errorlevel 1 ( echo ERROR: no se pudo crear el ZIP portable & exit /b 1 )

set ISCC=
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" installer\AndroidTvMaster.iss || exit /b 1
) else (
    echo AVISO: Inno Setup 6 no esta instalado, se omite el instalador - jrsoftware.org/isinfo.php
)

if defined SIGN_PFX if exist dist\AndroidTvMaster-%VERSION%-Setup.exe call firma\firmar.bat dist\AndroidTvMaster-%VERSION%-Setup.exe

echo.
echo Listo. Resultados en la carpeta dist\
endlocal
