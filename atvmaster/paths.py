"""Rutas de la aplicación y localización de ejecutables externos (adb, scrcpy)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import APP_ID

EXE = ".exe" if os.name == "nt" else ""


def app_root() -> Path:
    """Carpeta que contiene la app (junto al .exe si está empaquetada)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_capture_dir() -> Path:
    d = Path.home() / "Pictures" / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def _first_existing(candidates: list[str | None]) -> str | None:
    for c in candidates:
        if not c:
            continue
        if Path(c).is_file():
            return str(c)
    return None


def find_adb(configured: str | None = None) -> str | None:
    root = app_root()
    candidates = [
        configured,
        root / "tools" / "platform-tools" / f"adb{EXE}",
        root / "platform-tools" / f"adb{EXE}",
        shutil.which("adb"),
    ]
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk:
        candidates.append(Path(sdk) / "platform-tools" / f"adb{EXE}")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Android" / "Sdk" / "platform-tools" / f"adb{EXE}")
    return _first_existing(candidates)


def find_keeper() -> str | None:
    """APK de ADB Keeper (la app auxiliar que reactiva la depuración inalámbrica al arrancar)."""
    root = app_root()
    return _first_existing([root / "tools" / "helper" / "AdbKeeper.apk",
                            root / "vendor" / "tools" / "helper" / "AdbKeeper.apk",
                            root / "helper_apk" / "AdbKeeper.apk"])


def find_scrcpy(configured: str | None = None) -> str | None:
    root = app_root()
    candidates = [configured, shutil.which("scrcpy")]
    tools = root / "tools"
    if tools.is_dir():
        candidates.append(tools / "scrcpy" / f"scrcpy{EXE}")
        for sub in sorted(tools.glob("scrcpy*")):
            candidates.append(sub / f"scrcpy{EXE}")
    return _first_existing(candidates)
