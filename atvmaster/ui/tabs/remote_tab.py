from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QVBoxLayout,
)

from ...adb import KEYCODES, SETTINGS_SCREENS
from ..base_tab import DeviceTab


class RemoteTab(DeviceTab):
    """Mando a distancia: D-pad, volumen/canales, multimedia, texto, toque/deslizamiento,
    gestos para móviles y atajos a pantallas de ajustes."""

    title = "Mando"
    key = "remote"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()

        # Cruceta
        pad = QGroupBox("Navegación")
        g = QGridLayout(pad)
        for text, key, r, c in (("▲", "Arriba", 0, 1), ("◀", "Izquierda", 1, 0), ("OK", "OK", 1, 1),
                                ("▶", "Derecha", 1, 2), ("▼", "Abajo", 2, 1)):
            g.addWidget(self._key_btn(text, key, 56), r, c)
        g.addWidget(self._key_btn("↩ Atrás", "Atrás", 56), 3, 0)
        g.addWidget(self._key_btn("⌂ Inicio", "Inicio", 56), 3, 1)
        g.addWidget(self._key_btn("☰ Menú", "Menú", 56), 3, 2)
        row.addWidget(pad)
        self.pad_box = pad

        # Volumen / canales / sistema
        misc = QGroupBox("Volumen y sistema")
        m = QGridLayout(misc)
        keys = ["Vol +", "Vol -", "Silencio", "Canal +", "Canal -", "Entradas (fuente)",
                "Despertar", "Standby", "Ajustes", "Guía", "Información", "Aplicaciones recientes"]
        self._misc_btns = {}  # etiqueta -> botón, para ocultar los que solo valen en TV
        for i, k in enumerate(keys):
            self._misc_btns[k] = self._key_btn(k, k)
            m.addWidget(self._misc_btns[k], i // 3, i % 3)
        row.addWidget(misc)

        media = QGroupBox("Multimedia")
        ml = QGridLayout(media)
        for i, k in enumerate(["Anterior", "Retroceder", "Play/Pausa", "Avanzar", "Siguiente", "Stop"]):
            ml.addWidget(self._key_btn(k, k), i // 3, i % 3)
        row.addWidget(media)
        lay.addLayout(row)

        # Texto
        tb = QGroupBox("Escribir texto en el dispositivo")
        tl = QHBoxLayout(tb)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Texto (solo ASCII; el campo del dispositivo debe estar enfocado)")
        self.text.returnPressed.connect(self.send_text)
        send = QPushButton("Enviar")
        send.clicked.connect(self.send_text)
        enter = QPushButton("Enter")
        enter.clicked.connect(lambda: self._key("KEYCODE_ENTER"))
        back = QPushButton("⌫ Borrar")
        back.clicked.connect(lambda: self._key("KEYCODE_DEL"))
        for w in (self.text, send, enter, back):
            tl.addWidget(w)
        lay.addWidget(tb)

        # Toque / deslizamiento
        tt = QGroupBox("Toque / deslizamiento (coordenadas de la pantalla)")
        ttl = QHBoxLayout(tt)
        self.sp = {n: self._spin(n) for n in ("x1", "y1", "x2", "y2")}
        for n, sp in self.sp.items():
            ttl.addWidget(QLabel(n))
            ttl.addWidget(sp)
        tap = QPushButton("Tap (x1,y1)")
        tap.clicked.connect(lambda: self.call(
            lambda s: self.ctx.adb.tap(s, self.sp["x1"].value(), self.sp["y1"].value())))
        swipe = QPushButton("Swipe")
        swipe.clicked.connect(lambda: self.call(
            lambda s: self.ctx.adb.swipe(s, *(self.sp[n].value() for n in ("x1", "y1", "x2", "y2")))))
        ttl.addWidget(tap)
        ttl.addWidget(swipe)
        lay.addWidget(tt)

        # Gestos táctiles pensados para móviles y tablets (no hay D-pad). Las coordenadas se
        # calculan con la resolución real de la pantalla, así que valen para cualquier tamaño.
        gb = QGroupBox("Gestos (móviles y tablets)")
        gl = QHBoxLayout(gb)
        # El nombre del gesto es el sentido del dedo; el texto, hacia dónde se desplaza la página.
        for text, name in (("⬆ Subir página", "down"), ("⬇ Bajar página", "up"),
                           ("⬅ A la izquierda", "right"), ("➡ A la derecha", "left"),
                           ("🔓 Deslizar para desbloquear", "unlock")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, n=name: self.call(lambda s: self.ctx.adb.gesture(s, n)))
            gl.addWidget(b)
        lay.addWidget(gb)
        self.gest_box = gb

        # Extras de móviles y tablets: paneles del sistema, orientación y brillo.
        tx = QGroupBox("Móvil / tablet")
        txl = QHBoxLayout(tx)
        for text, fn in (
            ("🔔 Notificaciones", lambda s: self.ctx.adb.expand_notifications(s)),
            ("⚙ Ajustes rápidos", lambda s: self.ctx.adb.expand_quick_settings(s)),
            ("✖ Cerrar paneles", lambda s: self.ctx.adb.collapse_panels(s)),
            ("↕ Vertical", lambda s: self.ctx.adb.rotate(s, 0)),
            ("↔ Horizontal", lambda s: self.ctx.adb.rotate(s, 1)),
            ("⟲ Giro automático", lambda s: self.ctx.adb.rotate(s, None)),
            ("☀ Brillo −", lambda s: self.ctx.adb.set_brightness(s, 60)),
            ("☀ Brillo +", lambda s: self.ctx.adb.set_brightness(s, 220)),
        ):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: self.call(f))
            txl.addWidget(b)
        lay.addWidget(tx)
        self.touch_extras_box = tx

        # Terminales de mano (PDA): teclas físicas. El código del gatillo del escáner y de las
        # teclas programables depende del modelo; aquí se puede enviar cualquier KEYCODE por
        # nombre (KEYCODE_CAMERA) o por número (27) para localizarlo y probarlo.
        pda = QGroupBox("Terminal de mano · teclas físicas")
        pl = QHBoxLayout(pda)
        for text, code in (("📷 Cámara", "KEYCODE_CAMERA"), ("◎ Enfoque", "KEYCODE_FOCUS"),
                           ("☰ Apps recientes", "KEYCODE_APP_SWITCH"), ("⏻ Encendido", "KEYCODE_POWER"),
                           ("⌫ Borrar", "KEYCODE_DEL")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, c=code: self._key(c))
            pl.addWidget(b)
        self.raw_key = QLineEdit()
        self.raw_key.setPlaceholderText("Otra tecla: KEYCODE_… o número")
        self.raw_key.setMaximumWidth(220)
        self.raw_key.returnPressed.connect(self._send_raw_key)
        sendk = QPushButton("Enviar tecla")
        sendk.clicked.connect(self._send_raw_key)
        pl.addWidget(self.raw_key)
        pl.addWidget(sendk)
        lay.addWidget(pda)
        self.pda_box = pda

        # Pantallas de ajustes
        st = QGroupBox("Abrir pantalla de ajustes del dispositivo")
        sl = QHBoxLayout(st)
        self.screens = QComboBox()
        self.screens.addItems(SETTINGS_SCREENS.keys())
        go = QPushButton("Abrir")
        go.clicked.connect(self.open_screen)
        sl.addWidget(self.screens, 1)
        sl.addWidget(go)
        lay.addWidget(st)
        lay.addStretch(1)

    def apply_kind(self, kind: str, show_all: bool) -> None:
        """TV/caja: D-pad, canales y guía; sin gestos. Móvil/tablet: gestos y extras táctiles;
        sin canales, guía ni fuente de entrada. Tipo desconocido: se muestra todo."""
        from ...profiles import TV_ONLY_KEYS, has_feature
        self.pad_box.setVisible(has_feature(kind, "dpad", show_all))
        self.gest_box.setVisible(has_feature(kind, "gestures", show_all))
        self.touch_extras_box.setVisible(has_feature(kind, "touch_extras", show_all))
        self.pda_box.setVisible(has_feature(kind, "pda_extras", show_all) and kind == "pda" or show_all)
        tv_keys = has_feature(kind, "tv_keys", show_all)
        for label, btn in self._misc_btns.items():
            btn.setVisible(tv_keys or label not in TV_ONLY_KEYS)

    def _spin(self, name):
        sp = QSpinBox()
        sp.setRange(0, 7680)
        sp.setValue(960 if name.startswith("x") else 540)
        return sp

    def _key_btn(self, text, key_label, min_w=0):
        b = QPushButton(text)
        b.setMinimumHeight(38)
        if min_w:
            b.setMinimumWidth(min_w)
        b.setAutoRepeat(key_label in ("Vol +", "Vol -", "Canal +", "Canal -"))
        b.clicked.connect(lambda: self._key(KEYCODES[key_label]))
        return b

    def _send_raw_key(self):
        code = self.raw_key.text().strip()
        # Solo KEYCODE_XXX o un número: nada de pasar texto libre al shell.
        if code and (code.isdigit() or (code.startswith("KEYCODE_") and code.replace("_", "").isalnum())):
            self._key(code)
        elif code:
            self.ctx.log("Tecla no válida: usa KEYCODE_NOMBRE o un número")

    def _key(self, code):
        self.call(lambda s: self.ctx.adb.keyevent(s, code))

    def send_text(self):
        t = self.text.text()
        if t:
            self.call(lambda s: self.ctx.adb.text(s, t), lambda r: self.text.clear())

    def open_screen(self):
        action = SETTINGS_SCREENS[self.screens.currentText()]
        self.call(lambda s: self.ctx.adb.open_settings(s, action),
                  lambda r: self.ctx.log(f"Abierto: {self.screens.currentText()}"))
