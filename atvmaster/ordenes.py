"""Órdenes remotas firmadas para el launcher de las PDA (com.azalogistics.pda 1.6.0 o superior).

El launcher consulta cada minuto, en el servidor de actualizaciones, un fichero por terminal
(``<base>/<NºSERIE>.json``) y otro para todos (``<base>/todos.json``). Aquí se construyen esos ficheros:

    {"payload": "<texto JSON>", "firma": "<RSA-SHA256 en base64 del payload>"}

El launcher solo ejecuta las órdenes si la firma coincide con su clave pública incrustada, así que
**la clave privada (ordenes_keys/ordenes_privada.pem) es lo único que importa proteger**: quien la tenga
puede instalar y desinstalar apps en todas las PDA.

Tipos de orden: ``instalar`` (APK con su SHA-256), ``desinstalar``, ``cerrar`` y ``actualizar_launcher``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
PAQUETE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
SERIE_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
TIPOS = ("instalar", "desinstalar", "cerrar", "actualizar_launcher")
HORAS_POR_DEFECTO = 24
# Mismos paquetes que el launcher se niega a tocar (OrdenesVerificador.paqueteProtegido): se avisa aquí
# antes de publicar, para no firmar una orden que la PDA va a rechazar.
PROTEGIDOS_PREFIJOS = ("com.android.", "com.datalogic.", "com.mediatek.", "com.google.android.gms",
                       "com.google.android.gsf")
PAQUETE_LAUNCHER = "com.azalogistics.pda"


class OrdenError(ValueError):
    pass


def sha256_archivo(ruta: str | Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def nuevo_id(prefijo: str = "ord") -> str:
    """Id único y legible: prefijo-AAAAMMDD-HHMMSS-xxxx (un id solo se ejecuta una vez en cada PDA)."""
    return f"{prefijo}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def protegido(paquete: str) -> bool:
    p = paquete.lower()
    return p == "android" or p == "com.android.vending" or p.startswith(PROTEGIDOS_PREFIJOS)


def _comprobar_paquete(paquete: str, *, permitir_launcher: bool = False) -> None:
    if not PAQUETE_RE.match(paquete or ""):
        raise OrdenError(f"nombre de paquete no válido: {paquete!r}")
    if paquete == PAQUETE_LAUNCHER and not permitir_launcher:
        raise OrdenError("el launcher no se toca con esta orden; usa «actualizar_launcher»")
    if protegido(paquete):
        raise OrdenError(f"{paquete} es un paquete protegido: la PDA rechazaría la orden")


def orden_instalar(url: str, sha256: str, paquete: str = "", id: str | None = None) -> dict:
    if not re.match(r"^https?://", url or "", re.I):
        raise OrdenError("la URL debe ser http(s)")
    if not re.fullmatch(r"[0-9a-f]{64}", (sha256 or "").lower()):
        raise OrdenError("sha256 no válido")
    if paquete:
        _comprobar_paquete(paquete)
    return {"id": id or nuevo_id("inst"), "tipo": "instalar", "url": url, "sha256": sha256.lower(),
            **({"paquete": paquete} if paquete else {})}


def orden_actualizar_launcher(url: str, sha256: str, id: str | None = None) -> dict:
    o = orden_instalar(url, sha256, "", id or nuevo_id("launcher"))
    o["tipo"] = "actualizar_launcher"
    return o


def orden_desinstalar(paquete: str, id: str | None = None) -> dict:
    _comprobar_paquete(paquete)
    return {"id": id or nuevo_id("desinst"), "tipo": "desinstalar", "paquete": paquete}


def orden_cerrar(paquete: str, id: str | None = None) -> dict:
    _comprobar_paquete(paquete)
    return {"id": id or nuevo_id("cerrar"), "tipo": "cerrar", "paquete": paquete}


def construir_payload(destino: str, ordenes: list[dict], horas: float = HORAS_POR_DEFECTO,
                      ahora: float | None = None) -> str:
    """Texto JSON que se firma. ``destino`` es un nº de serie o ``*`` (todas las PDA)."""
    if destino != "*" and not SERIE_RE.match(destino or ""):
        raise OrdenError(f"destino no válido: {destino!r}")
    if not ordenes:
        raise OrdenError("no hay órdenes que enviar")
    ids = [o.get("id") for o in ordenes]
    if any(not ID_RE.match(str(i or "")) for i in ids) or len(set(ids)) != len(ids):
        raise OrdenError("cada orden necesita un id válido y distinto")
    for o in ordenes:
        if o.get("tipo") not in TIPOS:
            raise OrdenError(f"tipo de orden desconocido: {o.get('tipo')!r}")
    if not 0 < horas <= 24 * 30:
        raise OrdenError("la vigencia debe estar entre 0 y 720 horas")
    t = int(ahora if ahora is not None else time.time())
    # Las órdenes caducan: un fichero antiguo que alguien vuelva a copiar al servidor deja de valer.
    return json.dumps({"version": 1, "emitido": t, "caduca": t + int(horas * 3600), "destino": destino,
                       "ordenes": ordenes}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _clave_privada(ruta: str | Path):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(Path(ruta).read_bytes(), password=None)


def firmar(payload: str, clave_pem: str | Path) -> str:
    """Firma RSA PKCS#1 v1.5 con SHA-256, en base64 (lo que verifica SHA256withRSA en Android)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    firma = _clave_privada(clave_pem).sign(payload.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(firma).decode("ascii")


def fichero_firmado(destino: str, ordenes: list[dict], clave_pem: str | Path,
                    horas: float = HORAS_POR_DEFECTO, ahora: float | None = None) -> str:
    payload = construir_payload(destino, ordenes, horas, ahora)
    return json.dumps({"payload": payload, "firma": firmar(payload, clave_pem)}, ensure_ascii=False, indent=2)


def verificar(texto: str, clave_publica_pem: str | Path) -> bool:
    """Comprobación del fichero tal como la hace la PDA (útil para probar antes de publicar)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        fichero = json.loads(texto)
        clave = serialization.load_pem_public_key(Path(clave_publica_pem).read_bytes())
        clave.verify(base64.b64decode(fichero["firma"]), fichero["payload"].encode("utf-8"),
                     padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False


def publicar(carpeta_servidor: str | Path, nombre: str, texto: str) -> Path:
    """Escribe ``<carpeta_servidor>/ordenes/<nombre>.json`` de forma atómica (nunca un fichero a medias)."""
    if nombre != "todos" and not SERIE_RE.match(nombre):
        raise OrdenError(f"nombre de fichero no válido: {nombre!r}")
    carpeta = Path(carpeta_servidor) / "ordenes"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{nombre}.json"
    tmp = carpeta / f".{nombre}.{os.getpid()}.tmp"
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(destino)
    return destino
