import sys
import traceback
from datetime import datetime

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QMessageBox

from atvmaster import APP_NAME, paths
from atvmaster.ui.common import AppContext
from atvmaster.ui.main_window import MainWindow


def apply_dark(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    bg, base, text, accent = (QColor(32, 34, 40), QColor(24, 26, 31),
                              QColor(225, 228, 235), QColor(56, 132, 255))
    for role, color in (
        (QPalette.ColorRole.Window, bg),
        (QPalette.ColorRole.Base, base),
        (QPalette.ColorRole.AlternateBase, bg),
        (QPalette.ColorRole.Button, QColor(46, 49, 58)),
        (QPalette.ColorRole.WindowText, text),
        (QPalette.ColorRole.Text, text),
        (QPalette.ColorRole.ButtonText, text),
        (QPalette.ColorRole.ToolTipBase, base),
        (QPalette.ColorRole.ToolTipText, text),
        (QPalette.ColorRole.Highlight, accent),
        (QPalette.ColorRole.HighlightedText, QColor(255, 255, 255)),
        (QPalette.ColorRole.PlaceholderText, QColor(130, 135, 148)),
    ):
        p.setColor(role, color)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(110, 114, 125))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(110, 114, 125))
    app.setPalette(p)


_reported: set[str] = set()   # errores ya mostrados en esta sesión (no se repite el aviso)


def install_crash_guard() -> None:
    """PyQt6 cierra TODO el programa si una excepción se escapa de un slot (cualquier botón o
    señal). Con este gestor un error inesperado se anota en error.log y se avisa una vez, pero la
    aplicación sigue funcionando y no se pierden las tareas en curso."""
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(paths.data_dir() / "error.log", "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} ---\n{text}\n")
        except OSError:
            pass
        sys.stderr.write(text)
        key = f"{exc_type.__name__}:{exc}"
        if key not in _reported and QApplication.instance():
            _reported.add(key)
            QMessageBox.warning(None, APP_NAME,
                                f"Ha ocurrido un error inesperado:\n\n{exc_type.__name__}: {exc}\n\n"
                                f"El programa sigue funcionando. Detalle en:\n{paths.data_dir() / 'error.log'}")
    sys.excepthook = hook


def main() -> int:
    install_crash_guard()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_dark(app)
    ctx = AppContext()
    win = MainWindow(ctx)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
