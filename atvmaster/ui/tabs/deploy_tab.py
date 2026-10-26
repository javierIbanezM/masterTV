from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ... import fully_deploy as fd
from ..base_tab import DeviceTab
from ..common import confirm, info, warn


class DeployTab(DeviceTab):
    """Despliegue de Fully EMM en 3 pasos: plantilla de ajustes, APK oficial e instalación con
    permisos. Fully importa la plantilla solo en su primer arranque."""

    title = "Despliegue Fully (EMM)"
    key = "deploy"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Instala la edición <b>EMM</b> de Fully Kiosk (descargada de la web oficial de Fully) en "
            "un dispositivo con <b>nuestra configuración</b>: Start URL propia, arranque automático y el "
            "resto de ajustes de un dispositivo de referencia. Fully los importa solo en el primer arranque."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        # 1 · Plantilla
        g1 = QGroupBox("1 · Plantilla de configuración (de un dispositivo de referencia)")
        l1 = QVBoxLayout(g1)
        self.tpl_label = QLabel()
        self.tpl_label.setWordWrap(True)
        l1.addWidget(self.tpl_label)
        r1 = QHBoxLayout()
        b = QPushButton("⬇ Exportar desde el dispositivo seleccionado…")
        b.clicked.connect(self.export_template)
        b2 = QPushButton("📂 Importar de un archivo…")
        b2.clicked.connect(self.import_template)
        r1.addWidget(b)
        r1.addWidget(b2)
        r1.addStretch(1)
        l1.addLayout(r1)
        lay.addWidget(g1)

        # 2 · APK
        g2 = QGroupBox("2 · APK de Fully edición EMM")
        l2 = QVBoxLayout(g2)
        self.apk_label = QLabel()
        self.apk_label.setWordWrap(True)
        l2.addWidget(self.apk_label)
        r2 = QHBoxLayout()
        b3 = QPushButton("⬇ Descargar / actualizar APK EMM…")
        b3.clicked.connect(self.download)
        r2.addWidget(b3)
        r2.addStretch(1)
        l2.addLayout(r2)
        lay.addWidget(g2)

        # 3 · Instalar
        g3 = QGroupBox("3 · Instalar en el dispositivo seleccionado")
        l3 = QVBoxLayout(g3)
        self.disable_play = QCheckBox(
            "Desactivar el Fully de Google Play al terminar (reversible), para que no compita con "
            "la EMM al arrancar el dispositivo"
        )
        self.disable_play.setChecked(True)
        l3.addWidget(self.disable_play)
        r3 = QHBoxLayout()
        b4 = QPushButton("🚀 Instalar Fully EMM con la plantilla…")
        b4.clicked.connect(self.deploy)
        r3.addWidget(b4)
        r3.addStretch(1)
        l3.addLayout(r3)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet("font-family: Consolas, monospace;")
        l3.addWidget(self.out, 1)
        lay.addWidget(g3, 1)
        self.refresh()

    def on_activated(self):
        self.refresh()

    def on_device_changed(self):
        self.out.clear()
        self.refresh()

    def refresh(self):
        t = fd.load_template()
        if t:
            self.tpl_label.setText(
                f"✔ Plantilla guardada ({len(t)} ajustes). Start URL de referencia: "
                f"{t.get('startURL', '?')}\n"
                "Se sustituye la Start URL por la de cada dispositivo (pestaña Kiosco) al instalar."
            )
        else:
            self.tpl_label.setText(
                "✖ Sin plantilla. Exporta una desde un dispositivo ya configurado o importa un "
                "fully-settings.json.")
        a = fd.apk_info()
        self.apk_label.setText(
            f"✔ {a[0].name} · {a[1] / 1048576:.1f} MB · SHA-256 {a[2][:16]}…" if a
            else f"✖ No descargada. Se obtiene de {fd.SOURCE_PAGE}"
        )

    def export_template(self):
        s = self.serial()
        if not s:
            return
        if not confirm(
            self, "Exportar plantilla desde el dispositivo",
            "Se abrirán los ajustes de Fully en el dispositivo (≈1 min), se pulsará «Export Settings» y "
            "«Guardar» en el selector de Android. Se crea el archivo Download/fully-settings.json "
            "en el dispositivo y se descarga al PC. No se cambia ningún ajuste.",
            f"adb -s {s} pull {fd.EXPORT_REMOTE}",
        ):
            return
        d = self.ctx.current
        if not self.ctx.kiosk.try_begin(d.id):
            return warn(self, "Ocupado", "Hay otra operación de kiosco en curso en este dispositivo.")
        self.out.setPlainText("Exportando desde el dispositivo…")

        def work():
            try:
                return fd.export_template_from_tv(self.ctx.adb, self.ctx.fully, s)
            finally:
                self.ctx.kiosk.end(d.id)

        def done(t):
            self.out.setPlainText(f"Plantilla exportada: {len(t)} ajustes.")
            self.refresh()

        self.ctx.run(work, done, lambda e: self.out.setPlainText(f"Error: {e}"))

    def import_template(self):
        p, _ = QFileDialog.getOpenFileName(self, "fully-settings.json", "", "JSON (*.json)")
        if p:
            try:
                t = fd.import_template_file(p)
            except (OSError, ValueError) as e:
                return warn(self, "Archivo no válido", str(e))
            self.out.setPlainText(f"Plantilla importada: {len(t)} ajustes.")
            self.refresh()

    def download(self):
        if not confirm(
            self, "Descargar APK de Fully (edición EMM)",
            f"Se leerá {fd.SOURCE_PAGE} para localizar la APK «EMM Edition» y se descargará de "
            "fully-kiosk.com a la carpeta tools/fully de la aplicación. Se mostrará su tamaño y "
            "SHA-256 al terminar.",
        ):
            return
        self.out.setPlainText("Buscando el enlace en la página de descargas…")

        def work():
            url = fd.find_emm_url()
            self.ctx.log(f"Descargando {url}")
            return url, fd.download_apk(url, self.ctx.log)

        def done(res):
            url, (path, size, sha) = res
            self.out.setPlainText(
                f"Descargada: {url}\n{path}\n{size / 1048576:.1f} MB · SHA-256 {sha}")
            self.refresh()

        self.ctx.run(work, done, lambda e: self.out.setPlainText(f"Error: {e}"))

    def deploy(self):
        d = self.ctx.current
        if not d:
            return warn(self, "Sin dispositivo", "Selecciona un dispositivo primero.")
        tpl, apk = fd.load_template(), fd.apk_info()
        if not tpl or not apk:
            return warn(self, "Faltan pasos", "Primero necesitas la plantilla (1) y la APK (2).")
        if not d.kiosk_url:
            return warn(self, "Sin URL", "Escribe la URL de este dispositivo en la pestaña «Kiosco» y guárdala.")
        s = d.serial
        off = self.disable_play.isChecked()
        cmds = (
            f"adb -s {s} push fully-once-settings.json {fd.ONCE_FILE}\n"
            f"adb -s {s} install -r -d {apk[0].name}\n"
            f"adb -s {s} shell pm grant {fd.EMM_PKG} android.permission.READ_EXTERNAL_STORAGE\n"
            f"adb -s {s} shell appops set {fd.EMM_PKG} MANAGE_EXTERNAL_STORAGE allow\n"
            f"adb -s {s} shell appops set {fd.EMM_PKG} SYSTEM_ALERT_WINDOW allow"
        ) + (f"\nadb -s {s} shell pm disable-user --user 0 {fd.FULLY_PKG}" if off else "")
        if not confirm(
            self, f"Instalar Fully EMM en «{d.name}»",
            "Se instalará Fully EMM (una app aparte, junto a la de Google Play) con la Start URL "
            f"{d.kiosk_url}. No se desinstala nada."
            + (" Al terminar se DESACTIVARÁ el Fully de Google Play (reversible)." if off else "")
            + "\nLa pantalla del dispositivo cambiará durante unos minutos.",
            cmds,
        ):
            return
        if not self.ctx.kiosk.try_begin(d.id):
            return warn(self, "Ocupado", "Hay otra operación de kiosco en curso en este dispositivo.")
        self.out.setPlainText("Instalando… (varios minutos)")
        deployer = fd.FullyDeployer(self.ctx.adb, self.ctx.fully, self.ctx.log)

        def work():
            try:
                return deployer.deploy(d, apk[0], tpl, off)
            finally:
                self.ctx.kiosk.end(d.id)

        def done(rep):
            d.kiosk_package = fd.EMM_PKG
            self.ctx.store.update(d)
            self.out.setPlainText("\n".join(rep))
            self.ctx.device_changed.emit()

        self.ctx.run(work, done, lambda e: self.out.setPlainText(f"Error: {e}"))
