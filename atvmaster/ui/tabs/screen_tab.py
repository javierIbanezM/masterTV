from __future__ import annotations

import os
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout,
    QSizePolicy,
)

from ... import paths, scrcpy
from ...adb import save_bytes
from ..base_tab import DeviceTab
from ..widgets import PreviewLabel
from ..common import info, warn


class ScreenTab(DeviceTab):
    """Capturas, vista previa en vivo (~1 fps con screencap), escritorio remoto (scrcpy) y
    grabación de pantalla con screenrecord."""

    title = "Pantalla y escritorio remoto"
    key = "screen"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        self._procs = []
        self._busy = False
        self._last_png = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._live_tick)

        lay = QHBoxLayout(self)

        # Vista previa
        left = QVBoxLayout()
        self.preview = PreviewLabel("Sin captura")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 270)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background:#111; border:1px solid #444;")
        left.addWidget(self.preview, 1)
        row = QHBoxLayout()
        b = QPushButton("📷 Captura")
        b.clicked.connect(self.capture)
        self.live = QCheckBox("Vista previa en vivo (≈1 fps)")
        self.live.toggled.connect(self._toggle_live)
        folder = QPushButton("Abrir carpeta de capturas")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._dir()))))
        # Control remoto con el ratón y el teclado sobre la propia vista previa (sin scrcpy).
        self.ctl = QCheckBox("🖱 Controlar con el ratón y el teclado")
        self.ctl.setToolTip("Clic = toque · arrastrar = deslizar · rueda = desplazar · clic derecho = Atrás · "
                            "clic central = Inicio · escribe con el teclado tras hacer clic en la pantalla")
        self.ctl.toggled.connect(self._toggle_control)
        for w in (b, self.live, self.ctl, folder):
            row.addWidget(w)
        row.addStretch(1)
        left.addLayout(row)
        self.preview.tapped.connect(self._on_tap)
        self.preview.swiped.connect(self._on_swipe)
        self.preview.scrolled.connect(self._on_scroll)
        self.preview.back.connect(lambda: self._send_key("KEYCODE_BACK"))
        self.preview.home.connect(lambda: self._send_key("KEYCODE_HOME"))
        self.preview.key_typed.connect(self._on_key)
        self._typed = ""            # texto tecleado pendiente de enviar (se agrupa para no lanzar un adb por letra)
        self._type_timer = QTimer(self)
        self._type_timer.setSingleShot(True)
        self._type_timer.timeout.connect(self._flush_text)
        self._shot_size = (0, 0)    # tamaño real de la última captura = píxeles de la pantalla del equipo
        lay.addLayout(left, 3)

        # Escritorio remoto
        right = QVBoxLayout()
        box = QGroupBox("Escritorio remoto (scrcpy)")
        f = QFormLayout(box)
        self.max_size = QSpinBox()
        self.max_size.setRange(0, 3840)
        self.max_size.setSpecialValueText("Nativa")
        self.max_size.setSuffix(" px")
        self.bitrate = QSpinBox()
        self.bitrate.setRange(1, 64)
        self.bitrate.setValue(8)
        self.bitrate.setSuffix(" Mbps")
        self.fps = QSpinBox()
        self.fps.setRange(5, 120)
        self.fps.setValue(30)
        self.audio = QCheckBox("Reenviar audio al PC")
        self.awake = QCheckBox("Mantener el dispositivo despierto")
        self.awake.setChecked(True)
        self.screen_off = QCheckBox("Apagar la pantalla del dispositivo durante la sesión")
        self.full = QCheckBox("Pantalla completa")
        self.top = QCheckBox("Siempre visible")
        f.addRow("Resolución máx.", self.max_size)
        f.addRow("Bitrate", self.bitrate)
        f.addRow("FPS máx.", self.fps)
        for w in (self.audio, self.awake, self.screen_off, self.full, self.top):
            f.addRow(w)
        self.scrcpy_btn = QPushButton("🖥 Abrir escritorio remoto")
        self.scrcpy_btn.clicked.connect(self.open_remote)
        f.addRow(self.scrcpy_btn)
        self.scrcpy_note = QLabel()
        self.scrcpy_note.setWordWrap(True)
        f.addRow(self.scrcpy_note)
        right.addWidget(box)

        # Grabación
        rec = QGroupBox("Grabación de pantalla (screenrecord)")
        rl = QHBoxLayout(rec)
        self.dur = QSpinBox()
        self.dur.setRange(3, 180)
        self.dur.setValue(15)
        self.dur.setSuffix(" s")
        rb = QPushButton("⏺ Grabar y descargar")
        rb.clicked.connect(self.record)
        rl.addWidget(self.dur)
        rl.addWidget(rb)
        right.addWidget(rec)
        right.addStretch(1)
        lay.addLayout(right, 2)
        self._refresh_scrcpy_note()

    def _dir(self) -> Path:
        custom = self.ctx.settings.get("capture_dir")
        d = Path(custom) if custom else paths.default_capture_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _stamp(self) -> str:
        name = (self.ctx.current.name if self.ctx.current else "tv").replace(" ", "_")
        return f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"

    def on_activated(self):
        self._refresh_scrcpy_note()

    def on_device_changed(self):
        # Al cambiar de dispositivo se apaga el control: un clic nunca debe ir a otro equipo.
        self.ctl.setChecked(False)
        self.live.setChecked(False)

    def _refresh_scrcpy_note(self):
        found = paths.find_scrcpy(self.ctx.settings.get("scrcpy_path") or None)
        if found:
            self.scrcpy_note.setText(f"scrcpy: {found}")
            return
        self.scrcpy_note.setText(
            "⚠ scrcpy no encontrado. Colócalo en tools/scrcpy/ (junto a la app) o indica su ruta "
            "en Configuración.")

    # ---------- captura ----------
    def capture(self):
        def done(png):
            self._show(png)
            p = self._dir() / f"{self._stamp()}.png"
            save_bytes(p, png)
            self.ctx.log(f"Captura guardada: {p}")

        self.call(lambda s: self.ctx.adb.screencap(s), done)

    def _show(self, png: bytes):
        self._last_png = png
        pm = QPixmap()
        pm.loadFromData(png)
        self._shot_size = (pm.width(), pm.height())
        self.preview.setPixmap(pm.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))

    # ---------- control con ratón y teclado ----------
    def _toggle_control(self, on: bool):
        self.preview.set_control(on)
        if on:
            if not self.serial():
                self.ctl.setChecked(False)
                return
            if not self.live.isChecked():
                self.live.setChecked(True)  # sin imagen al día no se ve el efecto de lo que se pulsa

    def _xy(self, fx: float, fy: float) -> tuple[int, int]:
        """Fracción de la imagen -> píxel de la pantalla del dispositivo."""
        w, h = self._shot_size
        return int(fx * w), int(fy * h)

    def _on_tap(self, fx: float, fy: float):
        x, y = self._xy(fx, fy)
        self.call(lambda s: self.ctx.adb.tap(s, x, y))

    def _on_swipe(self, fx1: float, fy1: float, fx2: float, fy2: float, ms: int):
        (x1, y1), (x2, y2) = self._xy(fx1, fy1), self._xy(fx2, fy2)
        self.call(lambda s: self.ctx.adb.swipe(s, x1, y1, x2, y2, ms))

    def _on_scroll(self, fx: float, fy: float, direction: int):
        # Rueda hacia arriba = el contenido sube = el dedo baja (y al revés).
        x, y = self._xy(fx, fy)
        dy = int(self._shot_size[1] * 0.25) * (1 if direction > 0 else -1)
        y2 = max(1, min(self._shot_size[1] - 1, y + dy))
        self.call(lambda s: self.ctx.adb.swipe(s, x, y, x, y2, 250))

    def _send_key(self, code: str):
        self.call(lambda s: self.ctx.adb.keyevent(s, code))

    def _on_key(self, key: int, text: str):
        K = Qt.Key
        special = {K.Key_Return: "KEYCODE_ENTER", K.Key_Enter: "KEYCODE_ENTER", K.Key_Backspace: "KEYCODE_DEL",
                   K.Key_Delete: "KEYCODE_FORWARD_DEL", K.Key_Escape: "KEYCODE_BACK", K.Key_Tab: "KEYCODE_TAB",
                   K.Key_Up: "KEYCODE_DPAD_UP", K.Key_Down: "KEYCODE_DPAD_DOWN", K.Key_Left: "KEYCODE_DPAD_LEFT",
                   K.Key_Right: "KEYCODE_DPAD_RIGHT", K.Key_Home: "KEYCODE_MOVE_HOME", K.Key_End: "KEYCODE_MOVE_END"}
        if key in special:
            self._flush_text()  # que el texto pendiente salga antes que la tecla especial
            self._send_key(special[key])
        elif text and text.isprintable():
            if text.isascii():
                self._typed += text
                self._type_timer.start(200)
            else:
                self.ctx.log("Solo se pueden escribir caracteres ASCII (limitación de `input text`)")

    def _flush_text(self):
        text, self._typed = self._typed, ""
        if text:
            self.call(lambda s: self.ctx.adb.text(s, text))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._last_png:
            self._show(self._last_png)

    def _toggle_live(self, on: bool):
        if on:
            if not self.serial():
                self.live.setChecked(False)
                return
            self._live_tick()
            self.timer.start(1000)
        else:
            self.timer.stop()

    def _live_tick(self):
        s = self.ctx.serial
        if self._busy or not s:
            return
        self._busy = True

        def done(png):
            self._busy = False
            self._show(png)

        def err(msg):
            self._busy = False
            self.live.setChecked(False)
            self.ctx.log(f"✖ Vista previa detenida: {msg}")

        self.ctx.run(lambda: self.ctx.adb.screencap(s), done, err)

    # ---------- scrcpy ----------
    def open_remote(self):
        d = self.ctx.current
        if not d:
            return warn(self, "Sin dispositivo", "Selecciona un dispositivo primero.")
        exe = paths.find_scrcpy(self.ctx.settings.get("scrcpy_path") or None)
        if not exe:
            return warn(self, "scrcpy no encontrado",
                        "Descarga scrcpy (https://github.com/Genymobile/scrcpy/releases) y "
                        "descomprímelo en la carpeta tools/scrcpy/ junto a la aplicación, o indica "
                        "su ruta en Configuración.")
        opts = scrcpy.ScrcpyOptions(
            max_size=self.max_size.value(),
            bitrate_mbps=self.bitrate.value(),
            max_fps=self.fps.value(),
            no_audio=not self.audio.isChecked(),
            stay_awake=self.awake.isChecked(),
            screen_off=self.screen_off.isChecked(),
            fullscreen=self.full.isChecked(),
            always_on_top=self.top.isChecked(),
        )
        try:
            proc = scrcpy.launch(exe, self.ctx.adb.path, d.serial, f"{d.name} ({d.address})", opts)
        except OSError as e:
            return warn(self, "No se pudo lanzar scrcpy", str(e))
        self._procs.append(proc)
        self.ctx.log(f"Escritorio remoto abierto para {d.name}")

        def wait():
            _, err = proc.communicate()
            return proc.returncode, err.decode("utf-8", "replace").strip()

        def done(res):
            rc, err = res
            if rc not in (0, None):
                self.ctx.log(f"scrcpy terminó con error ({rc}): {err[-400:]}")

        self.ctx.run(wait, done)

    # ---------- grabación ----------
    def record(self):
        secs = self.dur.value()
        remote = "/sdcard/atvmaster_rec.mp4"
        local = self._dir() / f"{self._stamp()}.mp4"
        self.ctx.log(f"Grabando {secs}s en el dispositivo…")

        def work(s):
            a = self.ctx.adb
            r = a.shell(s, f"screenrecord --time-limit {secs} {remote}", timeout=secs + 30)
            if not r.ok and "not found" in r.text.lower():
                raise RuntimeError("Este dispositivo no incluye screenrecord")
            p = a.pull(s, remote, str(local))
            a.shell(s, f"rm -f {remote}")
            if not p.ok:
                raise RuntimeError(p.text)
            return str(local)

        self.call(work, lambda p: self.ctx.log(f"Grabación guardada: {p}"))
