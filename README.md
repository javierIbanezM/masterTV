# Android TV Master

Aplicación de escritorio (Windows) para controlar **cualquier dispositivo Android** con ADB:
Android TV y cajas, tablets y móviles, por **red (Wi‑Fi/Ethernet)** o por **cable USB**.

Versión **1.4.0**. El código se recuperó del ejecutable original `AndroidTvMaster.exe` (1.0.0) y
se amplió con soporte multi‑dispositivo y comentarios. Detalles de la recuperación en
[`analisis_exe/INFORME.md`](analisis_exe/INFORME.md).

## Qué hace

| Pestaña | Para qué sirve |
|---|---|
| **Resumen y energía** | Modelo, Android, tipo, batería, red, almacenamiento. Encender (Wake‑on‑LAN + `KEYCODE_WAKEUP`), standby, reiniciar, apagar. «Pasar de USB a Wi‑Fi». |
| **Kiosco (URL)** | Mantener una URL a pantalla completa (Fully Kiosk u otro navegador), arranque automático, zoom por densidad, diagnóstico de DNS/red hecho desde el propio equipo. |
| **Despliegue Fully (EMM)** | Descarga la APK oficial de Fully EMM e instálala con una plantilla de ajustes y los permisos necesarios. |
| **Navegar** | Abrir una web en el dispositivo (en el navegador que elijas), atrás/adelante/recargar, desplazar la página, **favoritos** e historial. |
| **Mando** | D‑pad, volumen/canales, multimedia, escribir texto, tap/swipe, **gestos para móviles/tablets**, atajos a pantallas de ajustes. |
| **Pantalla y escritorio remoto** | Captura, vista previa en vivo (~1 fps), **control con ratón y teclado dentro de la propia ventana**, escritorio remoto con scrcpy, grabación de pantalla. |
| **Aplicaciones** | Listar, abrir, forzar cierre, borrar datos, desinstalar, instalar APK. |
| **Ajustes del sistema** | Apagado de pantalla, animaciones, resolución y densidad (`wm`), editor de `settings`. |
| **Archivos** | Explorar, descargar al PC, subir, eliminar. |
| **Shell y logcat** | `adb shell` con confirmación en comandos peligrosos y visor de logcat. |

Además: lista de dispositivos con **grupos**, estado en vivo, **acciones en lote** sobre los marcados,
un registro de actividad, **mosaico de pantallas**, **programación y avisos**, **perfiles de preparación**
e **inventario a Excel** (ver la sección siguiente).

## Gestionar varios dispositivos

Marca varios con la casilla de la lista (o ninguno para actuar sobre el seleccionado) y usa
**«Acción sobre las marcadas ▾»** o el menú *Aplicación*.

### Instalar y desinstalar en lote
- **Instalar APK en las marcadas…** admite `.apk` y también paquetes divididos `.apks`, `.xapk` y
  `.apkm` (se instalan con `install-multiple`). También puedes **arrastrar los archivos a la ventana**.
- Antes de instalar se muestra la lista de dispositivos y el comando exacto; el resultado sale
  por dispositivo en el registro.
- **Desinstalar app en las marcadas…**: solo apps de usuario; las del sistema están protegidas y se omiten.

### Control con el ratón en la propia ventana
Pestaña *Pantalla* → casilla **«Controlar con el ratón y el teclado»** (activa la vista en vivo):

| Acción | Efecto |
|---|---|
| Clic izquierdo | Toque |
| Arrastrar | Deslizar |
| Rueda | Desplazar |
| Clic derecho / central | Atrás / Inicio |
| Teclear (tras un clic en la pantalla) | Texto (solo ASCII), Intro, Borrar, Esc = Atrás, flechas |

Se apaga solo al cambiar de dispositivo, para que un clic nunca llegue a otro equipo. La vista se
refresca ~1 vez por segundo: para uso fluido está **scrcpy** (botón «Abrir escritorio remoto»).

