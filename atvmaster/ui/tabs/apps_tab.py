from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout,
)

from ..base_tab import DeviceTab
from ..common import confirm, warn


class AppsTab(DeviceTab):
    """Aplicaciones instaladas: abrir, forzar cierre, borrar datos, desinstalar e instalar APK.
    Las apps del sistema están protegidas contra borrado/desinstalación."""

    title = "Aplicaciones"
    key = "apps"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        self.third = set()
        self.allpk = []
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItems(["Instaladas por el usuario", "Sistema", "Todas"])
        self.scope.currentIndexChanged.connect(self._fill)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar por nombre de paquete…")
        self.filter.textChanged.connect(self._fill)
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self.refresh)
        top.addWidget(self.scope)
        top.addWidget(self.filter, 1)
        top.addWidget(refresh)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.launch())
        lay.addWidget(self.list, 1)
        self.count = QLabel("")
        lay.addWidget(self.count)

        row = QHBoxLayout()
        for text, slot in (("▶ Abrir", self.launch), ("■ Forzar cierre", self.stop),
                           ("🧹 Borrar datos…", self.clear), ("🗑 Desinstalar…", self.uninstall),
                           ("📦 Instalar APK…", self.install)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)

    def on_device_changed(self):
        self.list.clear()
        self.allpk = []
        self.third = set()
        self.count.setText("")

    def on_activated(self):
        if self.ctx.current and self.is_online() and not self.allpk:
            self.refresh()

    def refresh(self):
        def work(s):
            a = self.ctx.adb
            return a.packages(s, "-3"), a.packages(s, "")

        def done(res):
            third, allp = res
            self.third = set(third)
            self.allpk = allp
            self._fill()

        self.call(work, done)

    def _fill(self):
        mode = self.scope.currentIndex()
        txt = self.filter.text().lower()
        items = [p for p in self.allpk
                 if (mode == 2 or (mode == 0) == (p in self.third)) and txt in p.lower()]
        self.list.clear()
        self.list.addItems(items)
        self.count.setText(f"{len(items)} paquetes")

    def _pkg(self) -> str | None:
        it = self.list.currentItem()
        if not it:
            warn(self, "Sin selección", "Selecciona un paquete de la lista.")
            return None
        return it.text()

    def launch(self):
        p = self._pkg()
        if p:
            self.call(lambda s: self.ctx.adb.launch(s, p), lambda r: self.ctx.log(f"Abriendo {p}"))

    def stop(self):
        p = self._pkg()
        if p:
            self.call(lambda s: self.ctx.adb.force_stop(s, p), lambda r: self.ctx.log(f"Cerrada {p}"))

    def _guard_user_app(self, p: str, what: str) -> bool:
        if p not in self.third:
            warn(self, "Aplicación del sistema",
                 f"{p} es una aplicación del sistema. Por seguridad la aplicación no permite "
                 f"{what} apps del sistema (podría dejar el dispositivo inestable o sin arranque).")
            return False
        return True

    def clear(self):
        p, s = self._pkg(), self.serial()
        if p and s and self._guard_user_app(p, "borrar los datos de") and confirm(
            self, "Borrar datos de la app", f"Se borrarán TODOS los datos y ajustes de {p}.",
            f"adb -s {s} shell pm clear {p}",
        ):
            self.call(lambda s: self.ctx.adb.clear_data(s, p), lambda r: self.ctx.log(r.text))

    def uninstall(self):
        p, s = self._pkg(), self.serial()
        if p and s and self._guard_user_app(p, "desinstalar") and confirm(
            self, "Desinstalar aplicación", f"Se desinstalará {p}.", f"adb -s {s} uninstall {p}",
        ):
            def done(r):
                self.ctx.log(f"Desinstalar {p}: {r.text}")
                self.refresh()

            self.call(lambda s: self.ctx.adb.uninstall(s, p), done)

    def install(self):
        s = self.serial()
        if not s:
            return
        apk, _ = QFileDialog.getOpenFileName(self, "Elegir APK", "", "APK (*.apk)")
        if apk and confirm(self, "Instalar APK", f"Se instalará (o actualizará) {apk} en el dispositivo.",
                           f'adb -s {s} install -r "{apk}"'):
            self.ctx.log(f"Instalando {apk}…")

            def done(r):
                self.ctx.log(f"Instalación: {r.text}")
                self.refresh()

            self.call(lambda s: self.ctx.adb.install(s, apk), done)
