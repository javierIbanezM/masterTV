from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from ... import kiosk
from ...adb import FULLY_PACKAGES
from ..base_tab import DeviceTab
from ..common import confirm, info, warn

DPI_PER_PCT = 1.6  # 160 dpi = 100 %

PACKAGES = [
    ("Fully Kiosk Browser (Google Play)", kiosk.FULLY_PKG),
    ("Fully Kiosk Browser (edición EMM)", "com.fullykiosk.emm"),
    ("Firefox", "org.mozilla.firefox"),
    ("Chrome", "com.android.chrome"),
]


class KioskTab(DeviceTab):
    """Kiosco: URL a pantalla completa por dispositivo (Fully u otro navegador), arranque
    automático dentro del equipo, zoom por densidad y diagnóstico de DNS/red hecho desde el equipo."""

    title = "Kiosco (URL)"
    key = "kiosk"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        self._dns_fail = False
        lay = QVBoxLayout(self)

        box = QGroupBox("URL a pantalla completa en este dispositivo")
        f = QFormLayout(box)
        self.url = QLineEdit()
        self.url.setPlaceholderText("http://servidorwebs.zar.local/Planificador/visordealmacen.php")
        self.pkg = QComboBox()
        self.pkg.setEditable(True)
        for label, p in PACKAGES:
            self.pkg.addItem(f"{label} ({p})", p)
        self.on_power = QCheckBox(
            "Lanzar el kiosco cuando el dispositivo se encienda o arranque (mientras esta aplicación esté abierta)")
        self.watchdog = QCheckBox(
            "Vigilante: si el dispositivo está despierto y el kiosco no está en pantalla, volver a lanzarlo")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText("Solo si activas «Administración remota» en Fully (opcional)")
        f.addRow("URL", self.url)
        f.addRow("App kiosco", self.pkg)
        f.addRow(self.on_power)
        f.addRow(self.watchdog)
        f.addRow("Contraseña Fully", self.pw)
        lay.addWidget(box)

        row = QHBoxLayout()
        save = QPushButton("💾 Guardar")
        save.clicked.connect(self.save)
        apply_ = QPushButton("▶ Guardar y aplicar ahora")
        apply_.clicked.connect(self.apply_now)
        home = QPushButton("⌂ Salir del kiosco (Inicio)")
        home.clicked.connect(lambda: self.call(lambda s: self.ctx.adb.keyevent(s, "KEYCODE_HOME")))
        for b in (save, apply_, home):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        # Arranque autónomo
        boot = QGroupBox("Arranque automático dentro del dispositivo (sin depender de este programa)")
        bl = QVBoxLayout(boot)
        brow = QHBoxLayout()
        bcheck = QPushButton("🔎 Comprobar Fully")
        bcheck.clicked.connect(lambda: self.fully_run(check_only=True))
        bconf = QPushButton("⚙ Configurar Fully en el dispositivo…")
        bconf.clicked.connect(lambda: self.fully_run(check_only=False))
        brow.addWidget(bcheck)
        brow.addWidget(bconf)
        brow.addStretch(1)
        bl.addLayout(brow)
        bnote = QLabel(
            "Guarda dentro de Fully la «Start URL» y activa «Launch on Boot» y «Keep Screen On». "
            "Así Fully se abre solo al arrancar el dispositivo y carga la URL, aunque el PC y esta "
            "aplicación estén apagados. Tarda ≈1 minuto y verás cambiar la pantalla."
        )
        bnote.setWordWrap(True)
        bl.addWidget(bnote)
        lay.addWidget(boot)

        # Zoom
        zoom = QGroupBox("Zoom de la página (escala de la pantalla del dispositivo)")
        zl = QVBoxLayout(zoom)
        zr = QHBoxLayout()
        self.zoom_on = QCheckBox("Fijar zoom al lanzar el kiosco")
        self.zoom = QSpinBox()
        self.zoom.setRange(45, 400)
        self.zoom.setSingleStep(5)
        self.zoom.setValue(100)
        self.zoom.setSuffix(" %")
        self.zoom.valueChanged.connect(self._update_zoom_label)
        zr.addWidget(self.zoom_on)
        zr.addWidget(self.zoom)
        for pct in (75, 100, 125, 150):
            b = QPushButton(f"{pct} %")
            b.setFixedWidth(60)
            b.clicked.connect(lambda _=False, p=pct: self.zoom.setValue(p))
            zr.addWidget(b)
        zr.addStretch(1)
        zl.addLayout(zr)
        self.zoom_info = QLabel("")
        self.zoom_info.setWordWrap(True)
        zl.addWidget(self.zoom_info)
        zr2 = QHBoxLayout()
        zapply = QPushButton("🔎 Aplicar zoom ahora…")
        zapply.clicked.connect(self.apply_zoom)
        zreset = QPushButton("↺ Restaurar densidad original…")
        zreset.clicked.connect(self.reset_zoom)
        zr2.addWidget(zapply)
        zr2.addWidget(zreset)
        zr2.addStretch(1)
        zl.addLayout(zr2)
        lay.addWidget(zoom)
        self._disp = None

        # Diagnóstico
        diag = QGroupBox("Comprobar que el dispositivo puede abrir la URL (DNS / red)")
        dl = QVBoxLayout(diag)
        r2 = QHBoxLayout()
        test = QPushButton("🔍 Comprobar desde el dispositivo")
        test.clicked.connect(self.diagnose)
        self.fqdn_btn = QPushButton("Usar nombre completo (FQDN)")
        self.fqdn_btn.clicked.connect(self.use_fqdn)
        self.fqdn_btn.setVisible(False)
        self.dns_btn = QPushButton("Desactivar DNS privado del dispositivo…")
        self.dns_btn.clicked.connect(self.disable_private_dns)
        self.dns_btn.setVisible(False)
        for b in (test, self.fqdn_btn, self.dns_btn):
            r2.addWidget(b)
        r2.addStretch(1)
        dl.addLayout(r2)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setStyleSheet("font-family: Consolas, monospace;")
        dl.addWidget(self.report)
        lay.addWidget(diag, 1)

        note = QLabel(
            "<b>Cómo se mantiene el kiosco:</b> «Aplicar» abre la URL a pantalla completa en Fully "
            "(o la app elegida). Con las casillas activas, esta aplicación lo relanza cuando el dispositivo se "
            "enciende/arranca o se sale del kiosco, siempre que esté abierta.<br>"
            "<b>Para que arranque sin el PC:</b> usa «Configurar Fully en el dispositivo» (arriba)."
        )
        note.setWordWrap(True)
        lay.addWidget(note)

    # ---------- estado ----------
    def on_device_changed(self):
        d = self.ctx.current
        self.report.clear()
        self.fqdn_btn.setVisible(False)
        self.dns_btn.setVisible(False)
        self.setEnabled(d is not None)
        if not d:
            return
        self.url.setText(d.kiosk_url)
        idx = self.pkg.findData(d.kiosk_package)
        if idx >= 0:
            self.pkg.setCurrentIndex(idx)
        else:
            self.pkg.setEditText(d.kiosk_package)
        self.on_power.setChecked(d.kiosk_on_power_on)
        self.watchdog.setChecked(d.kiosk_watchdog)
        self.pw.setText(d.fully_password)
        self.zoom_on.setChecked(d.kiosk_density > 0)
        self.zoom.setValue(round(d.kiosk_density / DPI_PER_PCT) if d.kiosk_density else 100)
        self._disp = None
        self._update_zoom_label()
        if self.is_online():
            self.refresh_display()

    def on_activated(self):
        if self.ctx.current and self.is_online() and self._disp is None:
            self.refresh_display()

    # ---------- zoom ----------
    def _dpi(self) -> int:
        return round(self.zoom.value() * DPI_PER_PCT)

    def _update_zoom_label(self):
        w = (self._disp or {}).get("width", 1920)
        txt = (f"Con {self.zoom.value()} % ({self._dpi()} dpi) la página verá un ancho de ≈ "
               f"{round(w * 160 / self._dpi())} px.")
        # current_dpi puede ser 0 si `wm density` no devolvió nada: se evita dividir por cero.
        if self._disp and self._disp.get("current_dpi"):
            cur = self._disp["current_dpi"]
            txt = (f"Pantalla {self._disp['width']}×{self._disp['height']} · ahora {cur} dpi "
                   f"({round(cur / DPI_PER_PCT)} %, la página ve ≈ {round(w * 160 / cur)} px; "
                   f"original {self._disp['physical_dpi']} dpi).\n" + txt)
        self.zoom_info.setText(txt)

    def refresh_display(self):
        def done(info):
            self._disp = info
            self._update_zoom_label()

        self.call(lambda s: self.ctx.adb.display_info(s), done)

    def apply_zoom(self):
        s = self.serial()
        if not s or not self.save(quiet=True):
            return
        dpi = self._dpi()
        if confirm(
            self, "Cambiar el zoom (densidad de pantalla)",
            f"Se fijará la densidad del dispositivo a {dpi} dpi ({self.zoom.value()} %). Afecta a toda la "
            "interfaz del dispositivo, no solo al kiosco, y se mantiene al reiniciar. Si marcas «Fijar "
            "zoom», se volverá a aplicar cada vez que se lance el kiosco.",
            f"adb -s {s} shell wm density {dpi}",
        ):
            def done(r):
                self.ctx.log(f"Densidad {dpi} dpi aplicada: {r.text or 'OK'}")
                self.refresh_display()

            self.call(lambda s: self.ctx.adb.set_density(s, dpi), done)

    def reset_zoom(self):
        s = self.serial()
        if s and confirm(self, "Restaurar densidad original", "El dispositivo volverá a su densidad de fábrica.",
                         f"adb -s {s} shell wm density reset"):
            self.zoom_on.setChecked(False)
            self.save(quiet=True)

            def done(r):
                self.ctx.log("Densidad restaurada")
                self.refresh_display()

            self.call(lambda s: self.ctx.adb.reset_density(s), done)

    # ---------- guardar / aplicar ----------
    def _package(self) -> str:
        data = self.pkg.currentData()
        text = self.pkg.currentText().strip()
        if data and text == self.pkg.itemText(self.pkg.currentIndex()):
            return data
        return text

    def save(self, quiet: bool = False) -> bool:
        d = self.ctx.current
        if not d:
            warn(self, "Sin dispositivo", "Selecciona un dispositivo primero.")
            return False
        raw = self.url.text().strip()
        if raw:
            try:
                raw = kiosk.normalize_url(raw)
            except ValueError as e:
                warn(self, "URL no válida", str(e))
                return False
        d.kiosk_url, d.kiosk_package = raw, self._package() or kiosk.FULLY_PKG
        d.kiosk_on_power_on, d.kiosk_watchdog = self.on_power.isChecked(), self.watchdog.isChecked()
        d.fully_password = self.pw.text()
        d.kiosk_density = self._dpi() if self.zoom_on.isChecked() else 0
        self.ctx.store.update(d)
        self.url.setText(raw)
        if not quiet:
            self.ctx.log(f"Kiosco guardado para {d.name}: {raw or '(sin URL)'}")
        return True

    def fully_run(self, check_only: bool):
        d = self.ctx.current
        if not d:
            return warn(self, "Sin dispositivo", "Selecciona un dispositivo primero.")
        if d.kiosk_package not in FULLY_PACKAGES:
            return warn(self, "Solo Fully", "Esta función solo configura Fully Kiosk Browser.")
        if not self.save(quiet=True):
            return
        if not check_only and not confirm(
            self, "Configurar Fully en el dispositivo",
            "Se abrirán los ajustes de Fully en el dispositivo y se cambiará:\n  • Start URL → "
            f"{d.kiosk_url or '(sin cambios: se deja la actual)'}\n  • Launch on Boot → activado\n"
            "  • Keep Screen On → activado\n\nDurante ≈1 minuto la pantalla del dispositivo mostrará los "
            "ajustes y al final se recargará la página. No toques el mando mientras tanto.",
        ):
            return
        if not self.ctx.kiosk.try_begin(d.id):
            return warn(self, "Ocupado", "Ya hay una operación de kiosco en curso en este dispositivo.")
        self.report.setPlainText("Trabajando en el dispositivo… (≈1 min)")

        def work():
            try:
                return self.ctx.fully.with_pkg(d.kiosk_package).configure(
                    d.serial, d.kiosk_url, check_only=check_only)
            finally:
                self.ctx.kiosk.end(d.id)

        def done(rep):
            self.report.setPlainText(
                ("Estado de Fully:\n" if check_only else "Fully configurado:\n")
                + "\n".join("  " + r for r in rep))
            self.ctx.log(f"{d.name}: Fully {'comprobado' if check_only else 'configurado'}")

        self.ctx.run(work, done, lambda e: self.report.setPlainText(f"Error: {e}"))

    def apply_now(self):
        if not self.save(quiet=True):
            return
        d = self.ctx.current
        if not d.kiosk_url:
            return warn(self, "Sin URL", "Escribe la URL del kiosco.")
        self.ctx.log(f"Aplicando kiosco en {d.name}…")

        def work():
            return self.ctx.kiosk.apply(d)

        self.ctx.run(work, lambda msgs: [self.ctx.log(f"{d.name}: {m}") for m in msgs])

    # ---------- diagnóstico ----------
    def diagnose(self):
        if not self.save(quiet=True):
            return
        d = self.ctx.current
        if not d.kiosk_url:
            return warn(self, "Sin URL", "Escribe la URL del kiosco.")
        self.report.setPlainText("Comprobando desde el dispositivo…")

        def done(res):
            text, dns_fail = res
            self._dns_fail = dns_fail
            self.report.setPlainText(text)
            self.dns_btn.setVisible(dns_fail)
            host = kiosk.split_url(d.kiosk_url)[1]
            pc = kiosk.pc_resolve(host)
            self.fqdn_btn.setVisible(bool(dns_fail and pc and pc[0].lower() != host.lower()))

        self.ctx.run(lambda: self.ctx.kiosk.diagnose(d), done,
                     lambda e: self.report.setPlainText(f"Error: {e}"))

    def use_fqdn(self):
        host = kiosk.split_url(self.url.text())[1]
        pc = kiosk.pc_resolve(host)
        if pc:
            self.url.setText(self.url.text().replace(host, pc[0], 1))
            self.save()
            self.diagnose()

    def disable_private_dns(self):
        s = self.serial()
        if s and confirm(
            self, "Desactivar DNS privado",
            "El dispositivo dejará de enviar las consultas DNS a un servidor público cifrado y usará el DNS "
            "de tu red (el que reparte el router/DHCP). Es un cambio de ajustes del dispositivo.",
            f"adb -s {s} shell settings put global private_dns_mode off",
        ):
            def done(r):
                self.ctx.log(f"private_dns_mode=off: {'OK' if r.ok else r.text}")
                self.diagnose()

            self.call(lambda s: self.ctx.adb.settings_put(s, "global", "private_dns_mode", "off"), done)
