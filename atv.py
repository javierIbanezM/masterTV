"""Línea de comandos de Android TV Master: maneja los dispositivos de tu lista sin abrir la ventana.

Usa la misma lista (devices.json) y el mismo código que la aplicación, así que entiende las IP que cambian,
USB, red, etc. No modifica tu lista de dispositivos.

Ejemplos (el dispositivo se indica por nombre, parte del nombre, IP o id; «all» = todos; varios con comas):
    python atv.py list
    python atv.py info "PDA 99"
    python atv.py apps "TV ROC"
    python atv.py install "PDA 99,PDA 100" C:\\apks\\mi_app.apk
    python atv.py uninstall "PDA 99" com.ejemplo.app
    python atv.py open "TV ROC" org.videolan.vlc
    python atv.py url "TV ROC" http://servidorwebs.zar.local/Planificador/visordealmacen.php
    python atv.py key "TV ROC" KEYCODE_HOME
    python atv.py shell "PDA 99" "getprop ro.build.version.release"
    python atv.py screenshot "PDA 99" captura.png
    python atv.py reboot "PDA 99" --yes
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from atvmaster import paths
from atvmaster.adb import Adb, is_dangerous_shell
from atvmaster.store import Device, DeviceStore

OK, FAIL = "✔", "✖"


def pick(store: DeviceStore, spec: str) -> list[Device]:
    """Dispositivos que corresponden a `spec`: nombre (o parte), IP, id, 'all' o una lista separada por comas."""
    out: list[Device] = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        low = part.lower()
        if low == "all":
            found = list(store.devices)
        else:
            found = [d for d in store.devices if low in (d.id.lower(), d.host.lower(), d.name.lower())]
            found = found or [d for d in store.devices if low in d.name.lower()]
        if not found:
            sys.exit(f"{FAIL} No hay ningún dispositivo que coincida con «{part}». Mira `python atv.py list`.")
        out += [d for d in found if d not in out]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maneja tus dispositivos Android desde la consola.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="lista los dispositivos y su estado")
    for name, helptext in (("info", "datos del dispositivo"), ("apps", "apps instaladas con su versión")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("dev")
    sub.choices["apps"].add_argument("--todas", action="store_true", help="incluye las del sistema")
    p = sub.add_parser("install", help="instala (o actualiza) uno o varios APK/XAPK/APKS")
    p.add_argument("dev"); p.add_argument("archivo", nargs="+")
    p = sub.add_parser("uninstall", help="desinstala una app de usuario")
    p.add_argument("dev"); p.add_argument("paquete")
    for name, helptext in (("open", "abre una app"), ("stop", "fuerza el cierre de una app")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("dev"); p.add_argument("paquete")
    p = sub.add_parser("url", help="abre una URL en el navegador del dispositivo")
    p.add_argument("dev"); p.add_argument("url")
    p = sub.add_parser("key", help="envía una tecla (KEYCODE_HOME, KEYCODE_BACK, 66…)")
    p.add_argument("dev"); p.add_argument("tecla")
    p = sub.add_parser("shell", help="ejecuta un comando en el dispositivo")
    p.add_argument("dev"); p.add_argument("comando")
    p.add_argument("--forzar", action="store_true", help="permite comandos marcados como peligrosos")
    p = sub.add_parser("screenshot", help="guarda una captura de pantalla")
    p.add_argument("dev"); p.add_argument("salida", nargs="?", default="")
    p = sub.add_parser("reboot", help="reinicia el dispositivo")
    p.add_argument("dev"); p.add_argument("--yes", action="store_true", help="confirma el reinicio")
    a = ap.parse_args(argv)

    adb_path = paths.find_adb()
    if not adb_path:
        sys.exit(f"{FAIL} No encuentro adb.exe (carpeta tools\\platform-tools).")
    adb = Adb(lambda: adb_path)
    adb.start_server()
    store = DeviceStore()

    if a.cmd == "list":
        devs = list(store.devices)
        with ThreadPoolExecutor(max_workers=8) as ex:
            states = list(ex.map(adb.probe_device, devs))
        for d, s in zip(devs, states):
            print(f"{d.name:24} {d.address:26} {s}")
        return 0

    devs = pick(store, a.dev)
    ready = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for d, s in zip(devs, ex.map(adb.probe_device, devs)):
            ready[d.id] = s

    def run(d: Device) -> tuple[bool, str]:
        if ready[d.id] != "device":
            return False, f"sin conexión ADB ({ready[d.id]})"
        s = d.serial
        if a.cmd == "info":
            return True, "\n".join(f"  {k}: {v}" for k, v in adb.device_info(s).items())
        if a.cmd == "apps":
            vers = adb.package_versions(s, "" if a.todas else "-3")
            return True, "\n".join(f"  {p:48} {v}" for p, v in vers.items()) or "  (ninguna)"
        if a.cmd == "install":
            res = []
            for f in a.archivo:
                if not Path(f).is_file():
                    return False, f"no existe {f}"
                r = adb.install_any(s, f)
                res.append(f"{Path(f).name}: {r.text.splitlines()[-1] if r.text else 'OK'}")
                if "Success" not in r.text and r.rc != 0:
                    return False, "; ".join(res)
            return True, "; ".join(res)
        if a.cmd == "uninstall":
            if not adb.is_user_package(s, a.paquete):  # las apps del sistema están protegidas, como en la ventana
                return False, f"{a.paquete} no es una app de usuario instalada (las del sistema no se tocan)"
            r = adb.uninstall(s, a.paquete)
            return "Success" in r.text, r.text
        if a.cmd == "open":
            return True, adb.launch(s, a.paquete).text or "abierta"
        if a.cmd == "stop":
            adb.force_stop(s, a.paquete)
            return True, "cerrada"
        if a.cmd == "url":
            return True, adb.open_url(s, a.url).text or "abierta"
        if a.cmd == "key":
            return True, adb.keyevent(s, a.tecla).text or "enviada"
        if a.cmd == "shell":
            if is_dangerous_shell(a.comando) and not a.forzar:
                return False, "comando marcado como peligroso; añade --forzar si estás seguro"
            return True, adb.shell(s, a.comando, timeout=60).text
        if a.cmd == "screenshot":
            png = adb.screencap(s)
            out = Path(a.salida) if a.salida and len(devs) == 1 else Path(f"captura_{d.name.replace(' ', '_')}.png")
            out.write_bytes(png)
            return bool(png), f"guardada en {out.resolve()}"
        if a.cmd == "reboot":
            if not a.yes:
                return False, "añade --yes para confirmar el reinicio"
            adb.reboot(s)
            return True, "reiniciando"
        return False, "orden desconocida"

    code = 0
    for d in devs:
        ok, msg = run(d)
        print(f"{OK if ok else FAIL} {d.name}: {msg}")
        code |= 0 if ok else 1
    return code


if __name__ == "__main__":
    sys.exit(main())
