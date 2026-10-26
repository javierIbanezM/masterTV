"""Mosaico: varias pantallas a la vez, en una cuadrícula de miniaturas que se refrescan solas."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from .widgets import ClickableLabel

MAX_TILES = 16          # más de 16 pantallas a la vez saturarían la red y los dispositivos
MAX_PARALLEL = 6        # capturas simultáneas como máximo
TILE_W = 240            # ancho de cada miniatura


class MosaicWindow(QDialog):
    """Ventana no modal con una miniatura por dispositivo. Doble clic en una miniatura emite
    `open_device(id)` para que la ventana principal seleccione ese dispositivo."""

    open_device = pyqtSignal(str)

    def __init__(self, parent, ctx, devices: list, interval_ms: int = 2500):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(f"Mosaico de pantallas · {len(devices)} dispositivo(s)")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1000, 700)
        self.devices = devices[:MAX_TILES]
        self._busy: set[str] = set()
        self._tiles: dict[str, tuple[ClickableLabel, QLabel]] = {}

        lay = QVBoxLayout(self)
        hint = QLabel("Doble clic en una pantalla para abrirla en la ventana principal. "
                      "Se actualizan cada pocos segundos mientras esta ventana está abierta.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        host = QWidget()
        grid = QGridLayout(host)
        cols = 2 if len(self.devices) <= 4 else 3 if len(self.devices) <= 9 else 4
        for i, d in enumerate(self.devices):
            shot = ClickableLabel("Sin imagen")
            shot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            shot.setMinimumSize(TILE_W, int(TILE_W * 0.75))
            shot.setStyleSheet("background:#111; border:1px solid #444; color:#888;")
            shot.double_clicked.connect(lambda dev=d: self.open_device.emit(dev.id))
            cap = QLabel(d.name)
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell = QVBoxLayout()
            cell.addWidget(shot, 1)
            cell.addWidget(cap)
            grid.addLayout(cell, i // cols, i % cols)
            self._tiles[d.id] = (shot, cap)
        lay.addWidget(host, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(interval_ms)
        self.tick()

    def tick(self):
        """Pide una captura a cada dispositivo en línea que no tenga una en curso."""
        for d in self.devices:
            if len(self._busy) >= MAX_PARALLEL:
                break
            if d.id in self._busy:
                continue
            shot, cap = self._tiles[d.id]
            if self.ctx.state_of(d) != "device":
                shot.setText("Sin conexión")
                shot.setPixmap(QPixmap())
                cap.setText(f"{d.name} · sin conexión")
                continue
            self._busy.add(d.id)
            self.ctx.run(lambda d=d: self.ctx.adb.screencap(d.serial),
                         lambda png, d=d: self._done(d, png), lambda e, d=d: self._fail(d, e))

    def _done(self, d, png: bytes):
        self._busy.discard(d.id)
        shot, cap = self._tiles[d.id]
        pm = QPixmap()
        if pm.loadFromData(png):
            shot.setPixmap(pm.scaled(shot.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
            cap.setText(d.name)

    def _fail(self, d, msg: str):
        self._busy.discard(d.id)
        shot, cap = self._tiles[d.id]
        shot.setPixmap(QPixmap())
        shot.setText("Sin imagen")
        cap.setText(f"{d.name} · {msg[:60]}")

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)
