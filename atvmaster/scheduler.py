"""Tareas programadas y avisos de caída.

- Programación: acciones a una hora y unos días (encender, standby, aplicar kiosco, aplicar un
  perfil de preparación, reiniciar). Se evalúan cada minuto MIENTRAS la aplicación está abierta:
  no es un servicio de Windows. Si el PC o la app están apagados a esa hora, no se ejecutan.
- Avisos: si un dispositivo que estaba en línea deja de responder durante varios sondeos
  seguidos, se avisa (registro, bandeja del sistema y, opcionalmente, un webhook); y se avisa
  de nuevo cuando se recupera.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

DAY_NAMES = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")

# acción -> texto para mostrar. "reboot" reinicia equipos: se pide confirmar al crearla.
ACTIONS = {
    "wake": "Encender / despertar",
    "sleep": "Standby (apagar pantalla)",
    "kiosk": "Aplicar la URL de kiosco guardada",
    "profile": "Aplicar un perfil de preparación",
    "reboot": "Reiniciar",
}


@dataclass
class Schedule:
    """Una tarea programada. Se guarda en settings.json (clave "schedules")."""

    name: str
    time: str                                   # "HH:MM" (24 h)
    action: str                                 # clave de ACTIONS
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # 0=lunes … 6=domingo
    targets: str = "all"                        # "all" | "group:<nombre>" | "ids:<id>,<id>"
    profile: str = ""                           # nombre del perfil si action == "profile"
    enabled: bool = True
    last_run: str = ""                          # "YYYY-MM-DD HH:MM" del último disparo (evita repetir)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def validate(self) -> None:
        try:
            datetime.strptime(self.time, "%H:%M")
        except ValueError:
            raise ValueError("La hora debe tener el formato HH:MM (24 h)") from None
        if self.action not in ACTIONS:
            raise ValueError("Acción desconocida")
        if not self.days or any(d not in range(7) for d in self.days):
            raise ValueError("Elige al menos un día de la semana")
        if self.action == "profile" and not self.profile:
            raise ValueError("Elige el perfil que se aplicará")

    def describe(self) -> str:
        days = "Todos los días" if len(self.days) == 7 else ", ".join(DAY_NAMES[d] for d in sorted(self.days))
        what = ACTIONS.get(self.action, self.action) + (f" «{self.profile}»" if self.profile else "")
        return f"{self.time} · {days} · {what} · {describe_targets(self.targets)}"


def describe_targets(targets: str) -> str:
    if targets == "all":
        return "todos los dispositivos"
    if targets.startswith("group:"):
        return f"grupo «{targets[6:]}»"
    return "dispositivos elegidos"


def load(raw: list[dict]) -> list[Schedule]:
    """Lee las tareas de settings.json ignorando campos desconocidos o entradas dañadas."""
    known = set(Schedule.__dataclass_fields__)
    out = []
    for d in raw or []:
        try:
            s = Schedule(**{k: v for k, v in d.items() if k in known})
            s.validate()
            out.append(s)
        except (TypeError, ValueError):
            continue
    return out


def dump(items: list[Schedule]) -> list[dict]:
    return [asdict(s) for s in items]


def is_due(s: Schedule, now: datetime) -> bool:
    """¿Toca ejecutarla ahora? Coincide la hora y el día, y no se ha lanzado ya en este minuto."""
    return (s.enabled and now.weekday() in s.days and now.strftime("%H:%M") == s.time
            and s.last_run != now.strftime("%Y-%m-%d %H:%M"))


def mark_run(s: Schedule, now: datetime) -> None:
    s.last_run = now.strftime("%Y-%m-%d %H:%M")


def resolve_targets(s: Schedule, devices: list) -> list:
    """Dispositivos a los que afecta la tarea."""
    if s.targets == "all":
        return list(devices)
    if s.targets.startswith("group:"):
        g = s.targets[6:].lower()
        return [d for d in devices if d.group.lower() == g]
    if s.targets.startswith("ids:"):
        ids = set(s.targets[4:].split(","))
        return [d for d in devices if d.id in ids]
    return []


# ------------------------------------------------------------------ avisos

class AlertTracker:
    """Detecta caídas y recuperaciones a partir de los estados de cada sondeo.

    Un dispositivo solo genera avisos si alguna vez se vio en línea (así un equipo apagado que
    se acaba de añadir no llena de avisos) y la caída se confirma tras `threshold` sondeos
    seguidos sin respuesta (evita falsos avisos por un fallo puntual de Wi-Fi)."""

    def __init__(self, threshold: int = 3):
        self.threshold = max(1, threshold)
        self._seen_up: set[str] = set()
        self._down: dict[str, int] = {}
        self._alerted: set[str] = set()

    def update(self, dev_id: str, state: str) -> str | None:
        """Devuelve "down" (caída confirmada), "up" (recuperado) o None."""
        if state == "device":
            self._seen_up.add(dev_id)
            self._down.pop(dev_id, None)
            if dev_id in self._alerted:
                self._alerted.discard(dev_id)
                return "up"
            return None
        if dev_id not in self._seen_up:
            return None
        n = self._down.get(dev_id, 0) + 1
        self._down[dev_id] = n
        if n >= self.threshold and dev_id not in self._alerted:
            self._alerted.add(dev_id)
            return "down"
        return None


def format_alert(kind: str, name: str, extra: str = "") -> str:
    hora = datetime.now().strftime("%H:%M")
    if kind == "down":
        return f"🔴 {name} no responde desde las {hora}{(' — ' + extra) if extra else ''}"
    return f"🟢 {name} vuelve a estar en línea ({hora})"


def post_webhook(url: str, text: str, timeout: float = 8) -> None:
    """Envía el aviso a un webhook (Teams, Slack, Discord o similar) con JSON {"text": ...}.
    Para Telegram usa la URL https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>.
    Lanza ValueError si la URL no es http(s) y OSError si falla el envío."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("El webhook debe ser una URL http:// o https://")
    payload: dict = {"text": text}
    if "api.telegram.org" in u.netloc:
        q = urllib.parse.parse_qs(u.query)
        payload = {"chat_id": (q.get("chat_id") or [""])[0], "text": text}
        url = urllib.parse.urlunparse(u._replace(query=""))
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": "AndroidTvMaster"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read(256)
