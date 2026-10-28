from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
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
        self.versions: dict[str, str] = {}   # {paquete: versión} de las apps de usuario
        self._fresh = False                  # False = lo que se ve es la última lectura guardada
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
        self.allpk, self.third, self.versions, self._fresh = [], set(), {}, False
        self.count.setText("")
        d = self.ctx.current
        if d and d.app_versions:  # última lectura guardada: se ve aunque el dispositivo esté apagado
            self.versions = dict(d.app_versions)
            self.third = set(self.versions)
            self.allpk = sorted(self.versions)
            self._fill()

    def on_activated(self):
        if self.ctx.current and self.is_online() and not self._fresh:
            self.refresh()

    def refresh(self):
        def work(s):
            a = self.ctx.adb
            return a.package_versions(s, "-3"), a.packages(s, "")

        def done(res):
            versions, allp = res
            self.versions, self._fresh = versions, True
            self.third = set(versions)
            self.allpk = allp
            d = self.ctx.current
            if d:  # se registra con el dispositivo: queda visible sin conexión y en el inventario
                d.app_versions = dict(versions)
                d.app_versions_at = datetime.now().strftime("%Y-%m-%d %H:%M")
                self.ctx.store.update(d)
            self._fill()

        self.call(work, done)

    def _fill(self):
        mode = self.scope.currentIndex()
        txt = self.filter.text().lower()
        items = [p for p in self.allpk
                 if (mode == 2 or (mode == 0) == (p in self.third)) and txt in p.lower()]
        self.list.clear()
        for p in items:
            ver = self.versions.get(p, "")
            it = QListWidgetItem(f"{p}    ·    v{ver}" if ver else p)
            it.setData(Qt.ItemDataRole.UserRole, p)  # el nombre del paquete, sin el texto de la versión
            self.list.addItem(it)
        d = self.ctx.current
        note = ""
        if not self._fresh and d and d.app_versions_at:
            note = f" · última lectura guardada: {d.app_versions_at} (sin conexión)"
        elif d and d.app_versions_at:
            note = f" · leído: {d.app_versions_at}"
        self.count.setText(f"{len(items)} paquetes{note}")

    def _pkg(self) -> str | None:
        it = self.list.currentItem()
        if not it:
            warn(self, "Sin selección", "Selecciona un paquete de la lista.")
            return None
        return it.data(Qt.ItemDataRole.UserRole) or it.text()

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
