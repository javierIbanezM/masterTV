"""Perfiles de preparación: una lista de pasos que se aplica a uno o varios dispositivos
(instalar apps, dar permisos, fijar ajustes, URL de kiosco…) para dejarlos listos con un clic.

El perfil es texto, un paso por línea (las líneas que empiezan por # son comentarios):

    setting global stay_on_while_plugged_in 7     # ajuste del sistema (global|secure|system)
    stayawake on                                   # no apagar la pantalla al cargar (on|off)
    timeout 10m                                    # apagado de pantalla: 30s, 5m, 1h, never
    animations 0.5                                 # escala de animaciones: 0, 0.5 o 1
    brightness 150                                 # brillo 0-255
    rotation auto                                  # 0, 1, 2, 3 o auto
    density 320                                    # o: density reset
    install C:\\apks\\mi_app.apk                     # .apk / .apks / .xapk / .apkm
    uninstall com.ejemplo.app                      # solo apps de usuario (las del sistema están protegidas)
    grant com.ejemplo.app android.permission.CAMERA
    launch com.ejemplo.app
    kiosk http://servidor/visor.php com.fullykiosk.emm   # guarda la URL en el dispositivo (la app)
    keeper                                         # instala ADB Keeper: depuración inalámbrica siempre activa (Android 11+)
    wake | home

Cada paso se valida al leerlo (formato, nombres de paquete y de permiso, rangos). No existe un
paso para ejecutar comandos arbitrarios: es deliberado, para que un perfil compartido no pueda
hacer nada que no esté en esta lista.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import kiosk, paths

_PKG = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
_PERM = re.compile(r"^[A-Za-z0-9_.]+$")
_KEY = re.compile(r"^[A-Za-z0-9_.]+$")
_VAL = re.compile(r"^[A-Za-z0-9_.:/+,\-]*$")

EXAMPLE = """# Perfil de ejemplo: terminal de almacén
stayawake on
timeout 10m
animations 0.5
# install C:\\apks\\mi_app.apk
# grant com.ejemplo.app android.permission.CAMERA
# kiosk http://servidorwebs.zar.local/Planificador/visordealmacen.php com.fullykiosk.emm
"""


class ProfileError(ValueError):
    """Línea no válida en un perfil (el mensaje incluye el número de línea)."""


@dataclass
class Step:
    name: str
    args: list[str]
    line: int = 0

    def __str__(self) -> str:
        return " ".join([self.name, *self.args])


def _timeout_ms(text: str) -> int:
    t = text.lower()
    if t in ("never", "nunca"):
        return 86_400_000
    m = re.fullmatch(r"(\d+)\s*(s|m|h)", t)
    if not m:
        raise ValueError("usa 30s, 5m, 1h o never")
    ms = int(m[1]) * {"s": 1000, "m": 60_000, "h": 3_600_000}[m[2]]
    if not 5_000 <= ms <= 86_400_000:
        raise ValueError("el tiempo debe estar entre 5 s y 24 h")
    return ms


def parse(text: str) -> list[Step]:
    """Valida y convierte el texto de un perfil en pasos. Lanza ProfileError con la línea."""
    steps: list[Step] = []
    for n, raw in enumerate(text.splitlines(), 1):
        # Un "#" abre un comentario si está al inicio o tras un espacio (así no rompe rutas con #).
        line = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()
        if not line:
            continue
        name, _, rest = line.partition(" ")
        name, rest = name.lower(), rest.strip()
        try:
            args = _check(name, rest)
        except ValueError as e:
            raise ProfileError(f"Línea {n} («{raw.strip()}»): {e}") from None
        steps.append(Step(name, args, n))
    return steps


def _check(name: str, rest: str) -> list[str]:
    a = rest.split()
    if name == "setting":
        if len(a) != 3 or a[0] not in ("global", "secure", "system"):
            raise ValueError("formato: setting global|secure|system CLAVE VALOR")
        if not _KEY.match(a[1]) or not _VAL.match(a[2]):
            raise ValueError("clave o valor con caracteres no permitidos")
        return a
    if name == "stayawake":
        if a not in (["on"], ["off"]):
            raise ValueError("usa stayawake on|off")
        return a
    if name == "timeout":
        if len(a) != 1:
            raise ValueError("formato: timeout 30s|5m|1h|never")
        return [str(_timeout_ms(a[0]))]
    if name == "animations":
        if a not in (["0"], ["0.5"], ["1"]):
            raise ValueError("usa animations 0, 0.5 o 1")
        return a
    if name == "brightness":
        if len(a) != 1 or not a[0].isdigit() or not 0 <= int(a[0]) <= 255:
            raise ValueError("brillo entre 0 y 255")
        return a
    if name == "rotation":
        if a not in (["0"], ["1"], ["2"], ["3"], ["auto"]):
            raise ValueError("usa rotation 0, 1, 2, 3 o auto")
        return a
    if name == "density":
        if a == ["reset"]:
            return a
        if len(a) != 1 or not a[0].isdigit() or not 72 <= int(a[0]) <= 960:
            raise ValueError("densidad entre 72 y 960, o reset")
        return a
    if name in ("install",):
        if not rest:
            raise ValueError("indica la ruta del archivo")
        return [rest]  # la ruta puede tener espacios
    if name in ("uninstall", "launch"):
        if len(a) != 1 or not _PKG.match(a[0]):
            raise ValueError("indica un nombre de paquete válido (p. ej. com.ejemplo.app)")
        return a
    if name == "grant":
        if len(a) != 2 or not _PKG.match(a[0]) or not _PERM.match(a[1]):
            raise ValueError("formato: grant PAQUETE android.permission.NOMBRE")
        return a
    if name == "kiosk":
        if not 1 <= len(a) <= 2:
            raise ValueError("formato: kiosk URL [PAQUETE]")
        url = kiosk.normalize_url(a[0])  # lanza ValueError si no es válida
        if len(a) == 2 and not _PKG.match(a[1]):
            raise ValueError("paquete no válido")
        return [url, *a[1:]]
    if name in ("wake", "home", "keeper"):
        if a:
            raise ValueError(f"«{name}» no lleva argumentos")
        return []
    raise ValueError(f"paso desconocido «{name}»")


def run(adb, device, steps: list[Step], log: Callable[[str], None] = lambda m: None) -> tuple[list[str], bool]:
    """Aplica los pasos a `device`. Devuelve (mensajes, device_modificado).
    Un paso que falla no detiene los demás; queda anotado como «✖». `device_modificado` es True
    si algún paso (kiosk) cambió campos del propio dispositivo y hay que guardarlo."""
    s = device.serial
    msgs: list[str] = []
    changed = False

    def ok(step: Step, detail: str = "OK"):
        msgs.append(f"✔ {step}: {detail}")

    def bad(step: Step, detail: str):
        msgs.append(f"✖ {step}: {detail}")

    for st in steps:
        a = st.args
        try:
            if st.name == "setting":
                r = adb.settings_put(s, a[0], a[1], a[2])
            elif st.name == "stayawake":
                r = adb.settings_put(s, "global", "stay_on_while_plugged_in", "7" if a[0] == "on" else "0")
            elif st.name == "timeout":
                r = adb.settings_put(s, "system", "screen_off_timeout", a[0])
            elif st.name == "animations":
                for k in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
                    r = adb.settings_put(s, "global", k, a[0])
            elif st.name == "brightness":
                r = adb.set_brightness(s, int(a[0]))
            elif st.name == "rotation":
                r = adb.rotate(s, None if a[0] == "auto" else int(a[0]))
            elif st.name == "density":
                r = adb.reset_density(s) if a[0] == "reset" else adb.set_density(s, int(a[0]))
            elif st.name == "install":
                r = adb.install_any(s, a[0])
                if "Success" not in r.text:
                    bad(st, r.text.splitlines()[-1] if r.text else "la instalación falló")
                    continue
            elif st.name == "uninstall":
                if not adb.is_user_package(s, a[0]):
                    bad(st, "no está instalada o es una app del sistema (protegida)")
                    continue
                r = adb.uninstall(s, a[0])
            elif st.name == "grant":
                perm = a[1] if "." in a[1] else f"android.permission.{a[1]}"
                r = adb.shell(s, f"pm grant {a[0]} {perm}")
            elif st.name == "launch":
                r = adb.launch(s, a[0])
            elif st.name == "keeper":
                apk = paths.find_keeper()
                if not apk:
                    bad(st, "no se encuentra AdbKeeper.apk (tools\\helper)")
                    continue
                kmsgs = adb.install_keeper(s, apk)
                ok(st, "; ".join(kmsgs)) if all("No se pudo" not in m and "falló" not in m
                                                  and "anterior a 11" not in m for m in kmsgs) else bad(st, "; ".join(kmsgs))
                continue
            elif st.name == "wake":
                r = adb.keyevent(s, "KEYCODE_WAKEUP")
            elif st.name == "home":
                r = adb.keyevent(s, "KEYCODE_HOME")
            elif st.name == "kiosk":
                device.kiosk_url = a[0]
                if len(a) == 2:
                    device.kiosk_package = a[1]
                changed = True
                ok(st, "URL de kiosco guardada (se aplica desde la pestaña Kiosco)")
                continue
            else:  # no debería ocurrir: parse() ya filtró los pasos
                bad(st, "paso desconocido")
                continue
            if r.ok and "Exception" not in r.text and "Error" not in r.text:
                ok(st, r.text.splitlines()[-1] if r.text else "OK")
            else:
                bad(st, r.text.splitlines()[-1] if r.text else f"código {r.rc}")
        except Exception as e:  # un fallo de un paso no debe abortar el resto del perfil
            bad(st, str(e))
        log(msgs[-1])
    return msgs, changed
