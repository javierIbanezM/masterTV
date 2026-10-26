"""Inventario de dispositivos: recoge los datos de cada uno y los exporta a CSV (Excel)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .profiles import KIND_NAME

COLUMNS = [
    "Nombre", "Grupo", "Tipo", "Conexión", "Dirección", "Estado", "Fabricante", "Modelo", "Android",
    "SDK", "Parche de seguridad", "Compilación", "Nº de serie", "IMEI", "MAC", "IP", "Batería", "Pantalla",
    "Almacenamiento libre", "Idioma", "Zona horaria", "Apps de usuario", "Nº apps de usuario",
    "Kiosco URL", "Revisado",
]

STATES = {"device": "En línea", "unauthorized": "Falta autorizar", "offline": "Sin respuesta",
          "unreachable": "Apagado / desconectado", "unknown": "Sin comprobar"}


def _free_space(adb, serial: str) -> str:
    """Espacio libre de la partición de datos, p. ej. '12G'. Vacío si no se puede leer."""
    out = adb.shell(serial, "df -h /data | tail -n 1").out.split()
    return out[3] if len(out) >= 4 else ""


def collect(adb, d, state: str) -> dict:
    """Una fila del inventario. Los dispositivos sin conexión llevan solo los datos guardados."""
    row = {c: "" for c in COLUMNS}
    row.update({
        "Nombre": d.name, "Grupo": d.group,
        "Tipo": KIND_NAME.get(d.effective_kind, d.effective_kind),
        "Conexión": "USB" if d.is_usb else "Red",
        "Dirección": d.address, "Estado": STATES.get(state, state), "MAC": d.mac,
        "Kiosco URL": d.kiosk_url, "Revisado": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    if state != "device":
        return row
    s = d.serial
    info = adb.device_info(s)
    row.update({
        "Fabricante": info.get("Fabricante", ""), "Modelo": info.get("Modelo", ""),
        "Android": info.get("Android", ""), "SDK": info.get("SDK", ""),
        "Parche de seguridad": info.get("Parche de seguridad", ""),
        "Compilación": info.get("Compilación", ""), "Nº de serie": info.get("Nº de serie", ""),
        "IMEI": info.get("IMEI", ""),
        "MAC": info.get("MAC", "") or d.mac, "Batería": info.get("Batería", ""),
        "Pantalla": f"{info.get('Resolución', '')} @ {info.get('Densidad', '')} dpi".strip(" @"),
        "Idioma": info.get("Idioma", ""), "Zona horaria": info.get("Zona horaria", ""),
        "IP": adb.wifi_ip(s), "Almacenamiento libre": _free_space(adb, s),
    })
    if info.get("Tipo") and d.effective_kind == "auto":
        row["Tipo"] = KIND_NAME.get(info["Tipo"], info["Tipo"])
    apps = adb.packages(s, "-3")
    row["Apps de usuario"] = ", ".join(apps)
    row["Nº apps de usuario"] = str(len(apps))
    return row


def _safe(v: str) -> str:
    """Evita la inyección de fórmulas al abrir el CSV en Excel: un texto que empiece por = + - @
    se interpretaría como fórmula, así que se antepone un apóstrofo."""
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def to_csv(rows: list[dict], path: str | Path) -> Path:
    """CSV con BOM UTF-8 y ';' como separador: Excel en español lo abre con los acentos y columnas."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _safe(str(v)) for k, v in r.items()})
    return path
