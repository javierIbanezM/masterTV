"""Widgets propios reutilizables."""
from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel

# Distancia (en píxeles de la ventana) a partir de la cual un clic arrastrado cuenta como deslizamiento.
DRAG_THRESHOLD = 10


class PreviewLabel(QLabel):
    """Muestra la pantalla de un dispositivo y, si `control` está activo, convierte el ratón y el
    teclado en gestos táctiles. Las posiciones se emiten como FRACCIONES (0..1) de la imagen
    mostrada, de modo que no dependen del zoom de la ventana ni de la resolución del equipo.

    Ratón: clic izquierdo = toque · arrastrar = deslizar · rueda = desplazar ·
           clic derecho = Atrás · clic central = Inicio.
    """

    tapped = pyqtSignal(float, float)
    swiped = pyqtSignal(float, float, float, float, int)   # x1, y1, x2, y2 (fracciones), duración ms
    scrolled = pyqtSignal(float, float, int)               # x, y (fracciones), sentido: +1 arriba, -1 abajo
    back = pyqtSignal()
    home = pyqtSignal()
    key_typed = pyqtSignal(int, str)                       # tecla de Qt, texto escrito

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.control = False
        self._press: tuple[QPointF, float] | None = None
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def set_control(self, on: bool) -> None:
        self.control = on
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)

    def frac(self, pos: QPointF) -> tuple[float, float] | None:
        """Posición del ratón como fracción de la imagen; None si cae fuera de ella (en los bordes
        vacíos del visor)."""
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return None
        pw, ph = pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()
        x0, y0 = (self.width() - pw) / 2, (self.height() - ph) / 2
        fx, fy = (pos.x() - x0) / pw, (pos.y() - y0) / ph
        return (fx, fy) if 0 <= fx <= 1 and 0 <= fy <= 1 else None

    # -- ratón --
    def mousePressEvent(self, e):
        if not self.control:
            return super().mousePressEvent(e)
        self.setFocus()
        b = e.button()
        if b == Qt.MouseButton.RightButton:
            self.back.emit()
        elif b == Qt.MouseButton.MiddleButton:
            self.home.emit()
        elif b == Qt.MouseButton.LeftButton:
            self._press = (e.position(), time.time())

    def mouseReleaseEvent(self, e):
        if not (self.control and self._press and e.button() == Qt.MouseButton.LeftButton):
            return super().mouseReleaseEvent(e)
        start, t0 = self._press
        self._press = None
        a, b = self.frac(start), self.frac(e.position())
        if a is None:
            return
        d = e.position() - start
        if abs(d.x()) < DRAG_THRESHOLD and abs(d.y()) < DRAG_THRESHOLD:
            self.tapped.emit(*a)
        elif b is not None:
            self.swiped.emit(*a, *b, int(max(120, min(1500, (time.time() - t0) * 1000))))

    def wheelEvent(self, e):
        if not self.control:
            return super().wheelEvent(e)
        p = self.frac(e.position())
        if p and e.angleDelta().y():
            self.scrolled.emit(*p, 1 if e.angleDelta().y() > 0 else -1)

    # -- teclado --
    def keyPressEvent(self, e):
        if self.control:
            self.key_typed.emit(e.key(), e.text())
        else:
            super().keyPressEvent(e)


class ClickableLabel(QLabel):
    """QLabel que avisa de un doble clic (lo usa el mosaico para abrir un dispositivo)."""

    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit()
