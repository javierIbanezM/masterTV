"""Wake-on-LAN: paquete mágico UDP."""
from __future__ import annotations

import re
import socket


def normalize_mac(mac: str) -> str:
    hexs = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(hexs) != 12:
        raise ValueError(f"MAC no válida: {mac!r}")
    return ":".join(hexs[i:i + 2] for i in range(0, 12, 2)).lower()


def send_magic_packet(mac: str, host_hint: str = "") -> list[str]:
    """Envía el paquete a broadcast global y al broadcast /24 de `host_hint`.
    Devuelve las direcciones a las que se envió."""
    mac_bytes = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    targets = ["255.255.255.255"]
    parts = host_hint.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        targets.append(".".join(parts[:3] + ["255"]))
    sent: list[str] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for t in targets:
            for port in (9, 7):
                s.sendto(packet, (t, port))
            sent.append(t)
    return sent
