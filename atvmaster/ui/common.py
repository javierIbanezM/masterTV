"""Infraestructura compartida por la UI: hilos, contexto de app y diálogos."""
from __future__ import annotations

import traceback
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from .. import paths
from ..adb import Adb
from ..fully_config import FullyConfigurator
from ..kiosk import KioskService
from ..store import Device, DeviceStore, Settings


# Modelo de hilos: adb es bloqueante, así que cada llamada se ejecuta en un QThreadPool. Un
# _Task corre `fn` en el hilo de trabajo y avisa por señales (_Signals), que Qt entrega en el
# hilo de la UI, donde sí es seguro tocar widgets.
class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class _Task(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            res = self.fn()
        except Exception as e:
            self._emit("failed", f"{e}" or traceback.format_exc(limit=1))
            return
        self._emit("done", res)

    def _emit(self, name: str, value):
        """Avisa a la UI. Si la ventana se cerró mientras la tarea trabajaba, el objeto de señales
        ya no existe (basta con acceder a él para que Qt lance RuntimeError) y se ignora: no hay a
        quién avisar."""
        try:
            getattr(self.signals, name).emit(value)
        except RuntimeError:
            pass


class AppContext(QObject):
    """Estado compartido: ADB, ajustes, dispositivos y dispositivo seleccionado."""

    device_changed = pyqtSignal()
    log_line = pyqtSignal(str)
    status_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.store = DeviceStore()
        self.adb = Adb(lambda: paths.find_adb(self.settings.get("adb_path") or None))
        self.kiosk = KioskService(self.adb, self.log)
        self.fully = FullyConfigurator(self.adb, self.log)
        self.kiosk_last = {}  # id de dispositivo -> instante del último lanzamiento (antirrebote)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(16)
        self.current = None   # Device seleccionado en la lista (o None)
        self.states = {}      # id de dispositivo -> estado de ADB (ver MainWindow.STATE_LABEL)
        self._live = set()    # señales en vuelo: se guardan para que Python no las recolecte

    @property
    def serial(self) -> str | None:
        return self.current.serial if self.current else None

    def state_of(self, d: Device) -> str:
        return self.states.get(d.id, "unknown")

    def log(self, msg: str) -> None:
        self.log_line.emit(msg)

    def run(self, fn: Callable, on_ok: Callable | None = None, on_err: Callable | None = None) -> None:
        """Ejecuta `fn` en un hilo y devuelve el resultado en el hilo de la UI."""
        sig = _Signals()
        self._live.add(sig)

        def finish():
            self._live.discard(sig)

        def ok(res):
            finish()
            if on_ok:
                on_ok(res)

        def err(msg):
            finish()
            if on_err:
                on_err(msg)
            else:
                self.log(f"✖ {msg}")

        sig.done.connect(ok)
        sig.failed.connect(err)
        self.pool.start(_Task(fn, sig))


def confirm(parent: QWidget, title: str, text: str, command: str = "") -> bool:
    """Diálogo de confirmación que muestra el comando exacto a ejecutar."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if command:
        box.setInformativeText(f"Comando exacto:\n{command}")
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.button(QMessageBox.StandardButton.Yes).setText("Sí, ejecutar")
    box.button(QMessageBox.StandardButton.Cancel).setText("Cancelar")
    return box.exec() == QMessageBox.StandardButton.Yes


def info(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warn(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)
