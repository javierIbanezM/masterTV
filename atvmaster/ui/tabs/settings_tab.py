from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..base_tab import DeviceTab
from ..common import confirm, warn


class SettingsTab(DeviceTab):
    """Ajustes del sistema: atajos (apagado de pantalla, animaciones), resolución/densidad
    (wm) y explorador/editor de `settings` (global, secure, system). Todo cambio pide confirmación."""

    title = "Ajustes del sistema"
    key = "settings"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        self.data = {}
        lay = QVBoxLayout(self)

        # Ajustes rápidos
        quick = QGroupBox("Ajustes rápidos (cada cambio pide confirmación)")
        ql = QHBoxLayout(quick)
        self.timeout = QComboBox()
        for label, ms in (("15 s", 15000), ("1 min", 60000), ("5 min", 300000),
                          ("30 min", 1800000), ("Nunca (24 h)", 86400000)):
            self.timeout.addItem(label, ms)
        t_btn = QPushButton("Aplicar")
        t_btn.clicked.connect(self.set_timeout)
        ql.addWidget(QLabel("Apagado de pantalla:"))
        ql.addWidget(self.timeout)
        ql.addWidget(t_btn)

        self.anim = QComboBox()
        for label, v in (("Sin animaciones (0)", "0"), ("Rápidas (0.5)", "0.5"), ("Normales (1)", "1")):
            self.anim.addItem(label, v)
        a_btn = QPushButton("Aplicar")
        a_btn.clicked.connect(self.set_anim)
        ql.addWidget(QLabel("Animaciones:"))
        ql.addWidget(self.anim)
        ql.addWidget(a_btn)
        ql.addStretch(1)
        lay.addWidget(quick)

        # Energía para terminales de mano: que no se duerman mientras cargan en el cargador/base.
        self.pda_box = QGroupBox("Terminal de mano · energía")
        pl = QHBoxLayout(self.pda_box)
        for text, val in (("Mantener encendida al cargar", "7"), ("Volver al comportamiento normal", "0")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=val: self._put("global", "stay_on_while_plugged_in", v))
            pl.addWidget(b)
        pl.addStretch(1)
        lay.addWidget(self.pda_box)

        # Resolución y densidad
        disp = QGroupBox("Resolución y densidad (wm)")
        dl = QHBoxLayout(disp)
        self.w, self.h, self.dpi = QSpinBox(), QSpinBox(), QSpinBox()
        self.w.setRange(320, 7680)
        self.w.setValue(1920)
        self.h.setRange(240, 4320)
        self.h.setValue(1080)
        self.dpi.setRange(72, 640)
        self.dpi.setValue(320)
        for lbl, w in (("Ancho", self.w), ("Alto", self.h)):
            dl.addWidget(QLabel(lbl))
            dl.addWidget(w)
        sz = QPushButton("Aplicar tamaño")
        sz.clicked.connect(self.set_size)
        szr = QPushButton("Restaurar tamaño")
        szr.clicked.connect(self.reset_size)
        dl.addWidget(sz)
        dl.addWidget(szr)
        dl.addWidget(QLabel("Densidad"))
        dl.addWidget(self.dpi)
        dn = QPushButton("Aplicar densidad")
        dn.clicked.connect(self.set_density)
        dnr = QPushButton("Restaurar densidad")
        dnr.clicked.connect(self.reset_density)
        dl.addWidget(dn)
        dl.addWidget(dnr)
        lay.addWidget(disp)

        # Explorador de settings
        top = QHBoxLayout()
        self.ns = QComboBox()
        self.ns.addItems(["global", "secure", "system"])
        self.ns.currentIndexChanged.connect(self.load)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar claves o valores…")
        self.filter.textChanged.connect(self._fill)
        load = QPushButton("Cargar")
        load.clicked.connect(self.load)
        edit = QPushButton("Editar valor…")
        edit.clicked.connect(self.edit)
        new = QPushButton("Añadir clave…")
        new.clicked.connect(self.add)
        for w in (QLabel("Espacio:"), self.ns):
            top.addWidget(w)
        top.addWidget(self.filter, 1)
        for w in (load, edit, new):
            top.addWidget(w)
        lay.addLayout(top)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Clave", "Valor"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(lambda _: self.edit())
        lay.addWidget(self.table, 1)

    def apply_kind(self, kind: str, show_all: bool) -> None:
        from ...profiles import has_feature
        self.pda_box.setVisible(has_feature(kind, "pda_extras", show_all) and (kind == "pda" or show_all))

    def on_device_changed(self):
        self.data = {}
        self.table.setRowCount(0)

    def on_activated(self):
        if self.ctx.current and self.is_online() and not self.data:
            self.load()

    def load(self):
        ns = self.ns.currentText()

        def done(d):
            self.data = d
            self._fill()

        self.call(lambda s: self.ctx.adb.settings_list(s, ns), done)

    def _fill(self):
        txt = self.filter.text().lower()
        rows = [(k, v) for k, v in sorted(self.data.items()) if txt in k.lower() or txt in v.lower()]
        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(k))
            self.table.setItem(i, 1, QTableWidgetItem(v))

    def _put(self, ns: str, key: str, value: str):
        s = self.serial()
        if not s:
            return
        cmd = f"adb -s {s} shell settings put {ns} {key} {value}"
        if not confirm(self, "Cambiar ajuste del sistema", f"Se cambiará {ns}/{key} a «{value}».", cmd):
            return

        def done(r):
            self.ctx.log(f"settings put {ns} {key} {value}: {'OK' if r.ok else r.text}")
            self.load()

        self.call(lambda s: self.ctx.adb.settings_put(s, ns, key, value), done)

    def edit(self):
        row = self.table.currentRow()
        if row < 0:
            return warn(self, "Sin selección", "Selecciona una fila de la tabla.")
        key = self.table.item(row, 0).text()
        cur = self.table.item(row, 1).text()
        val, ok = QInputDialog.getText(self, "Editar valor", f"{self.ns.currentText()}/{key}:", text=cur)
        if ok and val != cur:
            self._put(self.ns.currentText(), key, val)

    def add(self):
        key, ok = QInputDialog.getText(self, "Nueva clave", "Nombre de la clave:")
        if not (ok and key.strip()):
            return
        val, ok = QInputDialog.getText(self, "Nueva clave", f"Valor de {key}:")
        if ok:
            self._put(self.ns.currentText(), key.strip(), val)

    def set_timeout(self):
        self._put("system", "screen_off_timeout", str(self.timeout.currentData()))

    def set_anim(self):
        v = self.anim.currentData()
        s = self.serial()
        if s and confirm(
            self, "Cambiar animaciones", f"Se pondrán las 3 escalas de animación a {v}.",
            "\n".join(f"adb -s {s} shell settings put global {k} {v}" for k in (
                "window_animation_scale", "transition_animation_scale", "animator_duration_scale")),
        ):
            def work(s):
                for k in ("window_animation_scale", "transition_animation_scale",
                          "animator_duration_scale"):
                    self.ctx.adb.settings_put(s, "global", k, v)

            self.call(work, lambda r: (self.ctx.log("Animaciones actualizadas"), self.load()))

    def _wm(self, args: str, title: str, text: str):
        s = self.serial()
        if s and confirm(self, title, text, f"adb -s {s} shell wm {args}"):
            self.call(lambda s: self.ctx.adb.shell(s, f"wm {args}"),
                      lambda r: self.ctx.log(f"wm {args}: {r.text or 'OK'}"))

    def set_size(self):
        self._wm(f"size {self.w.value()}x{self.h.value()}", "Cambiar resolución",
                 "Una resolución no soportada puede dejar la imagen ilegible. "
                 "Si ocurre, usa «Restaurar tamaño».")

    def reset_size(self):
        self._wm("size reset", "Restaurar resolución", "Se vuelve a la resolución física.")

    def set_density(self):
        self._wm(f"density {self.dpi.value()}", "Cambiar densidad",
                 "Cambia el tamaño de la interfaz del dispositivo.")

    def reset_density(self):
        self._wm("density reset", "Restaurar densidad", "Se vuelve a la densidad física.")
