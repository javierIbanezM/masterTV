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

Órdenes remotas a las PDA Datalogic (launcher 1.6.0+): instalan/desinstalan/cierran apps SIN ADB. Se publican
firmadas en el servidor de actualizaciones y la PDA las recoge sola en menos de un minuto:
    python atv.py orden-instalar "PDA 99,PDA 100" C:\\apks\\mi_app.apk
    python atv.py orden-desinstalar "PDA 99" com.ejemplo.app
    python atv.py orden-cerrar all com.ejemplo.app
    python atv.py orden-estado "PDA 99"          # resultado de las órdenes (necesita ADB)
(--servidor y --url-base eligen otro servidor, p. ej. uno de pruebas; --solo-mostrar no escribe nada.)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from atvmaster import ordenes, paths
from atvmaster.adb import Adb, is_dangerous_shell
from atvmaster.store import Device, DeviceStore

OK, FAIL = "✔", "✖"
# Mismo servidor al que publica el despliegue del launcher (githooks/post-commit) y desde el que lee versionPDA.json.
SERVIDOR_POR_DEFECTO = r"\\SRVAutoN8N.zar.local\c$\Users\administrador.ZAR\Desktop\ConfigN8N\printer\updates"
URL_BASE_POR_DEFECTO = "http://SRVAutoN8N.zar.local:5000/updates"
CLAVE_POR_DEFECTO = Path(__file__).resolve().parent / "ordenes_keys" / "ordenes_privada.pem"
APP_PDA = "com.azalogistics.pda"


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

    def opciones_orden(p):
        p.add_argument("--servidor", default=os.environ.get("ATV_SERVIDOR", SERVIDOR_POR_DEFECTO),
                       help="carpeta del servidor de actualizaciones donde se publica (ruta de red o local)")
        p.add_argument("--url-base", default=os.environ.get("ATV_URL_BASE", URL_BASE_POR_DEFECTO),
                       help="URL con la que las PDA ven esa carpeta")
        p.add_argument("--clave", default=os.environ.get("ATV_CLAVE_ORDENES", str(CLAVE_POR_DEFECTO)),
                       help="clave privada que firma las órdenes")
        p.add_argument("--horas", type=float, default=ordenes.HORAS_POR_DEFECTO, help="vigencia de las órdenes")
        p.add_argument("--solo-mostrar", action="store_true", help="enseña lo que publicaría y no escribe nada")

    p = sub.add_parser("orden-instalar", help="orden remota: instala un APK en las PDA (sin ADB)")
    p.add_argument("dev"); p.add_argument("archivo")
    p.add_argument("--paquete", default="", help="nombre del paquete que debe tener el APK (recomendado)")
    opciones_orden(p)
    for name, helptext in (("orden-desinstalar", "orden remota: desinstala una app de usuario"),
                           ("orden-cerrar", "orden remota: fuerza el cierre de una app")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("dev"); p.add_argument("paquete")
        opciones_orden(p)
    p = sub.add_parser("orden-estado", help="resultado de las órdenes remotas de la PDA (lee por ADB)")
    p.add_argument("dev")
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

    def publicar_orden(d: Device) -> tuple[bool, str]:
        """Publica un fichero de órdenes firmado para este terminal (no necesita que esté conectado)."""
        serie = d.hw_serial or (d.host if d.is_usb else "")
        if not ordenes.SERIE_RE.match(serie):
            return False, "no se conoce su nº de serie: conéctalo una vez para que la aplicación lo memorice"
        try:
            if a.cmd == "orden-instalar":
                apk = Path(a.archivo)
                if not apk.is_file():
                    return False, f"no existe {apk}"
                sha = ordenes.sha256_archivo(apk)
                nombre = f"{sha[:12]}_{apk.name.replace(' ', '_')}"
                orden = ordenes.orden_instalar(f"{a.url_base.rstrip('/')}/apps/{quote(nombre)}", sha, a.paquete)
                if not a.solo_mostrar:
                    destino_apk = Path(a.servidor) / "apps" / nombre
                    destino_apk.parent.mkdir(parents=True, exist_ok=True)
                    if not destino_apk.exists():
                        shutil.copyfile(apk, destino_apk)
            elif a.cmd == "orden-desinstalar":
                orden = ordenes.orden_desinstalar(a.paquete)
            else:
                orden = ordenes.orden_cerrar(a.paquete)
            texto = ordenes.fichero_firmado(serie, [orden], a.clave, a.horas)
            if a.solo_mostrar:
                return True, f"publicaría para {serie}: {json.dumps(orden, ensure_ascii=False)}"
            ruta = ordenes.publicar(a.servidor, serie, texto)
        except (ordenes.OrdenError, OSError) as e:
            return False, str(e)
        return True, f"orden {orden['id']} publicada para {serie} ({ruta}); la PDA la recoge en menos de un minuto"

    def estado_ordenes(d: Device) -> tuple[bool, str]:
        r = adb.shell(d.serial, f"cat /sdcard/Android/data/{APP_PDA}/files/ordenes_resultados.json 2>/dev/null")
        try:
            res = json.loads(r.out)
        except ValueError:
            return True, "sin resultados todavía (¿launcher 1.6.0+ y alguna orden recibida?)"
        return True, "\n" + "\n".join(f"  {k:36} {'OK' if v.get('ok') else 'ERROR':5} {v.get('detalle', '')}"
                                      for k, v in sorted(res.items()))

    def run(d: Device) -> tuple[bool, str]:
        if a.cmd in ("orden-instalar", "orden-desinstalar", "orden-cerrar"):
            return publicar_orden(d)
        if ready[d.id] != "device":
            return False, f"sin conexión ADB ({ready[d.id]})"
        s = d.serial
        if a.cmd == "orden-estado":
            return estado_ordenes(d)
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
