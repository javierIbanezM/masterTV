from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QPushButton,
    QVBoxLayout,
)

from ..base_tab import DeviceTab
from ..common import warn

# Navegadores conocidos: (nombre, paquete). Solo se ofrecen los que estén instalados.
BROWSERS = [
    ("Chrome", "com.android.chrome"),
    ("Firefox", "org.mozilla.firefox"),
    ("Edge", "com.microsoft.emmx"),
    ("Samsung Internet", "com.sec.android.app.sbrowser"),
    ("Brave", "com.brave.browser"),
    ("Opera", "com.opera.browser"),
    ("Puffin TV", "com.cloudmosa.puffinTV"),
    ("TV Bro", "com.phlox.tvwebbrowser"),
    ("Fully Kiosk", "de.ozerov.fully"),
    ("Fully Kiosk (EMM)", "com.fullykiosk.emm"),
]


class NavigateTab(DeviceTab):
    """Navegar: abrir una web en el dispositivo (en el navegador que elijas), manejar el
    navegador (atrás, adelante, recargar, cerrar) y guardar favoritos para volver a ellos.
    En una TV el navegador suele ser Puffin/TV Bro/Fully; en móviles y tablets, Chrome o el
    del fabricante."""

    title = "Navegar"
    key = "navigate"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        self._installed: list[tuple[str, str]] = []
        self._history: list[str] = []
        lay = QVBoxLayout(self)

        # Barra de dirección
        bar = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("Dirección web (p. ej. http://servidorwebs.zar.local/ o google.com)")
        self.url.returnPressed.connect(self.open_url)
        self.browser = QComboBox()
        self.browser.addItem("Navegador predeterminado", "")
        go = QPushButton("▶ Abrir en el dispositivo")
        go.clicked.connect(self.open_url)
        bar.addWidget(self.url, 1)
        bar.addWidget(self.browser)
        bar.addWidget(go)
        lay.addLayout(bar)

        # Manejo del navegador una vez abierto
        ctrl = QGroupBox("Controlar el navegador")
        cl = QHBoxLayout(ctrl)
        for text, code in (("◀ Atrás", "KEYCODE_BACK"), ("▶ Adelante", "KEYCODE_FORWARD"),
                           ("⟳ Recargar", "KEYCODE_REFRESH"), ("⌂ Inicio", "KEYCODE_HOME"),
                           ("⇥ Siguiente enlace", "KEYCODE_TAB"), ("↵ Intro", "KEYCODE_ENTER")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, c=code: self.call(lambda s: self.ctx.adb.keyevent(s, c)))
            cl.addWidget(b)
        cl.addStretch(1)
        lay.addWidget(ctrl)
        self.touch_row = QGroupBox("Desplazar la página (pantallas táctiles)")
        tl = QHBoxLayout(self.touch_row)
        for text, name in (("⬆ Subir", "down"), ("⬇ Bajar", "up"), ("⬅", "right"), ("➡", "left")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, n=name: self.call(lambda s: self.ctx.adb.gesture(s, n)))
            tl.addWidget(b)
        tl.addStretch(1)
        lay.addWidget(self.touch_row)

        # Favoritos e historial
        mid = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(QLabel("<b>Favoritos</b>"))
        self.favs = QListWidget()
        self.favs.itemDoubleClicked.connect(lambda it: self._use(it.data(256)))
        left.addWidget(self.favs, 1)
        fr = QHBoxLayout()
        for text, slot in (("＋ Guardar actual", self.add_fav), ("✖ Quitar", self.del_fav)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            fr.addWidget(b)
        left.addLayout(fr)
        right.addWidget(QLabel("<b>Historial de esta sesión</b>"))
        self.hist = QListWidget()
        self.hist.itemDoubleClicked.connect(lambda it: self._use(it.text()))
        right.addWidget(self.hist, 1)
        mid.addLayout(left, 1)
        mid.addLayout(right, 1)
        lay.addLayout(mid, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self._load_favs()

    # ---------- perfil / estado ----------
    def apply_kind(self, kind: str, show_all: bool) -> None:
        from ...profiles import has_feature
        self.touch_row.setVisible(has_feature(kind, "gestures", show_all))
        if kind in ("tv", "box"):
            self.note.setText(
                "ℹ Muchas Android TV no traen navegador. Si no se abre nada, instala uno desde la "
                "pestaña Aplicaciones (Puffin TV, TV Bro, Fully). Para moverte por la página usa "
                "el D-pad de la pestaña Mando.")
        else:
            self.note.setText("")

    def on_device_changed(self):
        self._installed = []
        self._fill_browsers()

    def on_activated(self):
        if self.ctx.current and self.is_online() and not self._installed:
            self.call(lambda s: self.ctx.adb.packages(s, ""), self._set_installed)

    def _set_installed(self, pkgs: list[str]):
        have = set(pkgs)
        self._installed = [(n, p) for n, p in BROWSERS if p in have]
        self._fill_browsers()

    def _fill_browsers(self):
        cur = self.browser.currentData()
        self.browser.clear()
        self.browser.addItem("Navegador predeterminado", "")
        for n, p in self._installed:
            self.browser.addItem(n, p)
        i = self.browser.findData(cur)
        self.browser.setCurrentIndex(max(0, i))

    # ---------- abrir ----------
    @staticmethod
    def _normalize(raw: str) -> str:
        """Añade http:// si falta el esquema (los intents VIEW lo necesitan)."""
        raw = raw.strip()
        return raw if "://" in raw else "http://" + raw

    def open_url(self):
        raw = self.url.text().strip()
        if not raw:
            return warn(self, "Sin dirección", "Escribe una dirección web.")
        if any(c.isspace() for c in raw):
            return warn(self, "Dirección no válida", "La dirección no puede contener espacios.")
        url, pkg = self._normalize(raw), self.browser.currentData() or ""
        self.url.setText(url)
        if not self._history or self._history[-1] != url:
            self._history.append(url)
            self.hist.addItem(url)

        def work(s):
            return self.ctx.adb.open_url(s, url, pkg)

        self.call(work, lambda r: self.ctx.log(f"Abierto {url}"),
                  lambda e: warn(self, "No se pudo abrir", str(e)))

    def _use(self, url: str):
        self.url.setText(url)
        self.open_url()

    # ---------- favoritos ----------
    def _load_favs(self):
        from PyQt6.QtWidgets import QListWidgetItem
        self.favs.clear()
        for f in self.ctx.settings.get("bookmarks") or []:
            it = QListWidgetItem(f"{f['name']} — {f['url']}")
            it.setData(256, f["url"])
            self.favs.addItem(it)

    def add_fav(self):
        raw = self.url.text().strip()
        if not raw:
            return warn(self, "Sin dirección", "Escribe o abre una dirección para guardarla.")
        url = self._normalize(raw)
        name, ok = QInputDialog.getText(self, "Guardar favorito", "Nombre:", text=url)
        if ok and name.strip():
            favs = list(self.ctx.settings.get("bookmarks") or []) + [{"name": name.strip(), "url": url}]
            self.ctx.settings.set("bookmarks", favs)
            self._load_favs()

    def del_fav(self):
        row = self.favs.currentRow()
        favs = list(self.ctx.settings.get("bookmarks") or [])
        if 0 <= row < len(favs):
            del favs[row]
            self.ctx.settings.set("bookmarks", favs)
            self._load_favs()
