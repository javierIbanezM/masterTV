# Compila ADB Keeper (AdbKeeper.apk) sin Gradle, con las herramientas del Android SDK y un JDK.
#
#   powershell -ExecutionPolicy Bypass -File helper_apk\build_helper.ps1
#
# Requiere: Android SDK (build-tools + una plataforma con android.jar) y JDK 11 o superior.
# Salida: helper_apk\AdbKeeper.apk  y una copia en vendor\tools\helper\ (se empaqueta con el programa).
# La clave de firma se crea la primera vez en helper_apk\keystore\ (NO se sube al repositorio): hay que
# conservarla, porque Android solo actualiza una app si la nueva version esta firmada con la misma clave.
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { "$env:LOCALAPPDATA\Android\Sdk" }
if (-not (Test-Path $sdk)) { throw "No se encuentra el Android SDK en $sdk (define ANDROID_HOME)" }

# Ultima version de build-tools y plataforma disponibles ("36" o "36.1" no son versiones validas por si solas: se rellenan)
function ToVersion($text) {
    $p = @(($text -replace '[^0-9.]', '').Trim('.').Split('.'))
    while ($p.Count -lt 3) { $p += '0' }
    [version]($p[0..2] -join '.')
}
$bt = Get-ChildItem "$sdk\build-tools" -Directory | Sort-Object { ToVersion $_.Name } -Descending | Select-Object -First 1
$plat = Get-ChildItem "$sdk\platforms" -Directory | Where-Object { Test-Path "$($_.FullName)\android.jar" } |
        Sort-Object { ToVersion ($_.Name -replace 'android-', '') } -Descending | Select-Object -First 1
if (-not $bt -or -not $plat) { throw "Faltan build-tools o plataformas en el SDK" }
$androidJar = "$($plat.FullName)\android.jar"
"build-tools $($bt.Name) | plataforma $($plat.Name)"

# JDK (necesita javac y keytool)
$jdk = @($env:JAVA_HOME, "$env:ProgramFiles\Java\latest", (Get-ChildItem "$env:ProgramFiles\Java" -Directory -Filter "jdk-*" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName)) |
       Where-Object { $_ -and (Test-Path "$_\bin\javac.exe") } | Select-Object -First 1
if (-not $jdk) { $jdk = Split-Path (Split-Path (Get-Command javac -ErrorAction Stop).Source) }
$env:JAVA_HOME = $jdk; $env:PATH = "$jdk\bin;$env:PATH"
"JDK: $jdk"

$out = "$here\out"; Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$out\classes", "$out\dex" | Out-Null

# 1) Java -> .class (nivel 8: lo que entiende d8) -> classes.dex
$src = Get-ChildItem "$here\src" -Recurse -Filter *.java | ForEach-Object FullName
& javac --release 8 -Xlint:-options -encoding UTF-8 -classpath $androidJar -d "$out\classes" $src
if ($LASTEXITCODE) { throw "javac fallo" }
$classes = Get-ChildItem "$out\classes" -Recurse -Filter *.class | ForEach-Object FullName
& "$($bt.FullName)\d8.bat" --release --min-api 24 --lib $androidJar --output "$out\dex" $classes
if ($LASTEXITCODE) { throw "d8 fallo" }

# 2) Manifiesto -> APK base, y se le anade classes.dex
& "$($bt.FullName)\aapt2.exe" link -o "$out\base.apk" -I $androidJar --manifest "$here\AndroidManifest.xml" `
    --min-sdk-version 24 --target-sdk-version 33 --version-code 1 --version-name 1.0
if ($LASTEXITCODE) { throw "aapt2 fallo" }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::Open("$out\base.apk", "Update")
[void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, "$out\dex\classes.dex", "classes.dex")
$zip.Dispose()

# 3) Alinear y firmar
& "$($bt.FullName)\zipalign.exe" -f -p 4 "$out\base.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw "zipalign fallo" }
$ks = "$here\keystore\adbkeeper.jks"; $pwFile = "$here\keystore\password.txt"
if (-not (Test-Path $ks)) {
    New-Item -ItemType Directory -Force "$here\keystore" | Out-Null
    $pw = -join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Set-Content $pwFile $pw -NoNewline
    # keytool escribe mensajes informativos por stderr: en PowerShell 5.1 eso se trata como error, asi que
    # se ejecuta por cmd y se comprueba solo el codigo de salida.
    $kt = (Get-Command keytool).Source
    cmd /c "`"$kt`" -genkeypair -keystore `"$ks`" -storepass $pw -keypass $pw -alias adbkeeper -keyalg RSA -keysize 3072 -validity 9125 -dname `"CN=ADB Keeper (Android TV Master)`" >nul 2>&1"
    if ($LASTEXITCODE -or -not (Test-Path $ks)) { throw "keytool fallo" }
    "Clave de firma creada en $here\keystore (guardala)."
}
$pw = Get-Content $pwFile -Raw
& "$($bt.FullName)\apksigner.bat" sign --ks $ks --ks-pass "pass:$pw" --key-pass "pass:$pw" --out "$here\AdbKeeper.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw "apksigner fallo" }
& "$($bt.FullName)\apksigner.bat" verify "$here\AdbKeeper.apk"
if ($LASTEXITCODE) { throw "la firma no verifica" }

# 4) Copia para empaquetar con el programa
New-Item -ItemType Directory -Force "$here\..\vendor\tools\helper" | Out-Null
Copy-Item "$here\AdbKeeper.apk" "$here\..\vendor\tools\helper\AdbKeeper.apk" -Force
Remove-Item $out -Recurse -Force
"OK: {0} ({1} KB)" -f "$here\AdbKeeper.apk", [math]::Round((Get-Item "$here\AdbKeeper.apk").Length / 1KB)
