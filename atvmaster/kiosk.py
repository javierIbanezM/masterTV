"""Modo kiosco: mantener una URL a pantalla completa en cada dispositivo.

Mecanismos (de más a menos persistente):
 1. Fully Kiosk con Administración remota activa (puerto 2323): se guarda la «URL de inicio» y
    «Lanzar al arrancar» dentro de Fully, de modo que el dispositivo arranca el kiosco solo.
 2. Intent VIEW por ADB: abre la URL en Fully (o en la app indicada) a pantalla completa.
    Lo dispara esta aplicación: al encender el dispositivo, al detectar que arranca, o con el vigilante.
"""
from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .adb import FULLY_PACKAGES, Adb, AdbError, tcp_open
from .store import Device

FULLY_PKG = "de.ozerov.fully"
FULLY_PORT = 2323


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("La URL está vacía")
    if "://" not in url:
        url = "http://" + url
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("La URL debe empezar por http:// o https:// e incluir un servidor")
    if any(c.isspace() for c in url):
        raise ValueError("La URL no puede contener espacios")
    return url


def split_url(url: str) -> tuple[str, str, int, str]:
    p = urllib.parse.urlparse(normalize_url(url))
    port = p.port or (443 if p.scheme == "https" else 80)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    return p.scheme, p.hostname, port, path


def pc_resolve(host: str) -> tuple[str, str] | None:
    """(FQDN, IP) según el DNS del PC, que sí conoce los sufijos de búsqueda."""
    try:
        info = socket.getaddrinfo(host, None, socket.AF_INET, 0, 0, socket.AI_CANONNAME)
    except OSError:
        return None
    return (info[0][3] or host, info[0][4][0])


def fully_rest(ip: str, cmd: str, password: str = "", timeout: float = 5, **params) -> str:
    q = {"cmd": cmd, **params}
    if password:
        q["password"] = password
    url = f"http://{ip}:{FULLY_PORT}/?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise AdbError(f"Fully REST: {e.reason}") from e
    low = body.lower()
    if any(w in low for w in ("wrong password", "error", "denied", "not allowed")):
        raise AdbError("Fully REST rechazó el comando (¿contraseña de administración incorrecta?)")
    return body


