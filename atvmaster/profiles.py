"""Perfiles por tipo de dispositivo: qué pestañas y funciones se muestran en cada caso.

Una TV no necesita gestos táctiles ni un navegador completo; un móvil no necesita despliegue
de kiosco ni canales. Cada pestaña declara su `key`; aquí se decide cuáles ve cada tipo.
Si el tipo aún se ignora ("auto": dispositivo sin conectar o sin detectar) se muestra todo.
"""
from __future__ import annotations

# Orden = orden de las pestañas en la ventana.
ALL_TABS = ("info", "kiosk", "deploy", "navigate", "remote", "screen", "apps", "settings", "files", "shell")

PROFILES: dict[str, tuple[str, ...]] = {
    # TV y cajas: pantallas informativas, kioscos y mando con D-pad.
    "tv":     ("info", "kiosk", "deploy", "navigate", "remote", "screen", "apps", "settings", "files", "shell"),
    "box":    ("info", "kiosk", "deploy", "navigate", "remote", "screen", "apps", "settings", "files", "shell"),
    # Tablets: táctiles, también sirven de kiosco.
    "tablet": ("info", "kiosk", "deploy", "navigate", "remote", "screen", "apps", "settings", "files", "shell"),
    # Terminales de mano (PDA de almacén): suelen ejecutar una web/app a pantalla completa, así que
    # conservan Kiosco y Despliegue; se les añaden los controles de teclas físicas y de energía.
    "pda":    ("info", "kiosk", "deploy", "navigate", "remote", "screen", "apps", "settings", "files", "shell"),
    # Móviles: sin kiosco ni despliegue (se pueden ver todas con Ver → Mostrar todas las funciones).
    "phone":  ("info", "navigate", "remote", "screen", "apps", "settings", "files", "shell"),
}

# Funciones concretas dentro de una pestaña (para ocultar controles que no aplican).
FEATURES: dict[str, frozenset[str]] = {
    "tv":     frozenset({"dpad", "channels", "tv_keys", "wol", "power_off"}),
    "box":    frozenset({"dpad", "channels", "tv_keys", "wol", "power_off"}),
    "tablet": frozenset({"gestures", "touch_extras", "dpad", "quick_folders", "wol"}),
    "phone":  frozenset({"gestures", "touch_extras", "dpad", "quick_folders"}),
    # PDA: táctiles con teclas físicas (gatillo, teclado) y ajustes de energía propios.
    "pda":    frozenset({"gestures", "touch_extras", "dpad", "quick_folders", "pda_extras"}),
}

# Teclas del mando que solo tienen sentido en TV.
TV_ONLY_KEYS = frozenset({"Canal +", "Canal -", "Entradas (fuente)", "Guía", "Información"})

KIND_ICON = {"tv": "📺", "box": "📦", "tablet": "▭", "phone": "📱", "pda": "📟", "auto": "●"}
KIND_NAME = {"tv": "TV", "box": "Caja Android", "tablet": "Tablet", "phone": "Móvil",
             "pda": "Terminal de mano", "auto": "Sin detectar"}


def tabs_for(kind: str, show_all: bool = False) -> tuple[str, ...]:
    """Pestañas visibles para un tipo. Con `show_all` o tipo desconocido, todas."""
    if show_all or kind not in PROFILES:
        return ALL_TABS
    return PROFILES[kind]


def has_feature(kind: str, feature: str, show_all: bool = False) -> bool:
    """¿Se muestra `feature` para este tipo? Tipo desconocido o `show_all`: sí."""
    if show_all or kind not in FEATURES:
        return True
    return feature in FEATURES[kind]
