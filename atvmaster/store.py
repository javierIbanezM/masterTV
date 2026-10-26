"""Persistencia de dispositivos y ajustes de la app (JSON en %APPDATA%)."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field

from . import paths

# Tipos de dispositivo que entiende la app. "auto" = se detecta por ADB al abrir "Resumen".
KINDS = ("auto", "tv", "phone", "tablet", "box", "pda")
KIND_LABELS = {
    "auto": "Detectar automáticamente",
    "tv": "Android TV / Google TV",
    "box": "Caja / reproductor Android",
    "tablet": "Tablet",
    "phone": "Móvil",
    "pda": "Terminal de mano / PDA (Datalogic, Zebra, Honeywell…)",
}
# Formas de conectar: por red (adb connect IP:PUERTO) o por cable (nº de serie USB).
TRANSPORTS = ("wifi", "usb")


@dataclass
class Device:
    """Un dispositivo Android. Se guarda tal cual en devices.json."""

    name: str
    host: str                   # IP/host (wifi) o nº de serie (usb)
    port: int = 5555            # solo se usa con transport="wifi"
    mac: str = ""               # opcional: necesaria solo para Wake-on-LAN
    group: str = ""             # texto libre para agrupar en la lista
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # --- Compatibilidad con cualquier dispositivo (añadido en 1.1) ---
    kind: str = "auto"          # ver KINDS ("auto" = decidir por detección)
    transport: str = "wifi"     # ver TRANSPORTS
    detected_kind: str = ""     # último tipo detectado por ADB (se guarda para tener menú offline)
    keep_wifi_adb: bool = False  # reactivar el ADB por Wi-Fi cada vez que se conecte por USB

    # --- Modo kiosco ---
    kiosk_url: str = ""
    kiosk_package: str = "de.ozerov.fully"
    kiosk_on_power_on: bool = True
    kiosk_watchdog: bool = False
    fully_password: str = ""
    kiosk_density: int = 0      # 0 = no tocar la densidad

    @property
    def effective_kind(self) -> str:
        """Tipo que decide el menú: el elegido a mano, o el detectado, o "auto" si aún se ignora."""
        if self.kind != "auto":
            return self.kind
        return self.detected_kind or "auto"

    @property
    def is_usb(self) -> bool:
        return self.transport == "usb"

    @property
    def serial(self) -> str:
        """Identificador que se pasa a `adb -s`: IP:puerto (red) o nº de serie (USB)."""
        return self.host if self.is_usb else f"{self.host}:{self.port}"

    @property
    def ip(self) -> str:
        """IP utilizable para WoL / REST de Fully. Vacía si el dispositivo va por USB."""
        return "" if self.is_usb else self.host

    @property
    def address(self) -> str:
        """Texto corto para mostrar en la lista."""
        return f"USB {self.host}" if self.is_usb else f"{self.host}:{self.port}"


class DeviceStore:
    """Lista de dispositivos persistida en devices.json."""

    def __init__(self):
        self.path = paths.data_dir() / "devices.json"
        self.devices: list[Device] = []
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            # Se descartan claves desconocidas: así un devices.json de otra versión no rompe la carga.
            known = set(Device.__dataclass_fields__)
            self.devices = [Device(**{k: v for k, v in d.items() if k in known}) for d in raw]
        except (OSError, ValueError, TypeError):
            self.devices = []

    def save(self) -> None:
        # Escritura atómica: se escribe un .tmp y se renombra, para no dejar el JSON a medias.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(d) for d in self.devices], indent=2,
                                  ensure_ascii=False), "utf-8")
        tmp.replace(self.path)

    def add(self, d: Device) -> None:
        self.devices.append(d)
        self.save()

    def update(self, d: Device) -> None:
        for i, x in enumerate(self.devices):
            if x.id == d.id:
                self.devices[i] = d
        self.save()

    def remove(self, device_id: str) -> None:
        self.devices = [d for d in self.devices if d.id != device_id]
        self.save()

    def get(self, device_id: str) -> Device | None:
        return next((d for d in self.devices if d.id == device_id), None)

    def find_serial(self, serial: str) -> Device | None:
        """Dispositivo ya guardado que corresponde a ese serial de adb."""
        return next((d for d in self.devices if d.serial == serial), None)


class Settings:
    """Ajustes de la aplicación (settings.json). Las claves ausentes toman DEFAULTS."""

    DEFAULTS = {
        "adb_path": "",
        "scrcpy_path": "",
        "capture_dir": "",
        "poll_seconds": 10,
        "auto_connect": True,
        "bookmarks": [],   # favoritos de la pestaña Navegar: [{"name":..., "url":...}]
        "profiles": {},    # perfiles de preparación: {nombre: texto}  (ver prep.py)
        "schedules": [],   # tareas programadas (ver scheduler.py)
        "alerts_enabled": False,   # avisos de caída/recuperación
        "alerts_threshold": 3,     # sondeos seguidos sin respuesta antes de avisar
        "alerts_tray": True,       # notificación de Windows
        "alerts_webhook": "",      # URL de webhook (opcional)
    }

    def __init__(self):
        self.path = paths.data_dir() / "settings.json"
        self.values = dict(self.DEFAULTS)
        try:
            self.values.update(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError):
            return

    def get(self, key):
        return self.values.get(key, self.DEFAULTS.get(key))

    def set(self, key, value) -> None:
        self.values[key] = value
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.values, indent=2, ensure_ascii=False), "utf-8")
