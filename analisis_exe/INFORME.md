# Análisis de AndroidTvMaster.exe

## Qué es
| | |
|---|---|
| Tipo | Ejecutable de Windows empaquetado con **PyInstaller 2.1+** (2,6 MB) |
| Lenguaje / versión | **Python 3.14** (bytecode `.pyc` de 3.14) |
| Interfaz | **PyQt6** (estilo Fusion, tema oscuro propio) |
| Nombre / versión | «Android TV Master» · `AndroidTvMaster` · `1.0.0` |
| Dependencias de runtime | Solo biblioteca estándar + PyQt6. Usa `adb` y `scrcpy` externos |
| Sin ofuscar | Sin PyArmor/Nuitka/UPX: el bytecode conserva nombres, docstrings y textos |

## Cómo se analizó
1. `pyinstxtractor.py` → 13 ficheros en el CArchive y 214 módulos en el PYZ (24 son propios, paquete `atvmaster`; el resto es stdlib y PyQt6).
2. Los `.pyc` son de la misma versión (3.14) que el intérprete local, así que se cargan con `marshal` y se desensamblan con `dis` sin pérdida. Los descompiladores públicos (pycdc, decompyle3, uncompyle6) no soportan 3.14.
3. Reconstrucción módulo a módulo desde el desensamblado compacto (`desensamblado_compacto/`).
4. Verificación automática contra el bytecode original (`herramientas/verify.py`, `verify2.py`).

REA (reverse-engineer-anything) está descargado en `C:\proyecto adb\REA`, pero es un servidor MCP orientado a binarios nativos/.NET/Electron/APK; para un PyInstaller no aporta nada que no cubra la extracción + `dis`, así que no hizo falta ejecutarlo.

## Arquitectura (24 módulos)
- `main.py`: `QApplication` + tema oscuro + `AppContext` + `MainWindow`.
- **Núcleo**: `adb.py` (cliente adb: ~45 operaciones), `paths.py`, `store.py` (dispositivos y ajustes JSON en `%APPDATA%\AndroidTvMaster`), `wol.py`, `scrcpy.py`.
- **Kiosco**: `kiosk.py` (REST de Fully en el puerto 2323, intent VIEW por ADB, vigilante, diagnóstico DNS desde la TV), `fully_config.py` (maneja los ajustes de Fully con `uiautomator dump` y toques), `fully_deploy.py` (descarga la APK EMM de fully-kiosk.com y la instala con plantilla `fully-once-settings.json`).
- **UI**: `main_window.py`, `dialogs.py`, `common.py` (pool de hilos + señales), `base_tab.py` y 9 pestañas.

## Funcionalidades
Lista de TVs con grupos, sondeo periódico de estado (en línea / sin autorizar / sin respuesta / apagada) y acciones en lote · conectar/desconectar/emparejar (Android 11+) · encender (Wake-on-LAN UDP 9 y 7 a broadcast global y /24 + `KEYCODE_WAKEUP`) · standby / reinicio / apagado · mando completo (28 teclas, texto, tap/swipe, 15 pantallas de ajustes) · capturas y vista previa ≈1 fps · escritorio remoto con scrcpy · grabación con `screenrecord` · apps (listar, abrir, parar, borrar datos, desinstalar, instalar APK) · explorador de archivos (pull/push/rm restringido a /sdcard y /storage) · shell con confirmación de comandos peligrosos y logcat · editor de `settings` y `wm size/density` · modo kiosco completo.

## Seguridad / comportamiento relevante
- Todo acto destructivo pide confirmación mostrando el comando exacto (`confirm`).
- Las apps del sistema no se pueden borrar ni limpiar desde la UI.
- Se invoca `adb` con listas de argumentos (sin `shell=True`); los valores van por `shlex.quote`.
- Única red saliente propia: lectura de `fully-kiosk.com/docs/.../downloads` y descarga de la APK EMM (con SHA-256 mostrado); REST local a las TVs.
- No se encontraron credenciales ni claves embebidas. La URL de ejemplo del campo Kiosco apunta a un servidor interno (`servidorwebs.zar.local`).

## Fidelidad de la reconstrucción
- 24/24 módulos reconstruidos y compilados; ~460 funciones comparadas.
- `verify.py`: 0 constantes o nombres ausentes. `verify2.py`: 4 funciones con formas distintas pero equivalentes.
- Prueba de humo con PyQt6 6.11 en modo sin pantalla: ventana, 9 pestañas, alta de dispositivo y lógica pura correctas. **No se probó contra una TV real.**
