# Crea un certificado de firma de codigo AUTOFIRMADO para uso interno y lo exporta a .pfx / .cer.
#
#   powershell -ExecutionPolicy Bypass -File firma\crear_certificado_interno.ps1
#
# - El .pfx (con clave privada) sirve para firmar: guardalo en un sitio seguro y NO lo subas a ningun repositorio.
# - El .cer (solo la parte publica) se instala en los PC donde se vaya a usar el programa para que confien
#   en la firma:  certutil -addstore -f TrustedPublisher AndroidTvMaster.cer
#                 certutil -addstore -f Root             AndroidTvMaster.cer
#   (en una empresa se reparte por directiva de grupo, GPO).
# - Un certificado autofirmado NO elimina el aviso de SmartScreen en los PC que no lo tengan instalado.
param(
    [string]$Subject = "CN=Android TV Master (uso interno)",
    [string]$Salida  = "$PSScriptRoot\..\certificado",
    [int]$Anios = 3,
    [securestring]$Clave
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Salida | Out-Null
if (-not $Clave) { $Clave = Read-Host "Contrasena para proteger el .pfx" -AsSecureString }
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $Subject -KeyAlgorithm RSA -KeyLength 3072 `
        -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears($Anios) -CertStoreLocation Cert:\CurrentUser\My
try {
    Export-PfxCertificate -Cert $cert -FilePath "$Salida\AndroidTvMaster.pfx" -Password $Clave | Out-Null
    Export-Certificate    -Cert $cert -FilePath "$Salida\AndroidTvMaster.cer" | Out-Null
}
finally {
    Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -ErrorAction SilentlyContinue   # la clave queda solo en el .pfx
}
"Creado en $((Resolve-Path $Salida).Path):  AndroidTvMaster.pfx (firmar)  y  AndroidTvMaster.cer (instalar en los PC)"
"Para firmar:  set SIGN_PFX=<ruta al .pfx>  &  set SIGN_PWD=<contrasena>  &  build.bat"