class KioskService:
    def __init__(self, adb: Adb, log: Callable[[str], None]):
        self.adb, self.log = adb, log
        # Dispositivos con una operación de kiosco en curso: evita que el sondeo, el vigilante y
        # los botones lancen dos operaciones a la vez sobre el mismo equipo.
        self._busy: set[str] = set()
        self._lock = threading.Lock()

    def try_begin(self, dev_id: str) -> bool:
        """Reserva el dispositivo; False si ya hay otra operación en curso. Pareja de end()."""
        with self._lock:
            if dev_id in self._busy:
                return False
            self._busy.add(dev_id)
            return True

    def end(self, dev_id: str) -> None:
        with self._lock:
            self._busy.discard(dev_id)

    def apply(self, d: Device) -> list[str]:
        """Pone la URL del kiosco en pantalla. Devuelve mensajes para el registro."""
        url = normalize_url(d.kiosk_url)
        msgs: list[str] = []
        if d.kiosk_density:
            cur = self.adb.display_info(d.serial)["current_dpi"]
            if cur != d.kiosk_density:
                self.adb.set_density(d.serial, d.kiosk_density)
                msgs.append(f"Zoom: densidad {cur} → {d.kiosk_density} dpi")
                time.sleep(3)
        # Mecanismo 1: REST de Fully (persistente). Necesita la IP del dispositivo, por eso no se
        # intenta con dispositivos conectados por USB (d.ip está vacía).
        rest_ok = False
        if d.kiosk_package in FULLY_PACKAGES and d.ip and tcp_open(d.ip, FULLY_PORT, 1.5):
            try:
                pw = d.fully_password
                fully_rest(d.ip, "setStringSetting", pw, key="startURL", value=url)
                fully_rest(d.ip, "setBooleanSetting", pw, key="launchOnBoot", value="true")
                fully_rest(d.ip, "setBooleanSetting", pw, key="keepScreenOn", value="true")
                fully_rest(d.ip, "loadStartURL", pw)
                fully_rest(d.ip, "toForeground", pw)
                msgs.append("Fully: URL de inicio y «lanzar al arrancar» guardadas en el dispositivo")
                rest_ok = True
            except AdbError as e:
                msgs.append(f"{e}; se usa el intent por ADB")
        # Mecanismo 2: intent VIEW por ADB (no persiste tras reiniciar; lo relanza la app).
        if not rest_ok:
            self.adb.kiosk_launch(d.serial, url, d.kiosk_package)
            msgs.append(f"Kiosco lanzado por ADB ({d.kiosk_package}) → {url}")
        return msgs

    def wait_online(self, d: Device, timeout: float = 150) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.adb.probe_device(d) == "device":
                return True
            time.sleep(5)
        return False

    def when_ready(self, d: Device, wait_adb: bool = True) -> str:
        """Espera a que el dispositivo termine de arrancar y aplica el kiosco."""
        if not self.try_begin(d.id):
            return "ya hay un arranque de kiosco en curso"
        try:
            if wait_adb and not self.wait_online(d):
                return "el dispositivo no respondió por ADB a tiempo; kiosco no lanzado"
            # Espera (máx. 90 s) a que Android termine de arrancar y 8 s más a que el launcher
            # y la red estén listos; lanzar antes hace que la URL falle o se pierda.
            end = time.time() + 90
            while time.time() < end and not self.adb.boot_completed(d.serial):
                time.sleep(4)
            time.sleep(8)
            return "; ".join(self.apply(d))
        except (AdbError, ValueError) as e:
            return f"error: {e}"
        finally:
            self.end(d.id)

    def watchdog_check(self, d: Device) -> str | None:
        """Relanza el kiosco si el dispositivo está despierto y otra app tiene el primer plano."""
        if not self.try_begin(d.id):
            return None
        try:
            wake, pkg = self.adb.foreground(d.serial)
            if wake != "Awake" or not pkg or pkg == d.kiosk_package:
                return None
            msgs = self.apply(d)
            return f"Vigilante: en pantalla estaba {pkg}; " + "; ".join(msgs)
        except (AdbError, ValueError) as e:
            return f"Vigilante: error: {e}"
        finally:
            self.end(d.id)

    def diagnose(self, d: Device) -> tuple[str, bool]:
        """Informe de red hecho DESDE EL DISPOSITIVO. Devuelve (texto, dns_falla)."""
        _, host, port, path = split_url(d.kiosk_url)
        scheme = split_url(d.kiosk_url)[0]
        lines = [f"URL: {d.kiosk_url}", f"Servidor: {host}:{port}"]
        ip, ping_out = self.adb.resolve_on_tv(d.serial, host)
        dns_fail = ip is None
        pc = pc_resolve(host)
        if dns_fail:
            lines.append(f"✖ El dispositivo NO resuelve «{host}».")
            if pc:
                lines.append(f"  El PC sí lo resuelve: {pc[0]} → {pc[1]}")
                if "." not in host and pc[0].lower() != host.lower():
                    lines.append(
                        f"  El dispositivo no usa el sufijo DNS del PC. Prueba con el nombre completo: {pc[0]}"
                    )
            mode = self.adb.shell(d.serial, "settings get global private_dns_mode").out.strip()
            lines.append(f"  DNS privado del dispositivo: {mode or 'automático (por defecto)'}")
            if mode in ("", "null", "opportunistic"):
                lines.append(
                    "  → El DNS privado automático envía las consultas a un DNS público y puede "
                    "ignorar el DNS interno. Desactivarlo suele solucionarlo."
                )
            return "\n".join(lines), True
        lines.append(f"✔ El dispositivo resuelve {host} → {ip}")
        if "1 received" in ping_out or "bytes from" in ping_out:
            lines.append("✔ Ping a la IP del servidor: responde")
        else:
            lines.append("⚠ Ping sin respuesta (puede estar filtrado por el firewall)")
        if scheme == "http":
            status = self.adb.http_status_from_tv(d.serial, ip, host, port, path)
            lines.append(f"{'✔' if status.startswith('HTTP') else '⚠'} Respuesta HTTP desde el dispositivo: "
                         f"{status or 'sin respuesta'}")
        else:
            lines.append("ℹ HTTPS: no se comprueba la respuesta HTTP desde el dispositivo.")
        return "\n".join(lines), False
