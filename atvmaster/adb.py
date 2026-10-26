"""Envoltorio fino sobre el ejecutable adb. Todas las llamadas son bloqueantes:
la UI las ejecuta en hilos (ver ui/common.py: AppContext.run).

Funciona con cualquier dispositivo Android con depuración ADB: dispositivos, cajas, tablets y móviles,
tanto por red (`adb connect IP:PUERTO`) como por cable USB (nº de serie).
"""
from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Paquetes de Fully Kiosk: Google Play y edición EMM (la EMM puede leer el fichero de importación en Android 11+).
FULLY_PACKAGES = ("de.ozerov.fully", "com.fullykiosk.emm")
KEEPER_PKG = "com.atvmaster.adbkeeper"   # app auxiliar que reactiva la depuración inalámbrica (ver helper_apk/)

# Fabricantes de terminales de mano / PDA (coincidencia por texto en fabricante o marca).
PDA_VENDORS = ("datalogic", "zebra", "honeywell", "urovo", "chainway", "newland", "unitech",
               "cipherlab", "pointmobile", "point mobile", "bluebird", "symbol", "intermec",
               "janam", "handheld", "m3 mobile", "seuic", "idata", "opticon", "casio")
# En Windows evita que cada subproceso abra una ventana de consola.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_PNG_SIG = b"\x89PNG\r\n\x1a\n"

# Teclas del mando: nombre en la UI -> KEYCODE de Android. Valen igual en TV, tablet y móvil.
KEYCODES = {
    "Encender/Apagar": "KEYCODE_POWER",
    "Despertar": "KEYCODE_WAKEUP",
    "Standby": "KEYCODE_SLEEP",
    "Inicio": "KEYCODE_HOME",
    "Atrás": "KEYCODE_BACK",
    "Menú": "KEYCODE_MENU",
    "Arriba": "KEYCODE_DPAD_UP",
    "Abajo": "KEYCODE_DPAD_DOWN",
    "Izquierda": "KEYCODE_DPAD_LEFT",
    "Derecha": "KEYCODE_DPAD_RIGHT",
    "OK": "KEYCODE_DPAD_CENTER",
    "Vol +": "KEYCODE_VOLUME_UP",
    "Vol -": "KEYCODE_VOLUME_DOWN",
    "Silencio": "KEYCODE_VOLUME_MUTE",
    "Play/Pausa": "KEYCODE_MEDIA_PLAY_PAUSE",
    "Stop": "KEYCODE_MEDIA_STOP",
    "Siguiente": "KEYCODE_MEDIA_NEXT",
    "Anterior": "KEYCODE_MEDIA_PREVIOUS",
    "Retroceder": "KEYCODE_MEDIA_REWIND",
    "Avanzar": "KEYCODE_MEDIA_FAST_FORWARD",
    "Canal +": "KEYCODE_CHANNEL_UP",
    "Canal -": "KEYCODE_CHANNEL_DOWN",
    "Entradas (fuente)": "KEYCODE_TV_INPUT",
    "Ajustes": "KEYCODE_SETTINGS",
    "Guía": "KEYCODE_GUIDE",
    "Información": "KEYCODE_INFO",
    "Asistente": "KEYCODE_ASSIST",
    "Aplicaciones recientes": "KEYCODE_APP_SWITCH",
}

# Pantallas de ajustes que se pueden abrir por intent (`am start -a ...`).
SETTINGS_SCREENS = {
    "Ajustes (principal)": "android.settings.SETTINGS",
    "Wi-Fi": "android.settings.WIFI_SETTINGS",
    "Red / Internet": "android.settings.WIRELESS_SETTINGS",
    "Bluetooth": "android.settings.BLUETOOTH_SETTINGS",
    "Pantalla": "android.settings.DISPLAY_SETTINGS",
    "Sonido": "android.settings.SOUND_SETTINGS",
    "Aplicaciones": "android.settings.APPLICATION_SETTINGS",
    "Almacenamiento": "android.settings.INTERNAL_STORAGE_SETTINGS",
    "Idioma / Teclado": "android.settings.LOCALE_SETTINGS",
    "Fecha y hora": "android.settings.DATE_SETTINGS",
    "Accesibilidad": "android.settings.ACCESSIBILITY_SETTINGS",
    "Opciones de desarrollador": "android.settings.APPLICATION_DEVELOPMENT_SETTINGS",
    "Información del dispositivo": "android.settings.DEVICE_INFO_SETTINGS",
    "Cuentas": "android.settings.SYNC_SETTINGS",
    "Entradas de TV": "android.settings.INPUT_METHOD_SETTINGS",
}

# Comandos de shell que piden confirmación en la pestaña Shell (borrar, reiniciar, cambiar ajustes...).
_DANGEROUS = re.compile(
    r"(^|[;&|\s])(rm|rmdir|mv|dd|mkfs\S*|reboot|poweroff|shutdown|wipe|format|"
    r"pm\s+(uninstall|clear|disable\S*|hide|suspend)|settings\s+(put|delete)|setprop|"
    r"svc\s+\S+\s+(disable)|su|chmod|chown|mount|umount|cmd\s+package\s+(uninstall|clear)|"
    r"am\s+(kill|force-stop|broadcast)|wm\s+(size|density)|content\s+(insert|update|delete))(\s|$)",
    re.IGNORECASE,
)


def is_dangerous_shell(cmd: str) -> bool:
    return bool(_DANGEROUS.search(cmd))


@dataclass
class Result:
    """Resultado de una llamada a adb: código de salida, stdout, stderr y los bytes crudos de stdout."""

    rc: int
    out: str
    err: str
    raw: bytes = b""

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def text(self) -> str:
        # Texto "para mostrar": la salida, o el error si no hubo salida.
        return (self.out + ("\n" + self.err if self.err and not self.out else "")).strip()


class AdbError(RuntimeError):
    pass


# ---------------------------------------------------------------- utilidades de red

def tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    """¿Responde el puerto TCP? Se usa antes de `adb connect` para no bloquear adb."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def shell_quote(s: str) -> str:
    return shlex.quote(s)


def arp_mac(host: str) -> str:
    """MAC de `host` según la caché ARP del PC (una sola IP, sin escanear la red)."""
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        return ""
    try:
        p = subprocess.run(["arp", "-a", host], capture_output=True, timeout=5,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(rf"{re.escape(host)}\s+([0-9a-f]{{2}}(?:[-:][0-9a-f]{{2}}){{5}})",
                  p.stdout.decode("utf-8", "replace"), re.I)
    return m.group(1).replace("-", ":").lower() if m else ""


def luhn_ok(number: str) -> bool:
    """Dígito de control (Luhn) de un IMEI: 15 dígitos y suma de comprobación correcta."""
    if not (number.isdigit() and len(number) == 15):
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


def parse_parcel_string(text: str) -> str:
    """Decodifica la cadena que devuelve `adb shell service call` (un Parcel en hexadecimal):
    estado, longitud y caracteres UTF-16, dos por palabra de 32 bits. Cadena vacía si no hay texto."""
    import re as _re
    words: list[int] = []
    for line in text.splitlines():
        m = _re.search(r"0x[0-9a-fA-F]{8}:\s+((?:[0-9a-fA-F]{8}\s+)*[0-9a-fA-F]{8})", line)
        if m:
            words += [int(w, 16) for w in m.group(1).split()]
    if len(words) < 3 or words[0] != 0 or words[1] in (0, 0xFFFFFFFF) or words[1] > 64:
        return ""
    chars = []
    for w in words[2:]:
        chars += [chr(w & 0xFFFF), chr(w >> 16)]
    return "".join(chars)[: words[1]].strip("\x00")


class Adb:
    """Cliente adb. `path_getter` devuelve la ruta actual del ejecutable."""

    def __init__(self, path_getter: Callable[[], str | None]):
        self._path_getter = path_getter

    @property
    def path(self) -> str:
        p = self._path_getter()
        if not p:
            raise AdbError(
                "No se encuentra adb.exe. Indica su ruta en Configuración o copia "
                "platform-tools a la carpeta tools/."
            )
        return p

    # ------------------------------------------------------------ ejecución básica

    def run(self, args: list[str], serial: str | None = None, timeout: float = 20,
            input_data: bytes | None = None) -> Result:
        """Ejecuta `adb [-s serial] args...`. Nunca lanza por un código de salida != 0."""
        cmd = [self.path]
        if serial:
            cmd += ["-s", serial]
        cmd += args
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                               input=input_data, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            return Result(124, "", f"Tiempo de espera agotado ({timeout:.0f}s)")
        except OSError as e:
            raise AdbError(str(e)) from e
        out = p.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        err = p.stderr.decode("utf-8", "replace").replace("\r\n", "\n")
        return Result(p.returncode, out.strip(), err.strip(), p.stdout)

    def shell(self, serial: str, command: str, timeout: float = 20) -> Result:
        return self.run(["shell", command], serial, timeout)

    # ------------------------------------------------------------ servidor y conexión

    def start_server(self) -> Result:
        return self.run(["start-server"], timeout=15)

    def kill_server(self) -> Result:
        return self.run(["kill-server"], timeout=15)

    def connect(self, serial: str, timeout: float = 8) -> Result:
        return self.run(["connect", serial], timeout=timeout)

    def disconnect(self, serial: str) -> Result:
        return self.run(["disconnect", serial], timeout=8)

    def pair(self, host_port: str, code: str) -> Result:
        """Emparejamiento inalámbrico (Android 11+): `adb pair IP:PUERTO CÓDIGO`."""
        return self.run(["pair", host_port, code], timeout=20)

    def devices(self) -> dict[str, str]:
        """{serial: estado} de `adb devices` (device | unauthorized | offline)."""
        r = self.run(["devices"], timeout=10)
        states: dict[str, str] = {}
        for line in r.out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                states[parts[0]] = parts[1]
        return states

    def devices_detail(self) -> list[dict[str, str]]:
        """Dispositivos que ve adb ahora mismo, con modelo: [{serial, state, model, usb}].
        Sirve para descubrir móviles/tablets conectados por USB o ya conectados por red."""
        r = self.run(["devices", "-l"], timeout=10)
        out = []
        for line in r.out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            extra = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            out.append({
                "serial": parts[0],
                "state": parts[1],
                "model": extra.get("model", "").replace("_", " "),
                # Los equipos por red aparecen como IP:PUERTO; los USB, con su nº de serie.
                "usb": "usb" in extra or not re.fullmatch(r".+:\d+", parts[0]),
            })
        # Dispositivos con depuración inalámbrica visibles en la red pero todavía no conectados.
        have = {x["serial"] for x in out}
        for s in self.mdns_services(max_age=0):
            serial = f"{s['ip']}:{s['port']}"
            if s["kind"] == "connect" and serial not in have:
                out.append({"serial": serial, "state": "mdns", "model": "", "usb": False})
        return out

    # ------------------------------------------------------------ descubrimiento mDNS (Android 11+)
    #
    # La "Depuración inalámbrica" de Android 11+ se anuncia en la red por mDNS y usa un puerto
    # ALEATORIO que cambia cada vez que se reactiva. adb lo sabe ver con `adb mdns services`:
    #   <nombre> | _adb-tls-connect._tcp | 192.168.2.50:41234   (listo para conectar)
    #   <nombre> | _adb-tls-pairing._tcp | 192.168.2.50:37051   (mostrando el código de emparejamiento)

    def mdns_services(self, max_age: float = 8.0) -> list[dict]:
        """Servicios ADB anunciados en la red: [{name, kind: connect|pairing, ip, port}].
        El resultado se cachea `max_age` s para no lanzar adb por cada dispositivo del sondeo."""
        now = time.time()
        cache = getattr(self, "_mdns_cache", None)
        if cache and now - cache[0] < max_age:
            return cache[1]
        out = []
        try:
            r = self.run(["mdns", "services"], timeout=10)
        except AdbError:
            return []
        for line in r.out.splitlines():
            # _adb-tls-connect / _adb-tls-pairing: depuración inalámbrica (Android 11+).
            # _adb._tcp: ADB por red clásico (`adb tcpip 5555`); se trata como "connect".
            m = re.match(r"^(\S+)\s+_adb(?:-tls-(connect|pairing))?\._tcp\.?\s+(\d+\.\d+\.\d+\.\d+):(\d+)", line)
            if m:
                out.append({"name": m[1], "kind": m[2] or "connect", "ip": m[3], "port": int(m[4])})
        self._mdns_cache = (now, out)
        return out

    # ------------------------------------------------------------ búsqueda en la red

    @staticmethod
    def local_subnets() -> list[str]:
        """Subredes /24 de este PC (p. ej. '192.168.2.0/24'), para proponerlas en la búsqueda."""
        ips: set[str] = set()
        try:
            ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
        try:  # IP de salida por defecto, sin enviar nada (UDP "conectado")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 9))
                ips.add(s.getsockname()[0])
        except OSError:
            pass
        nets = []
        for ip in sorted(ips):
            if ip.startswith(("127.", "169.254.")):
                continue
            n = ".".join(ip.split(".")[:3]) + ".0/24"
            if n not in nets:
                nets.append(n)
        return nets

    @staticmethod
    def scan_subnet(cidr: str, ports: tuple[int, ...] = (5555,), timeout: float = 0.5,
                    workers: int = 128, max_hosts: int = 1024) -> list[tuple[str, int]]:
        """Prueba a abrir cada puerto TCP de cada IP de la subred y devuelve [(ip, puerto)] de los
        que responden. Solo hace conexiones TCP (no envía datos). Limitado a `max_hosts` IPs para
        no barrer redes enormes por error."""
        import ipaddress
        from concurrent.futures import ThreadPoolExecutor
        net = ipaddress.ip_network(cidr, strict=False)
        if net.num_addresses > max_hosts + 2:
            raise AdbError(f"La subred {cidr} es demasiado grande (máx. {max_hosts} direcciones).")
        targets = [(str(h), p) for h in net.hosts() for p in ports]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            hits = list(ex.map(lambda t: tcp_open(t[0], t[1], timeout), targets))
        return [t for t, ok in zip(targets, hits) if ok]

    def identify(self, ip: str, port: int) -> dict:
        """Conecta a ip:puerto y lee modelo y tipo, para mostrarlo en los resultados de la búsqueda.
        Si el dispositivo aún no ha autorizado este PC, el estado será 'unauthorized' y en su
        pantalla aparecerá el aviso de «Permitir depuración»."""
        state = self.probe(ip, port)
        info = {"ip": ip, "port": port, "serial": f"{ip}:{port}", "state": state, "model": "", "kind": ""}
        if state == "device":
            info["model"] = self.getprop(info["serial"], "ro.product.model")
            info["kind"] = self.detect_kind(info["serial"])
        return info

    def mdns_port_for(self, ip: str) -> int | None:
        """Puerto actual de conexión de la depuración inalámbrica de `ip`, si se anuncia."""
        return next((s["port"] for s in self.mdns_services() if s["kind"] == "connect" and s["ip"] == ip), None)

    def probe(self, host: str, port: int) -> str:
        """Estado de un dispositivo por red: device | unauthorized | offline | unreachable.
        Intenta conectar solo si el puerto TCP responde (evita bloqueos de adb)."""
        serial = f"{host}:{port}"
        known = self.devices().get(serial)
        if known == "device":
            return "device"
        if not tcp_open(host, port):
            if known:
                self.disconnect(serial)
            return "unreachable"
        self.connect(serial, timeout=8)
        return self.devices().get(serial, "offline")

    def probe_device(self, d) -> str:
        """Estado de un `store.Device`, sea por red o por USB.
        Por USB no hay nada que conectar: basta con ver si adb lo lista."""
        if d.is_usb:
            return self.devices().get(d.serial, "unreachable")
        state = self.probe(d.host, d.port)
        if state == "unreachable":
            # Android 11+: tras reactivar la depuración inalámbrica el puerto es otro. Si el
            # dispositivo se anuncia por mDNS con un puerto distinto, se conecta y se recuerda.
            new = self.mdns_port_for(d.host)
            if new and new != d.port:
                state2 = self.probe(d.host, new)
                if state2 != "unreachable":
                    d.port = new
                    d.port_changed = True  # la UI lo guarda en devices.json
                    return state2
        return state

    # ------------------------------------------------------------ información

    def getprop(self, serial: str, key: str) -> str:
        return self.shell(serial, f"getprop {key}").out

    def detect_kind(self, serial: str) -> str:
        """Clase del dispositivo: 'tv' | 'tablet' | 'phone'.
        Usa ro.build.characteristics (p. ej. "tv", "tablet", "default") y, si no basta,
        la característica `android.software.leanback` que declaran las Android TV."""
        chars = self.getprop(serial, "ro.build.characteristics").lower()
        if "tv" in chars:
            return "tv"
        # Terminales de mano industriales (almacén, logística): no declaran nada especial en
        # las características, así que se reconocen por el fabricante. Si tu modelo no se
        # detecta, fíjalo a mano en «Editar dispositivo → Tipo».
        vendor = (self.getprop(serial, "ro.product.manufacturer") + " "
                  + self.getprop(serial, "ro.product.brand")).lower()
        if any(v in vendor for v in PDA_VENDORS):
            return "pda"
        if "tablet" in chars:
            return "tablet"
        feat = self.shell(serial, "pm has-feature android.software.leanback 2>/dev/null "
                                  "|| cmd package has-feature android.software.leanback").out
        if "true" in feat.lower():
            return "tv"
        return "phone"

    def battery(self, serial: str) -> str:
        """Nivel y estado de carga (útil en móviles/tablets). Cadena vacía si no hay batería."""
        out = self.shell(serial, "dumpsys battery").out
        level = re.search(r"level:\s*(\d+)", out)
        if not level:
            return ""
        status = re.search(r"status:\s*(\d+)", out)
        charging = {"2": " (cargando)", "5": " (llena)"}.get(status.group(1) if status else "", "")
        return f"{level.group(1)} %{charging}"

    def wifi_ip(self, serial: str) -> str:
        """IP del dispositivo en su Wi-Fi/Ethernet (para pasar de USB a red)."""
        out = self.shell(serial, "ip -o -4 addr show | grep -v ' lo '").out
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else ""

    def tcpip(self, serial: str, port: int = 5555) -> Result:
        """Activa ADB por red en un dispositivo conectado por USB (`adb tcpip PUERTO`)."""
        return self.run(["tcpip", str(port)], serial, timeout=15)

    # ------------------------------------------------------------ ADB por Wi-Fi permanente
    #
    # Sin root no se puede dejar nada en el dispositivo que se ejecute al arrancar; lo que SÍ se
    # puede (con el usuario `shell` de adb) es:
    #   · Android 11+: encender la «Depuración inalámbrica»        -> settings global adb_wifi_enabled
    #   · Cualquier Android: ADB por red clásico en el puerto fijo  -> adb tcpip 5555 (se pierde al reiniciar)
    #   · Android 11+: que la autorización no caduque (7 días)      -> settings global adb_allowed_connection_time 0

    def wifi_debug_status(self, serial: str) -> dict:
        """Estado actual: {sdk, wireless (depuración inalámbrica), tcp_port (ADB clásico, 0 si no),
        no_expiry (autorización sin caducidad)}."""
        out = self.shell(serial, "echo @@v; getprop ro.build.version.sdk; echo @@w; settings get global adb_wifi_enabled; "
                                 "echo @@p; getprop service.adb.tcp.port; echo @@t; "
                                 "settings get global adb_allowed_connection_time", timeout=20).out
        vals: dict[str, str] = {}
        key = None
        for line in out.splitlines():
            if line.startswith("@@"):
                key = line[2:]
                vals[key] = ""
            elif key:
                vals[key] = (vals[key] + " " + line).strip()
        port = vals.get("p", "")
        return {
            "sdk": int(vals["v"]) if vals.get("v", "").isdigit() else 0,
            "wireless": vals.get("w") == "1",
            "tcp_port": int(port) if port.isdigit() else 0,
            "no_expiry": vals.get("t") == "0",
        }

    def enable_wifi_debug(self, serial: str, port: int = 5555, wireless: bool = True,
                          classic: bool = True, no_expiry: bool = True) -> list[str]:
        """Activa el ADB por Wi-Fi con lo que permite cada versión. Devuelve un mensaje por paso.
        El paso `tcpip` va el último porque reinicia adbd y la conexión se corta unos segundos."""
        msgs: list[str] = []
        sdk = self.wifi_debug_status(serial)["sdk"]
        if sdk >= 30:
            # Justo tras un reinicio el servicio `settings` aún no existe ("Can't find service:
            # settings"): se espera a que Android termine de arrancar y se comprueba cada ajuste.
            self.wait_boot(serial)
            if wireless:
                # Si se activa antes de que el Wi-Fi esté asociado, Android la apaga sola (comprobado
                # en un reinicio real): se espera a que el dispositivo tenga IP.
                self.wait_wifi(serial)
                msgs.append("Depuración inalámbrica activada" if self._put_verified(serial, "adb_wifi_enabled", "1")
                            else "Depuración inalámbrica: no se pudo activar")
            if no_expiry:
                msgs.append("Autorización sin caducidad"
                            if self._put_verified(serial, "adb_allowed_connection_time", "0")
                            else "Autorización sin caducidad: no se pudo fijar")
        elif wireless or no_expiry:
            msgs.append("Android anterior a 11: no tiene depuración inalámbrica (se usa solo ADB clásico)")
        if classic:
            r = self.tcpip(serial, port)
            msgs.append(f"ADB por red en el puerto {port}" if r.ok else f"tcpip: {r.text or 'error'}")
            self.wait_ready(serial)  # adbd se reinicia: se espera a que vuelva a responder
        if sdk >= 30 and wireless:
            # Comprobación final: si el sistema la apagó por su cuenta, se reintenta una vez.
            time.sleep(self.FINAL_CHECK_DELAY)
            if not self.wifi_debug_status(serial)["wireless"]:
                ok = self._put_verified(serial, "adb_wifi_enabled", "1")
                msgs.append("Depuración inalámbrica reactivada (el sistema la había apagado)" if ok
                            else "Depuración inalámbrica: el sistema la apaga (¿Wi-Fi sin conectar?)")
        return msgs

    FINAL_CHECK_DELAY = 3  # segundos antes de la comprobación final (0 en las pruebas)

    def wait_wifi(self, serial: str, timeout: float = 60) -> bool:
        """Espera a que el dispositivo tenga IP en su Wi-Fi/Ethernet. False si se acaba el tiempo."""
        end = time.time() + timeout
        while time.time() < end:
            if self.wifi_ip(serial):
                return True
            time.sleep(2)
        return False

    def wait_boot(self, serial: str, timeout: float = 150) -> bool:
        """Espera (sin pasarse de `timeout`) a que Android termine de arrancar. Si ya arrancó, vuelve al instante."""
        end = time.time() + timeout
        while time.time() < end:
            if self.boot_completed(serial):
                return True
            time.sleep(2)
        return False

    def _put_verified(self, serial: str, key: str, value: str, tries: int = 4) -> bool:
        """`settings put global` y comprobación leyendo el valor de vuelta; reintenta si falla."""
        for i in range(tries):
            r = self.shell(serial, f"settings put global {key} {value}")
            if r.ok and not r.text and self.shell(serial, f"settings get global {key}").out.strip() == value:
                return True
            if i < tries - 1:
                time.sleep(3)
        return False

    # Segundos que adbd tarda en caer tras `tcpip`/`usb` antes de volver (se puede poner a 0 en las pruebas).
    RESTART_SETTLE = 1.5

    def wait_ready(self, serial: str, timeout: float = 25) -> bool:
        """Espera a que el dispositivo vuelva a responder a `adb shell` tras reiniciar adbd.
        `wait-for-device` solo no basta: puede volver antes de que adbd llegue a caer, y la
        siguiente orden fallaría."""
        time.sleep(self.RESTART_SETTLE)
        self.run(["wait-for-device"], serial, timeout=timeout)
        end = time.time() + timeout
        while time.time() < end:
            if self.shell(serial, "echo ok", timeout=5).out.strip() == "ok":
                return True
            time.sleep(1)
        return False

    def keeper_status(self, serial: str) -> dict:
        """Estado de ADB Keeper en el dispositivo: {installed, granted}."""
        out = self.shell(serial, f"pm list packages {KEEPER_PKG}").out
        installed = f"package:{KEEPER_PKG}" in out
        granted = False
        if installed:
            dump = self.shell(serial, f"dumpsys package {KEEPER_PKG} | grep WRITE_SECURE_SETTINGS", timeout=20).out
            granted = "granted=true" in dump
        return {"installed": installed, "granted": granted}

    def install_keeper(self, serial: str, apk: str) -> list[str]:
        """Instala ADB Keeper, le concede UNA vez el permiso WRITE_SECURE_SETTINGS (sobrevive a los
        reinicios) y lo abre una vez en silencio: Android no entrega el aviso de arranque a una app
        recién instalada que nunca se ha abierto. Después, al arrancar el dispositivo y cada 15 minutos
        con red, la propia app vuelve a encender la depuración inalámbrica si estuviera apagada.
        Requiere Android 11 o superior (la depuración inalámbrica no existe antes)."""
        msgs: list[str] = []
        sdk = self.wifi_debug_status(serial)["sdk"]
        if sdk < 30:
            return ["Android anterior a 11: no tiene depuración inalámbrica, ADB Keeper no aplica"]
        r = self.run(["install", "-r", apk], serial, timeout=120)
        if "Success" not in r.text:
            return [f"Instalación de ADB Keeper: {r.text.splitlines()[-1] if r.text else 'falló'}"]
        msgs.append("ADB Keeper instalado")
        g = self.shell(serial, f"pm grant {KEEPER_PKG} android.permission.WRITE_SECURE_SETTINGS")
        st = self.keeper_status(serial)
        msgs.append("Permiso WRITE_SECURE_SETTINGS concedido" if st["granted"]
                    else f"No se pudo conceder el permiso: {g.text or 'sin detalle'}")
        if st["granted"]:
            if self.keeper_exempt(serial):
                msgs.append("Excluido del ahorro de batería (para recibir el aviso de arranque)")
            self.shell(serial, f"am start -n {KEEPER_PKG}/.MainActivity --ez silent true")
            msgs.append("Abierto una vez para activar el arranque automático")
            # Android guarda los permisos en disco con retraso (comprobado: un reinicio a los 9 s del
            # `pm grant` perdió el permiso). Se espera y se vuelve a comprobar que sigue concedido.
            time.sleep(self.KEEPER_FLUSH_DELAY)
            self.shell(serial, "sync")
            msgs.append("Permiso guardado" if self.keeper_status(serial)["granted"]
                        else "Aviso: el permiso no se mantuvo; reintenta la instalación")
        return msgs

    KEEPER_FLUSH_DELAY = 15  # segundos que se espera tras conceder el permiso (0 en las pruebas)

    def keeper_exempt(self, serial: str) -> bool:
        """Excluye a ADB Keeper del ahorro de batería. Sin esto Android lo deja en el standby bucket «nunca
        usada» y RETIENE su aviso de arranque hasta que alguien abre la app (comprobado en un Memor 11: tras
        reiniciar no se activaba nada). La lista se conserva entre reinicios. Devuelve True si queda excluido."""
        self.shell(serial, f"cmd deviceidle whitelist +{KEEPER_PKG}")
        return KEEPER_PKG in self.shell(serial, "cmd deviceidle whitelist").out

    def ensure_keeper_permission(self, serial: str) -> bool:
        """Si ADB Keeper está instalado pero perdió el permiso o la exclusión de batería (p. ej. tras una
        instalación interrumpida o una versión anterior), lo repara. Devuelve True si hubo que repararlo."""
        st = self.keeper_status(serial)
        if not st["installed"]:
            return False
        fixed = False
        if not st["granted"]:
            self.shell(serial, f"pm grant {KEEPER_PKG} android.permission.WRITE_SECURE_SETTINGS")
            fixed = True
        if KEEPER_PKG not in self.shell(serial, "cmd deviceidle whitelist").out:
            self.keeper_exempt(serial)
            fixed = True
        if fixed:
            self.shell(serial, f"am start -n {KEEPER_PKG}/.MainActivity --ez silent true")
        return fixed

    def remove_keeper(self, serial: str) -> list[str]:
        """Desinstala ADB Keeper (deja de reactivarse la depuración inalámbrica)."""
        r = self.uninstall(serial, KEEPER_PKG)
        return ["ADB Keeper desinstalado" if "Success" in r.text else f"Desinstalación: {r.text or 'falló'}"]

    def disable_wifi_debug(self, serial: str) -> list[str]:
        """Revierte lo anterior: apaga la depuración inalámbrica y devuelve adbd al modo USB."""
        msgs = []
        if self.wifi_debug_status(serial)["sdk"] >= 30:
            self.shell(serial, "settings put global adb_wifi_enabled 0")
            self.shell(serial, "settings delete global adb_allowed_connection_time")
            msgs.append("Depuración inalámbrica desactivada")
        r = self.run(["usb"], serial, timeout=15)
        msgs.append("ADB por red desactivado" if r.ok else f"usb: {r.text or 'error'}")
        return msgs

    def has_telephony(self, serial: str) -> bool:
        """¿Tiene módem/telefonía? (móviles, PDA con 4G…). Las TVs y cajas normalmente no."""
        out = self.shell(serial, "pm has-feature android.hardware.telephony 2>/dev/null "
                                 "|| cmd package has-feature android.hardware.telephony").out
        return "true" in out.lower()

    def imei(self, serial: str) -> list[str]:
        """IMEI(s) del dispositivo (uno por ranura SIM). Sin root, Android 10+ no deja leerlo a las
        apps, pero el usuario `shell` de adb sí puede en muchos equipos mediante `service call
        iphonesubinfo` (comprobado en un Datalogic Memor 11 con Android 13). Solo se devuelven
        valores de 15 dígitos con dígito de control correcto; si el equipo no lo permite, lista vacía."""
        found: list[str] = []
        # Variantes según versión de Android: con paquete llamante (10+), sin él (≤ 9) y por ranura.
        for cmd in ("service call iphonesubinfo 1 s16 com.android.shell",
                    "service call iphonesubinfo 1",
                    "service call iphonesubinfo 3 i32 0 s16 com.android.shell",
                    "service call iphonesubinfo 3 i32 1 s16 com.android.shell",
                    "service call iphonesubinfo 2 i32 1 s16 com.android.shell"):
            val = parse_parcel_string(self.shell(serial, cmd, timeout=15).out)
            if luhn_ok(val) and val not in found:
                found.append(val)
        return found

    def device_info(self, serial: str) -> dict[str, str]:
        # Etiqueta -> propiedad de Android que se lee con getprop.
        props = {
            "Modelo": "ro.product.model",
            "Fabricante": "ro.product.manufacturer",
            "Marca": "ro.product.brand",
            "Dispositivo": "ro.product.device",
            "Android": "ro.build.version.release",
            "SDK": "ro.build.version.sdk",
            "Parche de seguridad": "ro.build.version.security_patch",
            "Compilación": "ro.build.display.id",
            "Nº de serie": "ro.serialno",
            "Idioma": "persist.sys.locale",
            "Zona horaria": "persist.sys.timezone",
        }
        cmds = {label: f"getprop {key}" for label, key in props.items()}
        cmds.update({
            "Resolución": "wm size",
            "Densidad": "wm density",
            "Tiempo encendida": "uptime",
            "Estado de energía": "dumpsys power | grep -m1 mWakefulness=",
            "Red": "ip -o -4 addr show | grep -v ' lo '",
        })
        # Todo se pide en UNA sola llamada de shell: cada comando va precedido de una línea
        # "@@Etiqueta" que luego sirve para repartir la salida. Mucho más rápido que 15 llamadas.
        script = "; ".join(f"echo '@@{label}'; {c}" for label, c in cmds.items())
        out = self.shell(serial, script, timeout=60).out
        info: dict[str, str] = {}
        label = None
        for line in out.splitlines():
            if line.startswith("@@"):
                label = line[2:]
                info[label] = ""
                continue
            if not label:
                continue
            info[label] += ("\n" if info[label] else "") + line
        # Limpieza de los prefijos que añade `wm`.
        info["Resolución"] = info.get("Resolución", "").replace("Physical size: ", "")
        info["Densidad"] = info.get("Densidad", "").replace("Physical density: ", "")
        wake = info.get("Estado de energía", "")
        info["Estado de energía"] = wake.split("=")[-1] if "=" in wake else wake
        info["MAC"] = self.mac(serial)
        info["Tipo"] = self.detect_kind(serial)
        bat = self.battery(serial)
        if bat:
            info["Batería"] = bat
        if self.has_telephony(serial):  # IMEI solo en equipos con módem
            imeis = self.imei(serial)
            if imeis:
                info["IMEI"] = " / ".join(imeis)
        return info

    def mac(self, serial: str) -> str:
        """MAC del dispositivo. Android 10+ oculta /sys/class/net a adb, así que si falla
        se consulta la caché ARP del PC solo para la IP de este dispositivo."""
        for iface in ("wlan0", "eth0"):
            r = self.shell(serial, f"cat /sys/class/net/{iface}/address 2>/dev/null")
            m = r.out.strip().lower()
            if re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", m) and m != "00:00:00:00:00:00":
                return m
        # Alternativa: la MAC que el dispositivo usa en su Wi-Fi actual (puede ser aleatoria por
        # red si el dispositivo tiene activada la privacidad de MAC).
        wifi = self.shell(serial, "dumpsys wifi | grep -m1 mWifiInfo", timeout=15).out
        m = re.search(r"MAC:\s*((?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})", wifi)
        if m and m.group(1).lower() != "02:00:00:00:00:00":
            return m.group(1).lower()
        host = serial.rsplit(":", 1)[0] if ":" in serial else self.wifi_ip(serial)
        return arp_mac(host)

    def storage(self, serial: str) -> str:
        return self.shell(serial, "df -h").out

    def memory(self, serial: str) -> str:
        return self.shell(serial, "head -n 4 /proc/meminfo").out

    def wakefulness(self, serial: str) -> str:
        """Awake | Asleep | Dozing (estado de energía de Android)."""
        r = self.shell(serial, "dumpsys power | grep -m1 mWakefulness=").out
        if "=" in r:
            return r.split("=")[-1].strip()
        return ""

    # ------------------------------------------------------------ entrada (mando)

    def keyevent(self, serial: str, key: str | int) -> Result:
        return self.shell(serial, f"input keyevent {key}")

    def text(self, serial: str, text: str) -> Result:
        # `input text` no admite espacios: se codifican como %s.
        return self.shell(serial, "input text " + shell_quote(text.replace(" ", "%s")))

    def tap(self, serial: str, x: int, y: int) -> Result:
        return self.shell(serial, f"input tap {x} {y}")

    def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> Result:
        return self.shell(serial, f"input swipe {x1} {y1} {x2} {y2} {ms}")

    def gesture(self, serial: str, name: str) -> Result:
        """Gestos habituales en móviles/tablets calculados con la resolución real de la pantalla.
        name = sentido en que se mueve el DEDO: up (dedo hacia arriba: la página baja), down,
        left, right; unlock = deslizar desde abajo hacia arriba para quitar la pantalla de bloqueo."""
        d = self.display_info(serial)
        w, h = d["width"], d["height"]
        cx, cy = w // 2, h // 2
        coords = {
            "up": (cx, int(h * 0.75), cx, int(h * 0.25)),
            "down": (cx, int(h * 0.25), cx, int(h * 0.75)),
            "left": (int(w * 0.8), cy, int(w * 0.2), cy),
            "right": (int(w * 0.2), cy, int(w * 0.8), cy),
            "unlock": (cx, int(h * 0.85), cx, int(h * 0.2)),
        }
        return self.swipe(serial, *coords[name], 350)

    # --- extras de móviles/tablets (no tienen sentido en una TV) ---

    def expand_notifications(self, serial: str) -> Result:
        """Despliega el panel de notificaciones."""
        return self.shell(serial, "cmd statusbar expand-notifications")

    def expand_quick_settings(self, serial: str) -> Result:
        """Despliega los ajustes rápidos (Wi-Fi, Bluetooth, brillo...)."""
        return self.shell(serial, "cmd statusbar expand-settings")

    def collapse_panels(self, serial: str) -> Result:
        return self.shell(serial, "cmd statusbar collapse")

    def rotate(self, serial: str, rotation: int | None) -> Result:
        """Fija la orientación (0 vertical, 1 horizontal, 2 vertical invertida, 3 horizontal
        invertida) o, con None, devuelve el control al giro automático."""
        if rotation is None:
            return self.shell(serial, "settings put system accelerometer_rotation 1")
        return self.shell(serial, "settings put system accelerometer_rotation 0; "
                                  f"settings put system user_rotation {int(rotation) % 4}")

    def set_brightness(self, serial: str, level: int) -> Result:
        """Brillo 0-255 (desactiva el modo automático para que se respete)."""
        level = max(0, min(255, int(level)))
        return self.shell(serial, "settings put system screen_brightness_mode 0; "
                                  f"settings put system screen_brightness {level}")

    # --- navegación web ---

    def open_url(self, serial: str, url: str, package: str = "") -> Result:
        """Abre `url` en el navegador `package` o, si va vacío, en el predeterminado del sistema."""
        target = f" -p {shell_quote(package)}" if package else ""
        r = self.shell(serial, f"am start -a android.intent.action.VIEW -d {shell_quote(url)}{target}",
                       timeout=30)
        if "Error" in r.text or "unable to resolve" in r.text.lower():
            raise AdbError(r.text.splitlines()[-1] if r.text else
                           "No hay ninguna app que pueda abrir enlaces web en este dispositivo")
        return r

    def screencap(self, serial: str) -> bytes:
        """PNG de la pantalla. Algunas dispositivos anteponen texto de diagnóstico: se descarta."""
        r = self.run(["exec-out", "screencap", "-p"], serial, timeout=20)
        i = r.raw.find(_PNG_SIG)
        if i < 0:
            raise AdbError("El dispositivo no devolvió una imagen válida (¿pantalla protegida o apagado?)")
        return r.raw[i:]

    # ------------------------------------------------------------ aplicaciones

    def packages(self, serial: str, scope: str = "-3") -> list[str]:
        """scope: '-3' (terceros), '-s' (sistema) o '' (todos)."""
        r = self.shell(serial, f"pm list packages {scope}".strip(), timeout=30)
        return sorted(l.split(":", 1)[1].strip() for l in r.out.splitlines()
                      if l.startswith("package:"))

    def launch(self, serial: str, package: str) -> Result:
        """Abre una app por su paquete. Se prueba primero el lanzador de Android TV
        (LEANBACK) y después el de móviles/tablets (LAUNCHER) con `monkey`; si ninguno
        encuentra actividad, se resuelve la actividad principal y se lanza con `am start`."""
        for cat in ("android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER"):
            r = self.shell(serial, f"monkey -p {package} -c {cat} 1")
            if "No activities found" not in r.out and "monkey aborted" not in r.out:
                return r
        comp = self._resolve_launcher(serial, package)
        if comp:
            return self.shell(serial, f"am start -n {shell_quote(comp)}")
        return r

    def _resolve_launcher(self, serial: str, package: str) -> str:
        """'paquete/actividad' del lanzador de la app, o '' si no se encuentra."""
        out = self.shell(
            serial,
            f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {package}",
        ).out
        last = out.strip().splitlines()[-1] if out.strip() else ""
        return last if "/" in last and not last.startswith("No ") else ""

    def is_user_package(self, serial: str, package: str) -> bool:
        """¿Es una app instalada por el usuario (no del sistema)? Las del sistema están protegidas."""
        return package in self.packages(serial, "-3")

    def force_stop(self, serial: str, package: str) -> Result:
        return self.shell(serial, f"am force-stop {package}")

    def clear_data(self, serial: str, package: str) -> Result:
        return self.shell(serial, f"pm clear {package}")

    def uninstall(self, serial: str, package: str) -> Result:
        return self.run(["uninstall", package], serial, timeout=60)

    def install(self, serial: str, apk: str) -> Result:
        return self.run(["install", "-r", apk], serial, timeout=600)

    def install_any(self, serial: str, path: str, replace: bool = True) -> Result:
        """Instala un .apk, o un paquete dividido (.apks / .xapk / .apkm = ZIP con varios .apk,
        que se instalan juntos con `install-multiple`)."""
        import tempfile
        import zipfile
        p = Path(path)
        if not p.is_file():
            return Result(1, "", f"No existe el archivo: {path}")
        flags = ["-r"] if replace else []
        if p.suffix.lower() == ".apk":
            return self.run(["install", *flags, str(p)], serial, timeout=600)
        if p.suffix.lower() in (".apks", ".xapk", ".apkm"):
            with tempfile.TemporaryDirectory(prefix="atvm_apks_") as tmp:
                try:
                    with zipfile.ZipFile(p) as z:
                        parts = [n for n in z.namelist() if n.lower().endswith(".apk")]
                        if not parts:
                            return Result(1, "", "El paquete no contiene archivos .apk")
                        for n in parts:  # extracción segura: solo el nombre base, sin rutas
                            (Path(tmp) / Path(n).name).write_bytes(z.read(n))
                except zipfile.BadZipFile:
                    return Result(1, "", "El archivo no es un paquete válido (ZIP corrupto)")
                files = sorted(str(f) for f in Path(tmp).glob("*.apk"))
                return self.run(["install-multiple", *flags, *files], serial, timeout=900)
        return Result(1, "", f"Formato no admitido: {p.suffix} (usa .apk, .apks, .xapk o .apkm)")

    def open_settings(self, serial: str, action: str) -> Result:
        return self.shell(serial, f"am start -a {action}")

    def foreground(self, serial: str) -> tuple[str, str]:
        """(estado de energía, paquete en primer plano) en una sola llamada."""
        out = self.shell(
            serial,
            "dumpsys power | grep -m1 mWakefulness=; echo @@; "
            "dumpsys activity activities | grep -m1 -E 'topResumedActivity|mResumedActivity'",
            timeout=30,
        ).out
        wake_part, _, act_part = out.partition("@@")
        wake = wake_part.split("=")[-1].strip() if "=" in wake_part else ""
        # La línea contiene "... u0 com.paquete/.Actividad ...": se extrae el paquete.
        m = re.search(r"\bu\d+\s+([\w.]+)/", act_part)
        return (wake, m.group(1)) if m else (wake, "")

    # ------------------------------------------------------------ pantalla

    def display_info(self, serial: str) -> dict[str, int]:
        """Resolución física y densidad (física y actual) de la pantalla."""
        out = self.shell(serial, "wm size; wm density").out
        info = {"width": 1920, "height": 1080, "physical_dpi": 0, "current_dpi": 0}
        m = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
        if m:
            info["width"], info["height"] = int(m[1]), int(m[2])
        m = re.search(r"Physical density:\s*(\d+)", out)
        if m:
            info["physical_dpi"] = info["current_dpi"] = int(m[1])
        # Si hay una densidad forzada, "Override density" manda sobre la física.
        m = re.search(r"Override density:\s*(\d+)", out)
        if m:
            info["current_dpi"] = int(m[1])
        return info

    def set_density(self, serial: str, dpi: int) -> Result:
        if not 72 <= dpi <= 960:
            raise AdbError("La densidad debe estar entre 72 y 960 dpi")
        return self.shell(serial, f"wm density {dpi}")

    def reset_density(self, serial: str) -> Result:
        return self.shell(serial, "wm density reset")

    def boot_completed(self, serial: str) -> bool:
        return self.getprop(serial, "sys.boot_completed").strip() == "1"

    # ------------------------------------------------------------ kiosco

    def kiosk_launch(self, serial: str, url: str, package: str) -> Result:
        """Abre `url` en la app kiosco (intent VIEW). Fully se abre a pantalla completa."""
        target = (f"-n {package}/de.ozerov.fully.MainActivity" if package in FULLY_PACKAGES
                  else f"-p {shell_quote(package)}")
        r = self.shell(
            serial,
            f"am start -a android.intent.action.VIEW -d {shell_quote(url)} {target}",
            timeout=30,
        )
        if "Error" in r.text or "Exception" in r.text:
            raise AdbError(r.text.splitlines()[-1] if r.text else "am start falló")
        return r

    def resolve_on_tv(self, serial: str, host: str) -> tuple[str | None, str]:
        """(IP, salida de ping). IP=None si el dispositivo no resuelve el nombre."""
        r = self.shell(serial, f"ping -c 1 -W 3 {shell_quote(host)} 2>&1 | head -n 3", timeout=20)
        m = re.search(r"PING \S+ \(([\d.]+)\)", r.out)
        if m:
            return m.group(1), r.out
        return None, r.out

    def http_status_from_tv(self, serial: str, ip: str, host: str, port: int, path: str) -> str:
        # Petición HTTP/1.0 a mano con toybox nc (viene en Android 8+), sin curl.
        req = f"GET {path} HTTP/1.0\\r\\nHost: {host}\\r\\n\\r\\n"
        cmd = (f"printf {shell_quote(req)} | toybox nc -w 5 {shell_quote(ip)} {port} | head -n 1")
        return self.shell(serial, cmd, timeout=20).out.strip()

    # ------------------------------------------------------------ ajustes del sistema

    def settings_list(self, serial: str, namespace: str) -> dict[str, str]:
        r = self.shell(serial, f"settings list {namespace}", timeout=30)
        out: dict[str, str] = {}
        for line in r.out.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k] = v
        return out

    def settings_put(self, serial: str, namespace: str, key: str, value: str) -> Result:
        return self.shell(serial, f"settings put {namespace} {shell_quote(key)} {shell_quote(value)}")

    # ------------------------------------------------------------ archivos

    def ls(self, serial: str, path: str) -> list[tuple[str, bool, str, str]]:
        """Devuelve [(nombre, es_dir, tamaño, fecha)]."""
        path = path.rstrip("/") + "/"
        r = self.shell(serial, f"ls -la {shell_quote(path)}", timeout=20)
        if not r.ok and not r.out:
            raise AdbError(r.err or "No se pudo listar la carpeta")
        entries = []
        for line in r.out.splitlines():
            # Formato de `ls -la` de toybox: permisos, enlaces, dueño, grupo, tamaño, fecha, nombre.
            m = re.match(
                r"^([\-dlbcps][rwxsStT\-]{9})\s+\d+\s+\S+\s+\S+\s+(\d+)?\s*"
                r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+(.+)$",
                line,
            )
            if not m:
                continue
            perms, size, date, name = m.groups()
            if name in (".", ".."):
                continue
            is_dir = perms.startswith("d") or (perms.startswith("l") and name.endswith("/"))
            # Un enlace simbólico se trata como carpeta (p. ej. /sdcard -> /storage/emulated/0).
            if perms.startswith("l") and " -> " in name:
                name = name.split(" -> ")[0]
                is_dir = True
            entries.append((name, is_dir, size or "", date))
        entries.sort(key=lambda e: (not e[1], e[0].lower()))  # carpetas primero, luego A-Z
        return entries

    def pull(self, serial: str, remote: str, local: str) -> Result:
        return self.run(["pull", remote, local], serial, timeout=600)

    def push(self, serial: str, local: str, remote: str) -> Result:
        return self.run(["push", local, remote], serial, timeout=600)

    def remove(self, serial: str, remote: str) -> Result:
        return self.shell(serial, f"rm -rf {shell_quote(remote)}")

    # ------------------------------------------------------------ energía

    def reboot(self, serial: str) -> Result:
        return self.run(["reboot"], serial, timeout=10)

    def power_off(self, serial: str) -> Result:
        """Apaga el dispositivo. `reboot -p` funciona en la mayoría de dispositivos/cajas; en muchos
        móviles sin root falla y se prueba `svc power shutdown` (puede requerir permisos)."""
        r = self.shell(serial, "reboot -p")
        if r.ok and "not permitted" not in r.text.lower() and "denied" not in r.text.lower():
            return r
        return self.shell(serial, "svc power shutdown")


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
