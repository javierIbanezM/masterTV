from __future__ import annotations

from typing import Callable

from PyQt6.QtWidgets import QWidget

from .common import AppContext, warn


class DeviceTab(QWidget):
    """Pestaña que actúa sobre el dispositivo seleccionado en la lista."""

    title = "Pestaña"
    key = "tab"  # identificador que usa profiles.py para decidir en qué tipos de dispositivo se ve

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        ctx.device_changed.connect(self.on_device_changed)

    def on_device_changed(self) -> None:
        pass

    def apply_kind(self, kind: str, show_all: bool) -> None:
        """Adapta los controles de la pestaña al tipo de dispositivo (tv, box, tablet, phone o
        auto). Se llama al cambiar de dispositivo y al detectarse su tipo. Por defecto no hace nada."""

    def kind(self) -> str:
        d = self.ctx.current
        return d.effective_kind if d else "auto"

    def on_activated(self) -> None:
        """Se llama cuando el usuario abre la pestaña."""

    def serial(self, quiet: bool = False) -> str | None:
        s = self.ctx.serial
        if not s and not quiet:
            warn(self, "Sin dispositivo", "Selecciona primero un dispositivo en la lista de la izquierda.")
        return s

    def is_online(self) -> bool:
        d = self.ctx.current
        return bool(d and self.ctx.state_of(d) == "device")

    def call(self, fn: Callable, on_ok: Callable | None = None, on_err: Callable | None = None) -> None:
        """Ejecuta fn(serial) en segundo plano sobre el dispositivo seleccionado."""
        s = self.serial()
        if not s:
            return
        self.ctx.run(lambda: fn(s), on_ok, on_err)