### Mosaico de pantallas
*Ver → Mosaico de pantallas…* (o la acción en lote): miniaturas de hasta 16 dispositivos que se
refrescan solas (máx. 6 capturas simultáneas). **Doble clic** en una la abre en la pestaña *Pantalla*.

### Perfiles de preparación
*Aplicación → Perfiles de preparación…*: listas de pasos para dejar un terminal listo con un clic.
Un paso por línea (`#` = comentario):

```
stayawake on                  # no apagar la pantalla al cargar
timeout 10m                   # apagado de pantalla (30s, 5m, 1h, never)
animations 0.5                # escala de animaciones (0, 0.5, 1)
brightness 150 · rotation auto · density 320 | density reset
setting global stay_on_while_plugged_in 7
install C:\apks\mi_app.apk     # .apk / .apks / .xapk / .apkm
uninstall com.ejemplo.app     # solo apps de usuario
grant com.ejemplo.app android.permission.CAMERA
kiosk http://servidor/visor.php com.fullykiosk.emm
launch com.ejemplo.app · wake · home
```

Cada línea se **valida al guardar** (con número de línea si hay error) y **no existe un paso para
ejecutar comandos libres**: un perfil compartido solo puede hacer lo que está en esta lista. Se
aplican desde «Aplicar perfil de preparación…» sobre los marcados, con confirmación previa. Un paso
que falla no detiene los demás.

### Programación y avisos
*Aplicación → Programación y avisos…*
- **Tareas programadas** a una hora y unos días: encender (WoL + despertar), standby, aplicar la URL
  de kiosco, aplicar un perfil o reiniciar (esta última pide confirmación al crearla). Afectan a todos,
  a un grupo o a dispositivos concretos.
