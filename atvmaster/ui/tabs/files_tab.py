from __future__ import annotations

import posixpath
from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ..base_tab import DeviceTab
from ..common import confirm, warn


class FilesTab(DeviceTab):
    """Explorador de archivos del dispositivo: navegar, descargar al PC, subir y eliminar
    (el borrado solo se permite dentro de /sdcard y /storage)."""

    title = "Archivos"
    key = "files"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        self.cwd = "/sdcard"
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        up = QPushButton("⬆ Subir nivel")
        up.clicked.connect(self.go_up)
        self.path = QLineEdit(self.cwd)
        self.path.returnPressed.connect(lambda: self.go(self.path.text()))
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(lambda: self.go(self.cwd))
        # Carpetas habituales de móviles y tablets (cámara, descargas...). Se oculta en TV/cajas.
        self.quick = QComboBox()
        self.quick.addItem("Carpetas rápidas…", "")
        for label, folder in (("Descargas", "/sdcard/Download"), ("Cámara (DCIM)", "/sdcard/DCIM"),
                              ("Imágenes", "/sdcard/Pictures"), ("Documentos", "/sdcard/Documents"),
                              ("Música", "/sdcard/Music"), ("Vídeos", "/sdcard/Movies"),
                              ("Capturas", "/sdcard/Pictures/Screenshots"), ("Raíz del almacenamiento", "/sdcard")):
            self.quick.addItem(label, folder)
        self.quick.activated.connect(lambda _: self.quick.currentData() and self.go(self.quick.currentData()))
        top.addWidget(up)
        top.addWidget(self.quick)
        top.addWidget(self.path, 1)
        top.addWidget(refresh)
        lay.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nombre", "Tamaño", "Modificado"])
        self.tree.setColumnWidth(0, 420)
        self.tree.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        for text, slot in (("⬇ Descargar al PC", self.pull), ("⬆ Subir archivo…", self.push),
                           ("🗑 Eliminar…", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

    def apply_kind(self, kind: str, show_all: bool) -> None:
        from ...profiles import has_feature
        self.quick.setVisible(has_feature(kind, "quick_folders", show_all))

    def on_device_changed(self):
        self.tree.clear()

    def on_activated(self):
        if self.ctx.current and self.is_online() and self.tree.topLevelItemCount() == 0:
            self.go(self.cwd)

    def go(self, path: str):
        path = posixpath.normpath(path or "/")

        def done(entries):
            self.cwd = path
            self.path.setText(path)
            self.tree.clear()
            for name, is_dir, size, date in entries:
                it = QTreeWidgetItem([("📁 " if is_dir else "📄 ") + name, "" if is_dir else size, date])
                it.setData(0, 256, (name, is_dir))
                self.tree.addTopLevelItem(it)

        self.call(lambda s: self.ctx.adb.ls(s, path), done)

    def go_up(self):
        self.go(posixpath.dirname(self.cwd) or "/")

    def _open(self, item, _col=0):
        name, is_dir = item.data(0, 256)
        if is_dir:
            self.go(posixpath.join(self.cwd, name))

    def _sel(self):
        it = self.tree.currentItem()
        if not it:
            warn(self, "Sin selección", "Selecciona un archivo o carpeta.")
            return None
        return it.data(0, 256)

    def pull(self):
        sel = self._sel()
        if not sel:
            return
        name, _ = sel
        dest = QFileDialog.getExistingDirectory(self, "Carpeta de destino en el PC")
        if dest:
            remote = posixpath.join(self.cwd, name)
            self.ctx.log(f"Descargando {remote}…")
            self.call(lambda s: self.ctx.adb.pull(s, remote, str(Path(dest))),
                      lambda r: self.ctx.log(r.text))

    def push(self):
        s = self.serial()
        if not s:
            return
        local, _ = QFileDialog.getOpenFileName(self, "Archivo a subir al dispositivo")
        if local and confirm(
            self, "Subir archivo", f"Se copiará el archivo a {self.cwd} en el dispositivo.",
            f'adb -s {s} push "{local}" {self.cwd}/',
        ):
            self.ctx.log(f"Subiendo {local}…")
            self.call(lambda s: self.ctx.adb.push(s, local, self.cwd + "/"),
                      lambda r: (self.ctx.log(r.text), self.go(self.cwd)))

    def delete(self):
        s, sel = self.serial(), self._sel()
        if not (sel and s):
            return
        name, _ = sel
        remote = posixpath.join(self.cwd, name)
        if not (remote.startswith("/sdcard/") or remote.startswith("/storage/")):
            return warn(self, "Ruta protegida",
                        "Por seguridad solo se pueden eliminar archivos dentro de /sdcard o /storage.")
        if confirm(self, "Eliminar", f"Se eliminará definitivamente:\n{remote}",
                   f"adb -s {s} shell rm -rf '{remote}'"):
            self.call(lambda s: self.ctx.adb.remove(s, remote),
                      lambda r: (self.ctx.log(f"Eliminado {remote}"), self.go(self.cwd)))
