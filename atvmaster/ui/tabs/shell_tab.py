from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from ...adb import _NO_WINDOW, is_dangerous_shell
from ..base_tab import DeviceTab
from ..common import confirm

MONO = "font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;"


class _LogcatThread(QThread):
    line = pyqtSignal(str)

    def __init__(self, adb_path: str, serial: str, level: str):
        super().__init__()
        self.cmd = [adb_path, "-s", serial, "logcat", "-v", "time", f"*:{level}"]
        self.proc = None

    def run(self):
        try:
            self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)
            for raw in iter(self.proc.stdout.readline, b""):
                self.line.emit(raw.decode("utf-8", "replace").rstrip())
        except OSError as e:
            self.line.emit(f"[error] {e}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.wait(2000)


class ShellTab(DeviceTab):
    """Shell (`adb shell`, con confirmación para comandos peligrosos) y visor de logcat con
    nivel mínimo, filtro de texto y guardado a fichero."""

    title = "Shell y logcat"
    key = "shell"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        self.reader = None
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        tabs.addTab(self._build_shell(), "Shell")
        tabs.addTab(self._build_logcat(), "Logcat")

    # ---------- shell ----------
    def _build_shell(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(MONO)
        self.out.setMaximumBlockCount(5000)
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("Comando para `adb shell` (p. ej. dumpsys battery, pm list packages)")
        self.cmd.setStyleSheet(MONO)
        self.cmd.returnPressed.connect(self.run_cmd)
        run = QPushButton("Ejecutar")
        run.clicked.connect(self.run_cmd)
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self.out.clear)
        row.addWidget(self.cmd, 1)
        row.addWidget(run)
        row.addWidget(clear)
        lay.addLayout(row)
        return w

    def run_cmd(self):
        cmd = self.cmd.text().strip()
        s = self.serial()
        if not cmd or not s:
            return
        if is_dangerous_shell(cmd) and not confirm(
            self, "Comando potencialmente destructivo",
            "Este comando puede modificar o borrar datos del dispositivo.",
            f"adb -s {s} shell {cmd}",
        ):
            return
        self.out.appendPlainText(f"$ {cmd}")
        self.cmd.clear()

        def done(r):
            self.out.appendPlainText(r.text or "(sin salida)")

        self.call(lambda s: self.ctx.adb.shell(s, cmd, timeout=60), done,
                  lambda e: self.out.appendPlainText(f"[error] {e}"))

    # ---------- logcat ----------
    def _build_logcat(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.level = QComboBox()
        for lbl, v in (("Verbose", "V"), ("Debug", "D"), ("Info", "I"), ("Warning", "W"), ("Error", "E")):
            self.level.addItem(lbl, v)
        self.level.setCurrentIndex(2)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtro de texto (se aplica a las líneas nuevas)")
        self.toggle = QPushButton("▶ Iniciar")
        self.toggle.clicked.connect(self.toggle_log)
        clear = QPushButton("Limpiar vista")
        clear.clicked.connect(lambda: self.log.clear())
        save = QPushButton("Guardar…")
        save.clicked.connect(self.save_log)
        row.addWidget(QLabel("Nivel mín.:"))
        row.addWidget(self.level)
        row.addWidget(self.filter, 1)
        for b in (self.toggle, clear, save):
            row.addWidget(b)
        lay.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(MONO)
        self.log.setMaximumBlockCount(20000)
        lay.addWidget(self.log, 1)
        return w

    def toggle_log(self):
        if self.reader:
            self.stop_log()
            return
        s = self.serial()
        if not s:
            return
        self.reader = _LogcatThread(self.ctx.adb.path, s, self.level.currentData())
        self.reader.line.connect(self._on_line)
        self.reader.start()
        self.toggle.setText("■ Detener")

    def stop_log(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
        self.toggle.setText("▶ Iniciar")

    def _on_line(self, line: str):
        f = self.filter.text().lower()
        if not f or f in line.lower():
            self.log.appendPlainText(line)

    def save_log(self):
        name = f"logcat_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar logcat", name, "Texto (*.txt)")
        if path:
            Path(path).write_text(self.log.toPlainText(), "utf-8")
            self.ctx.log(f"Logcat guardado en {path}")

    def on_device_changed(self):
        self.stop_log()

    def closeEvent(self, e):
        self.stop_log()
        super().closeEvent(e)