- **Avisos**: si un dispositivo que estaba en línea deja de responder durante N sondeos seguidos
  (3 por defecto) se avisa en el registro, con una notificación de Windows y, si lo configuras, con un
  **webhook** (Teams, Slack, Discord; para Telegram: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>`).
  Se avisa también cuando se recupera. Un dispositivo nunca visto en línea no genera avisos.
- ⚠ **Solo funcionan con la aplicación abierta**: no son un servicio de Windows. Para vigilar 24 h,
  deja la aplicación abierta en un PC que no se apague.

### ADB por Wi‑Fi siempre activo
Para no tener que ir con un cable a cada terminal:

- **«Activar ADB por Wi‑Fi en las marcadas…»** (acción en lote) o el botón **«Pasar de USB a Wi‑Fi»**
  de la pestaña *Resumen*. Hace, según la versión de Android:
  1. **Android 11+**: enciende la *Depuración inalámbrica* (`settings put global adb_wifi_enabled 1`) y
     quita la caducidad de la autorización (`adb_allowed_connection_time 0`, por defecto caduca a los 7 días).
  2. **Cualquier Android**: ADB por red clásico en el puerto fijo 5555 (`adb tcpip 5555`).
  3. Comprueba que el puerto responde y **crea la entrada «Nombre (Wi‑Fi)»** del dispositivo.
- **«Mantener el ADB por Wi‑Fi activo»** (casilla al editar cualquier dispositivo, de red o de cable): cada vez
  que el equipo aparece conectado (al arrancar este programa, al enchufarlo a su base o tras un reinicio) la
  app **instala ADB Keeper si falta** (Android 11+) o repara su permiso y su exclusión de batería. En las
  entradas **USB** además reactiva el ADB por Wi‑Fi si estaba apagado y crea la entrada de red. No repite
  más de una vez cada 5 minutos.
- Verificado en un **Datalogic Memor 11 (Android 13, compilación `user`, sin root ni MDM)**, incluido el ciclo
  «reinicio → vuelve por USB → la app lo reactiva y crea su entrada Wi‑Fi» (≈ 45 s de arranque + unos segundos): tras activarlo,
  el puerto 5555 se abre, `adb connect` entra por red **sin pedir confirmación en el dispositivo** (el PC ya
  estaba autorizado por USB) y mDNS lo anuncia. «Pasar de USB a Wi‑Fi» se puede revertir con
  `Adb.disable_wifi_debug` o desde *Opciones de desarrollador*.

### ADB Keeper: activación automática al arrancar (Android 11+)
Una app auxiliar minúscula (`helper_apk/`, 16 KB, firmada) que **vive en el dispositivo** y vuelve a encender la
depuración inalámbrica sola:

- **Cuándo actúa:** al arrancar el dispositivo, al actualizarse la app y cada 15 minutos mientras haya Wi‑Fi o
  Ethernet (por ejemplo si Android la apagó al cambiar de red). También deja la autorización sin caducidad.
- **Cómo se instala:** acción en lote **«Instalar ADB Keeper (activación al arrancar)…»** o el paso `keeper` de un
  perfil de preparación. La app del PC instala el APK, le concede **una vez** el permiso `WRITE_SECURE_SETTINGS`
  (solo se puede conceder por adb, con el dispositivo conectado), espera a que Android lo guarde y lo abre una vez en
  silencio (Android no entrega el aviso de arranque a una app recién instalada que nunca se ha abierto).
- **Verificado en un Datalogic Memor 11 (Android 13, `user`, sin root ni MDM)**, con el dispositivo reiniciado
  **sin PC ni cable**: el Keeper se ejecutó solo al arrancar (`logcat -s AdbKeeper`: «arranque: Depuración
  inalámbrica activada») unos 12 s después de terminar de arrancar; el PC, ya autorizado por USB, se conectó por TLS
  al puerto aleatorio **sin emparejar** (adb incluso se conectó solo vía mDNS).
- **Exclusión del ahorro de batería (imprescindible):** si no, Android deja la app en el *standby bucket* «nunca
  usada» y **retiene su aviso de arranque** (`Deferred BOOT_COMPLETED` en `dumpsys activity broadcasts`) hasta que
  alguien la abre; en un Memor 11 reiniciado así no se activó nada. La instalación ejecuta
  `cmd deviceidle whitelist +com.atvmaster.adbkeeper` (se conserva entre reinicios) y, si encuentras un Keeper
  instalado con una versión anterior, la app lo repara sola al detectarlo por USB. Comprobado después en el
  Memor 11: tras reiniciar, la depuración inalámbrica volvió sola en ~90 s.
- **El puerto cambia** en cada activación: no es el 5555. La app del PC lo encuentra por mDNS (misma red local) y, si un
  dispositivo guardado cambia de puerto, lo actualiza sola.
- **Limitaciones:**
  - **El permiso tarda en guardarse en disco.** Reiniciar a los pocos segundos de concederlo lo pierde (lo comprobé:
    el Keeper llegó a ejecutarse pero con «Falta el permiso»). La instalación espera 15 s y lo verifica; si
    aparece sin permiso, la app lo restablece al detectar el dispositivo por USB.
  - Solo **Android 11+** y solo con Wi‑Fi/Ethernet; **no activa el ADB clásico del puerto 5555** (una app no puede).
  - Un MDM o la política del fabricante puede revocar el permiso o impedir la instalación; otros fabricantes pueden
    comportarse distinto: **solo está verificado en el Memor 11**.
  - Deja un puerto de depuración abierto en la red. Úsalo en redes de confianza. Se desinstala como cualquier app
    (o con `Adb.remove_keeper`), y la depuración inalámbrica se apaga desde *Opciones de desarrollador*.
- **Compilar el APK:** `powershell -File helper_apk\build_helper.ps1` (usa el Android SDK y un JDK; crea la clave de
  firma en `helper_apk\keystore\`, que debes conservar y no subir al repositorio). La copia empaquetada
  queda en `vendor\tools\helper\`.

**Sin ADB Keeper (Android 10 o anterior, o si no lo instalas)**
- Nada puede activar ADB al arrancar sin root o un MDM. El ADB por red clásico (5555) se pierde al reiniciar, y la
  depuración inalámbrica de Android 11+ se apaga igualmente.
- Alternativa: **enchufar por USB una vez tras cada reinicio** (o dejarlo en una base con USB conectada al PC con la
  casilla «Mantener» marcada) y la app lo vuelve a dejar activo.
- Para flotas grandes: un **MDM** o las herramientas del fabricante (en Datalogic, Scan2Deploy o su gestor de
  dispositivos). No lo he probado.
- **Seguridad**: deja un puerto de depuración abierto en la red y la autorización sin caducidad. Úsalo solo en
  redes de confianza y con equipos que ya autorizaron a vuestros PC.

### IMEI
La pestaña *Resumen* y el inventario incluyen el **IMEI** (uno por ranura SIM) en los equipos con módem
(móviles, PDA con 4G…); en TVs y cajas no se muestra. Sin root, Android 10+ no lo deja leer a las apps, pero
el usuario `shell` de adb sí puede en muchos equipos con `service call iphonesubinfo` (comprobado en un
Datalogic Memor 11 con Android 13; `cmd phone get-imei` salía «Permission denied»). Solo se acepta un valor de
15 dígitos con **dígito de control (Luhn) correcto**; si el equipo no lo permite, la fila queda vacía (no se
inventa nada). Es un identificador del dispositivo: tenlo en cuenta al compartir el CSV del inventario.

### Inventario
*Aplicación → Exportar inventario a Excel (CSV)…*: una fila por dispositivo (marcados, o todos) con
tipo, fabricante, modelo, Android, parche de seguridad, nº de serie, MAC, IP, batería, pantalla,
almacenamiento libre, idioma, apps de usuario y URL de kiosco. CSV con `;` y acentos correctos para
Excel en español; los textos que empiezan por `=`, `+`, `-` o `@` se neutralizan para evitar inyección de fórmulas.

## Menú adaptado al tipo de dispositivo

La ventana muestra solo lo que tiene sentido para el dispositivo seleccionado. El tipo se **detecta
solo** al ponerse en línea (y se guarda, así el menú correcto aparece también sin conexión), o lo
fijas tú al editar el dispositivo. El icono de la lista (📺 TV · 📦 caja · ▭ tablet · 📱 móvil) y la
barra de estado indican el perfil activo.

| | 📺 TV / 📦 caja | ▭ Tablet | 📱 Móvil |
|---|---|---|---|
| Pestañas | todas | todas | sin Kiosco ni Despliegue Fully |
| Mando | D‑pad, canales, guía, fuente | D‑pad, gestos táctiles, notificaciones, orientación, brillo | igual que tablet |
| Resumen | encender (WoL) y **apagar del todo** | sin «apagar del todo» (requiere root) | ídem |
| Archivos | – | **carpetas rápidas** (Descargas, DCIM, Pictures…) | ídem |
| Navegar | nota sobre navegadores para TV | desplazar la página con gestos | ídem |

**Terminal de mano (📟)** — todas las pestañas (suelen llevar un kiosco o una web de almacén), más:
en *Mando*, un grupo de **teclas físicas** (cámara, enfoque, recientes, encendido y una caja para enviar
cualquier `KEYCODE_…` o número, útil para localizar la tecla del gatillo, cuyo código depende del
modelo) y en *Ajustes del sistema*, **mantener la pantalla encendida mientras carga**. Lo específico
del escáner de códigos de barras (DataWedge o equivalente del fabricante) no está incluido.

Con tipo desconocido, o con **Ver → Mostrar todas las funciones**, se ve todo. Los perfiles se definen
en `atvmaster/profiles.py` (ahí se cambia qué ve cada tipo).

## Requisitos

- Windows 10/11 y Python 3.10+ (probado con 3.14).
- `adb` (Android platform‑tools). Se busca, por este orden: ruta en *Configuración*,
  `tools\platform-tools\`, `platform-tools\` junto a la app, `PATH`, `ANDROID_HOME`/`ANDROID_SDK_ROOT`
  y `%LOCALAPPDATA%\Android\Sdk\platform-tools`.
- Opcional: [scrcpy](https://github.com/Genymobile/scrcpy/releases) en `tools\scrcpy\` (escritorio remoto).

## Instalación y arranque

```
pip install -r requirements.txt
python main.py
```

## Instalar en un PC (sin Python)

`build.bat` genera en `dist\`:

| Fichero | Para qué |
|---|---|
| `AndroidTvMaster-1.4.0-Setup.exe` | **Instalador** (asistente en español, acceso directo, desinstalador). Instala por defecto solo para el usuario, sin pedir administrador. |
| `AndroidTvMaster-1.4.0-portable.zip` | Versión portable: descomprimir y ejecutar `AndroidTvMaster.exe`. |
| `AndroidTvMaster\` | Carpeta compilada (la misma que contienen los dos anteriores). |

Ya incluyen **adb** y **scrcpy 5.0.1** en `tools\`, así que el programa funciona nada más instalarlo
y el escritorio remoto con ratón y teclado está disponible. Esos binarios se guardan en
`vendor\tools\` (ver `vendor\LEEME.txt`); para actualizarlos, sustituye su contenido y vuelve a
ejecutar `build.bat`. Los datos del usuario (`%APPDATA%\AndroidTvMaster`) no se borran al desinstalar.

Requisitos para compilar: Python con `pip install -r requirements.txt` y, para el instalador,
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (si falta, el resto se genera igualmente).
Al ser un `.exe` sin firmar, Windows SmartScreen puede avisar la primera vez
(«Más información → Ejecutar de todas formas»).

### Firmar el ejecutable (opcional)
`build.bat` firma el `.exe` y el instalador si defines `SIGN_PFX` (ruta del `.pfx`) y, si lleva
contraseña, `SIGN_PWD` (usa `signtool` del Windows SDK; ver `firma\firmar.bat`).
- **Certificado propio (uso interno):** `firma\crear_certificado_interno.ps1` genera un `.pfx` y un
  `.cer` autofirmados. La firma solo es de confianza en los PC donde instales el `.cer`
  (`certutil -addstore -f TrustedPublisher AndroidTvMaster.cer`, o por GPO).
- **Sin avisos en cualquier PC:** hace falta un certificado de firma de código emitido por una
  autoridad reconocida (OV o EV); no se puede conseguir con un script.
- Nunca subas el `.pfx` a un repositorio (está en `.gitignore`).

### Pruebas automáticas
`python -m unittest discover -s tests -v` (también se ejecutan al inicio de `build.bat`: si una falla,
no se genera nada). Cubren perfiles, tareas programadas, avisos, instalación de paquetes (incluida la
extracción segura de ZIP), inventario/CSV, mDNS, detección de tipo y validaciones.

## Añadir dispositivos

Tres formas, de menos a más trabajo manual:

1. **🌐 Buscar en red** (botón o menú *Aplicación*): barre una subred (p. ej. `192.168.2.0/24`) probando
   el puerto de ADB (5555 por defecto, editable) y añade los que respondan. También incluye los que se
   anuncian por **mDNS** (depuración inalámbrica de Android 11+, que usa un puerto aleatorio). El
   desplegable propone las subredes de este PC, pero es editable: si tus dispositivos están en otra
   red enrutada, escríbela a mano. Solo hace conexiones TCP; para leer el modelo se conecta con
   `adb connect`, y un dispositivo que no te conoce mostrará el aviso de «Permitir depuración».
   Límite de seguridad: máximo 1024 direcciones por búsqueda.
2. **🔍 Descubrir**: lo que ADB ya ve ahora mismo (USB, red y mDNS).
3. **＋ Añadir**: a mano, con la IP o el nº de serie USB.

### Preparar cada tipo de dispositivo

| Dispositivo | Cómo activar ADB |
|---|---|
| **Android TV / Google TV / caja** | Ajustes → Sistema → Acerca de → pulsar 7 veces «Compilación» → Opciones de desarrollador → activar **Depuración USB** y/o **Depuración por red/Wi‑Fi**. Acepta el aviso de autorización la primera vez. |
| **Móvil / tablet por USB** | Ajustes → Acerca del teléfono → pulsar 7 veces «Número de compilación» → Opciones de desarrollador → **Depuración USB**. Conecta el cable y acepta «¿Permitir depuración USB?». En la app: *Descubrir*. |
| **Terminal de mano / PDA Android 11+** (Datalogic Memor, Zebra, Honeywell…) | Igual que un móvil con depuración inalámbrica (fila siguiente). Si tiene un MDM corporativo, puede bloquear las opciones de desarrollador: hay que pedir que las permita. Conviene dejar el Wi‑Fi activo en reposo y reservar su IP en el router. |
| **Móvil / tablet por Wi‑Fi (Android 11+)** | Opciones de desarrollador → **Depuración inalámbrica** → *Emparejar dispositivo con código* (déjala abierta). En la app: menú *Aplicación → Emparejar con código…*: detecta solo el dispositivo (mDNS); escribes el código y, al emparejar, se abre *Descubrir* para añadirlo. |
| **Cualquier equipo con USB → pasar a Wi‑Fi** | Conéctalo por USB, selecciónalo y pulsa **Pasar de USB a Wi‑Fi** (pestaña Resumen): ejecuta `adb tcpip 5555`, lee su IP y lo añade como dispositivo de red. |

**Android 11+ y el puerto cambiante.** La depuración inalámbrica usa un puerto aleatorio que cambia cada
vez que se desactiva y reactiva (o al reiniciar). Si un dispositivo guardado deja de responder en su
puerto, la app lo busca por mDNS en la misma IP, se reconecta y actualiza el puerto guardado
(queda anotado en el registro). Esto solo funciona si el PC y el dispositivo están en la misma red
local (mDNS no atraviesa routers).

### Tipo y conexión

- **Conexión «Red»**: identificador `IP:puerto` (5555 por defecto). Admite Wake‑on‑LAN si guardas la MAC.
- **Conexión «USB»**: identificador = nº de serie (lo rellena *Descubrir*). No usa puerto, MAC ni WoL.
- **Tipo**: `auto` (se detecta con `ro.build.characteristics`, la característica `leanback` y el
  fabricante), `tv`, `box`, `tablet`, `phone`, `pda` (terminal de mano). Los fabricantes de PDA
  reconocidos están en `PDA_VENDORS` (`adb.py`); si tu modelo no se detecta, fija el tipo en *Editar*. La pestaña Resumen muestra el tipo detectado.

### Estados en la lista

`En línea` · `Falta autorizar en el dispositivo` (acepta el aviso en su pantalla) ·
`ADB sin respuesta` · `Apagado / sin depuración / desconectado`.

## Compatibilidad por tipo de dispositivo

| Función | TV / caja | Tablet | Móvil |
|---|---|---|---|
| Mando (D‑pad, volumen, media) | ✔ | ✔ | ✔ (D‑pad limitado) |
| Navegar (abrir webs, favoritos) | ✔ si hay navegador instalado | ✔ | ✔ |
| Notificaciones, orientación, brillo | – | ✔ | ✔ |
| Gestos de desplazar / desbloquear | – | ✔ | ✔ |
| Captura / vista previa / scrcpy | ✔ | ✔ | ✔ (pantallas protegidas salen en negro) |
| Apps, archivos, shell, logcat, settings | ✔ | ✔ | ✔ |
| Abrir apps | ✔ lanzador LEANBACK | ✔ | ✔ (con *fallback* a `am start`) |
| Wake‑on‑LAN | ✔ si el equipo lo soporta | según modelo | normalmente no |
| Apagar del todo | `reboot -p` | `reboot -p` o `svc power shutdown` | suele requerir root |
| Kiosco con Fully (REST puerto 2323) | ✔ | ✔ | ✔ (solo por red) |
| «Configurar Fully en la TV» (automatiza su interfaz) | ✔ | ⚠ probado con pantalla horizontal | ⚠ en vertical puede fallar |

## Modo kiosco

1. **Fully con Administración remota** (puerto 2323): se guardan la *Start URL*, *Launch on Boot* y
   *Keep Screen On* dentro de Fully. Persiste tras reiniciar y no depende del PC. Solo por red.
2. **Intent `VIEW` por ADB**: abre la URL en Fully (o la app elegida). Lo lanza esta aplicación al
   detectar que el equipo se enciende o, con el **vigilante**, cuando el kiosco sale de pantalla.
3. **Configurar Fully en el equipo**: si no hay Administración remota, la app abre los ajustes de
   Fully con `uiautomator` y los cambia como lo haría una persona.
4. **Despliegue EMM**: instala la edición EMM con una plantilla exportada de un equipo de referencia.

El botón *Comprobar desde la TV/dispositivo* ejecuta ping, DNS y una petición HTTP **desde el propio
equipo** y avisa si el DNS privado o un sufijo de dominio impide resolver el servidor.

## Datos y seguridad

- Datos: `%APPDATA%\AndroidTvMaster\` → `devices.json`, `settings.json`, `fully-template.json`.
  Se leen con tolerancia: un `devices.json` de la 1.0 funciona sin migrar.
- Cualquier acción destructiva (reiniciar, borrar datos, desinstalar, eliminar archivos, cambiar
  ajustes, `wm`) pide confirmación mostrando el **comando exacto**.
- Las apps del sistema no se pueden desinstalar ni limpiar desde la interfaz; el borrado de archivos
  solo se permite dentro de `/sdcard` y `/storage`.
- La contraseña de Fully se guarda en claro en `devices.json`; protege tu perfil de Windows.
- Red saliente propia: lectura de `fully-kiosk.com` (descarga de la APK EMM) y REST a los equipos.

## Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| «No se encuentra adb.exe» | Indica la ruta en *Configuración* o copia platform‑tools a `tools\`. |
| Estado «Falta autorizar» | Mira la pantalla del dispositivo y acepta «Permitir depuración». Marca «Permitir siempre». |
| Móvil por USB no aparece | Cable de datos (no solo carga), driver USB del fabricante, modo «Transferencia de archivos», revoca autorizaciones USB y reconecta. |
| Por Wi‑Fi: «Apagado / sin depuración» | Comprueba IP, que el PC esté en la misma red y que la depuración por red esté activa (el puerto puede cambiar en Android 11+). |
| Captura negra | La app muestra contenido protegido (DRM, banca). Es una restricción de Android. |
| La TV no abre el kiosco por nombre | Mira el informe de *Comprobar*: suele ser DNS privado automático o falta del sufijo de dominio (botones de arreglo en la propia pestaña). |

## Estructura del proyecto

```
main.py                    punto de entrada y tema oscuro
atvmaster/
  adb.py                   cliente adb (todas las operaciones) y constantes (teclas, pantallas de ajustes)
  store.py                 Device / DeviceStore / Settings (JSON), tipos y conexiones
  paths.py                 rutas de la app y búsqueda de adb/scrcpy
  wol.py  scrcpy.py        Wake‑on‑LAN y lanzador de scrcpy
  kiosk.py                 servicio de kiosco (REST de Fully, intent, vigilante, diagnóstico)
  fully_config.py          automatiza los ajustes de Fully con uiautomator
  fully_deploy.py          descarga/instala Fully EMM con plantilla
  profiles.py              qué pestañas y controles ve cada tipo de dispositivo
  prep.py                  perfiles de preparación (lenguaje de pasos validado)
  scheduler.py             tareas programadas y detector de caídas (sin interfaz)
  inventory.py             recogida de datos y exportación a CSV
  ui/
    main_window.py         lista, sondeo, acciones en lote
    common.py              hilos (QThreadPool), AppContext, diálogos de confirmación
    base_tab.py            clase base de las pestañas
    dialogs.py             alta de dispositivo, descubrimiento, emparejado, configuración
    tabs/                  una pestaña por fichero
    widgets.py             visor de pantalla con ratón/teclado
    mosaic.py              ventana de mosaico
    tools_dialogs.py       diálogos de programación/avisos y de perfiles
helper_apk/                código y script de compilación de ADB Keeper (app auxiliar del dispositivo)
tests/                     pruebas automáticas de la lógica (python -m unittest discover -s tests)
firma/                     scripts para firmar el .exe
installer/                 script del instalador (Inno Setup)
vendor/                    adb y scrcpy que se empaquetan
analisis_exe/              material de la recuperación (no hace falta para ejecutar)
```

## Cómo ampliarlo

- **Nueva operación de adb**: añade un método a `Adb` (devuelve `Result` o datos) en `atvmaster/adb.py`.
- **Nueva pestaña**: crea `ui/tabs/mi_tab.py` con una clase que herede de `DeviceTab`
  (`title`, `key`, `on_device_changed`, `on_activated`; usa `self.call(fn, on_ok)` para trabajo en segundo
  plano: `fn` recibe el serial y `on_ok` corre en el hilo de la UI), regístrala en la lista
  `tab_widgets` de `MainWindow.__init__` y añade su `key` a `ALL_TABS` y a los perfiles de
  `profiles.py`. Si debe cambiar según el tipo, implementa `apply_kind(kind, show_all)`.
- **Nuevo ajuste de dispositivo**: añade el campo al dataclass `Device`; los `devices.json`
  antiguos siguen cargando porque las claves ausentes toman su valor por defecto.
- **Regla de oro de la UI**: nada que toque adb se ejecuta en el hilo de la interfaz.

## Cambios

- **1.4.0** — Instalar/desinstalar en lote (con arrastrar y soltar y paquetes `.apks/.xapk/.apkm`);
  control con ratón y teclado en la ventana; mosaico de pantallas; perfiles de preparación;
  tareas programadas y avisos de caída (notificación y webhook); inventario a Excel;
  **ADB por Wi‑Fi siempre activo** (activar en lote, mantener al conectar por USB, crea la entrada de red);
  **ADB Keeper**: app auxiliar que lo reactiva sola al arrancar (Android 11+), verificada en un Memor 11; MAC de Android 13
  por `dumpsys wifi`; detección de dispositivos con ADB clásico (`_adb._tcp`) por mDNS; pruebas
  automáticas; scripts de firma; **blindaje contra cierres**: un error inesperado se anota en
  `error.log` en vez de cerrar todo el programa (PyQt6 cierra la aplicación ante cualquier excepción
  no controlada); corregida una división por cero en la pestaña Kiosco heredada del original.
- **1.3.0** — **Buscar en red** (barrido de subred + mDNS), emparejado con detección automática,
  recuperación del puerto de la depuración inalámbrica cuando cambia, perfil **terminal de mano**
  (PDA) con detección por fabricante, teclas físicas y ajustes de energía.
- **1.2.0** — Menú por tipo de dispositivo (pestañas y controles según TV/caja/tablet/móvil, con
  detección automática); pestaña **Navegar** (URL, navegador a elegir, favoritos, historial);
  extras táctiles (notificaciones, orientación, brillo); carpetas rápidas en Archivos.
- **1.1.0** — Soporte para móviles, tablets y cajas; conexión por USB; *Descubrir dispositivos*;
  detección de tipo y batería; *Pasar de USB a Wi‑Fi*; gestos táctiles; arranque de apps con
  *fallback*; apagado con alternativa; textos genéricos («dispositivo»); comentarios y documentación.
- **1.0.0** — Versión original (recuperada del `.exe`).

## Nota sobre la recuperación

`analisis_exe/herramientas/verify*.py` comparan el bytecode del `.exe` 1.0.0 con el código. Tras la
1.1.0 mostrarán diferencias a propósito (funciones y textos nuevos); sirven para ver exactamente qué
cambió respecto al original. Detalle de las pocas diferencias de la propia recuperación en el informe.
