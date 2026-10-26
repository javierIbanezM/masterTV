"""Despliegue de Fully Kiosk (edición EMM) con una configuración propia.

Flujo oficial de Fully («Legacy Deployment»): exportar los ajustes de un dispositivo de referencia,
copiarlos como `fully-once-settings.json` a la raíz del almacenamiento y arrancar la app una vez:
Fully los importa y borra el archivo. La edición EMM es la que puede leer ese archivo en
Android 11+ (la de Google Play no: lo comprobamos en un dispositivo real).
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable

from . import paths
from .adb import Adb, AdbError, shell_quote
from .fully_config import EMM_PKG, FULLY_PKG, FullyConfigurator
from .kiosk import normalize_url
from .store import Device

SOURCE_PAGE = "https://www.fully-kiosk.com/docs/es/getting-started/downloads"
FALLBACK_EMM_URL = "https://www.fully-kiosk.com/files/2026/08/Fully-Kiosk-Browser-v1.61.2-emm.apk"
_EMM_LINK = re.compile(
    r'href="(https://www\.fully-kiosk\.com/files/[^"]*Fully-Kiosk-Browser-v[\d.]+-emm\.apk)"')
ONCE_FILE = "/sdcard/fully-once-settings.json"
EXPORT_REMOTE = "/sdcard/Download/fully-settings.json"
_UA = {"User-Agent": "AndroidTvMaster"}


def find_emm_url() -> str:
    """Enlace actual de la APK «EMM Edition» según la página oficial de descargas de Fully."""
    req = urllib.request.Request(SOURCE_PAGE, headers=_UA)
    try:
        html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except OSError as e:
        raise AdbError(f"No se pudo leer la página de descargas de Fully: {e}") from e
    links = _EMM_LINK.findall(html)
    if not links:
        raise AdbError("La página de descargas no ofrece ahora la edición EMM (¿ha cambiado el formato?)")
    return links[0]


def apk_dir() -> Path:
    d = paths.app_root() / "tools" / "fully"
    d.mkdir(parents=True, exist_ok=True)
    return d


def apk_info() -> tuple[Path, int, str] | None:
    """APK EMM ya descargada (la de versión más reciente), con su tamaño y SHA-256."""
    found = sorted(apk_dir().glob("Fully-Kiosk-Browser-v*-emm.apk"))
    if not found:
        return None
    p = found[-1]
    return p, p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()


def download_apk(url: str, progress: Callable[[str], None] = lambda m: None) -> tuple[Path, int, str]:
    """Descarga la APK EMM de la web oficial de Fully. Devuelve (ruta, bytes, sha256)."""
    dest = apk_dir() / url.rsplit("/", 1)[1]
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers=_UA)
    h = hashlib.sha256()
    done, last = 0, 0.0
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        while chunk := r.read(65536):
            out.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if time.time() - last > 1.5:
                last = time.time()
                progress(f"Descargando… {done / 1048576:.1f}" +
                         (f" / {total / 1048576:.1f} MB" if total else " MB"))
    if done < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise AdbError(f"La descarga parece incompleta ({done} bytes)")
    tmp.replace(dest)
    return dest, done, h.hexdigest()


def template_path() -> Path:
    return paths.data_dir() / "fully-template.json"


def load_template() -> dict | None:
    try:
        return json.loads(template_path().read_text("utf-8-sig"))
    except (OSError, ValueError):
        return None


def save_template(data: dict) -> None:
    if not isinstance(data, dict) or "startURL" not in data:
        raise ValueError("No parece un fully-settings.json válido (falta «startURL»)")
    template_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


def import_template_file(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text("utf-8-sig"))
    save_template(data)
    return data


def render(template: dict, d: Device) -> dict:
    """Plantilla + particularidades de cada dispositivo (de momento, su Start URL)."""
    out = dict(template)
    out["startURL"] = normalize_url(d.kiosk_url)
    out["launchOnBoot"] = True
    out["keepScreenOn"] = True
    return out


def export_template_from_tv(adb: Adb, cfg: FullyConfigurator, serial: str) -> dict:
    """Pulsa «Export Settings» en Fully, acepta el selector «Guardar» (carpeta Descargas)
    y descarga el JSON. Escribe `Download/fully-settings.json` en el dispositivo."""
    cfg.open_settings(serial)
    try:
        cfg.open_category(serial, "Other Settings", expect="Export Settings")
        _, row = cfg._find(serial, "Export Settings")
        cfg.tap(serial, row)
        time.sleep(3)
        save = next((n for n in cfg.dump(serial) if n.text.upper() in ("GUARDAR", "SAVE")), None)
        if not save:
            raise AdbError("No apareció el selector «Guardar» de Android")
        cfg.tap(serial, save)
        time.sleep(3)
        tmp = Path(tempfile.mkdtemp()) / "fully-settings.json"
        r = adb.pull(serial, EXPORT_REMOTE, str(tmp))
        if not r.ok:
            raise AdbError(f"No se pudo descargar {EXPORT_REMOTE}: {r.text}")
        data = json.loads(tmp.read_text("utf-8-sig"))
    finally:
        try:
            cfg.exit_settings(serial)
        except AdbError:
            pass
    save_template(data)
    return data


class FullyDeployer:
    """La edición EMM es OTRA app (`com.fullykiosk.emm`): se instala junto a la de Play sin
    tocarla. Para leer el archivo de importación necesita «acceso a todos los archivos»."""

    def __init__(self, adb: Adb, cfg: FullyConfigurator, log: Callable[[str], None] = print):
        self.adb, self.cfg, self.log = adb, cfg, log

    def version_of(self, serial: str, pkg: str) -> str:
        r = self.adb.shell(serial, f"dumpsys package {pkg} | grep -m1 versionName")
        return r.out.strip().replace("versionName=", "") or "no instalada"

    def _install(self, serial: str, apk: Path) -> str:
        r = self.adb.run(["install", "-r", "-d", str(apk)], serial, timeout=600)
        if "Success" not in r.text:
            raise AdbError(f"La instalación falló: {r.text.splitlines()[-1] if r.text else 'sin detalle'}")
        return self.version_of(serial, EMM_PKG)

    def _grant(self, s: str) -> None:
        for perm in ("READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE"):
            self.adb.shell(s, f"pm grant {EMM_PKG} android.permission.{perm}")
        self.adb.shell(s, f"appops set {EMM_PKG} MANAGE_EXTERNAL_STORAGE allow")
        self.adb.shell(s, f"appops set {EMM_PKG} SYSTEM_ALERT_WINDOW allow")

    def deploy(self, d: Device, apk: Path, template: dict, disable_play: bool = False) -> list[str]:
        s = d.serial
        rep: list[str] = []
        settings = render(template, d)
        rep.append(f"Fully Play: {self.version_of(s, FULLY_PKG)}"
                   f" · Fully EMM antes: {self.version_of(s, EMM_PKG)}")

        # 1) La configuración se copia primero a la raíz del almacenamiento
        tmp = Path(tempfile.mkdtemp()) / "fully-once-settings.json"
        tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), "utf-8")
        p = self.adb.push(s, str(tmp), ONCE_FILE)
        if not p.ok:
            raise AdbError(f"No se pudo copiar la configuración al dispositivo: {p.text}")
        rep.append(f"Configuración copiada a {ONCE_FILE} (Start URL {settings['startURL']})")

        # 2) Instalar la edición EMM y darle permisos
        try:
            rep.append(f"APK EMM instalada: versión {self._install(s, apk)}")
            self._grant(s)
            rep.append("Permisos concedidos: almacenamiento, «todos los archivos» y "
                       "«mostrar sobre otras apps»")
        except AdbError:
            self.adb.shell(s, f"rm -f {shell_quote(ONCE_FILE)}")
            raise

        # 3) Arrancar una vez: Fully importa el archivo y lo borra
        self.adb.shell(s, f"am force-stop {EMM_PKG}")
        self.adb.launch(s, EMM_PKG)
        consumed = False
        for _ in range(12):
            time.sleep(5)
            if "No such file" in self.adb.shell(s, f"ls {ONCE_FILE} 2>&1").text:
                consumed = True
                break
        rep.append("Importación automática: " +
                   ("hecha (Fully consumió el archivo)" if consumed
                    else "NO confirmada (el archivo sigue en el dispositivo)"))

        # 4) Verificar por interfaz y completar lo que falte
        cfg = self.cfg.with_pkg(EMM_PKG)
        state = cfg.configure(s, settings["startURL"], check_only=True)
        rep += ["Verificación: " + x for x in state]
        if any("DESACTIVADO" in x or "distinta" in x for x in state):
            rep.append("Se completa por interfaz lo que faltaba:")
            rep += ["  " + x for x in cfg.configure(s, settings["startURL"])]
        if not consumed:
            self.adb.shell(s, f"rm -f {shell_quote(ONCE_FILE)}")

        if disable_play and self.version_of(s, FULLY_PKG) != "no instalada":
            r = self.adb.shell(s, f"pm disable-user --user 0 {FULLY_PKG}")
            rep.append(f"Fully de Play desactivado: {r.text or 'OK'}  (se reactiva con: pm enable {FULLY_PKG})")
        return rep
