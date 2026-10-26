from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import QFileDialog, QStyle, QSystemTrayIcon
from PyQt6.QtWidgets import (
    QDockWidget, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QPlainTextEdit, QPushButton, QSplitter, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, inventory, kiosk, paths, prep, profiles, scheduler, wol
from ..adb import KEYCODES, tcp_open
from ..store import Device
from .common import AppContext, confirm, info, warn
from .dialogs import DeviceDialog, DiscoverDialog, PairDialog, ScanDialog, SettingsDialog
from .mosaic import MAX_TILES, MosaicWindow
from .tools_dialogs import ProfilesDialog, ScheduleDialog
from .tabs.apps_tab import AppsTab
from .tabs.files_tab import FilesTab
from .tabs.deploy_tab import DeployTab
from .tabs.info_tab import InfoTab
from .tabs.kiosk_tab import KioskTab
from .tabs.navigate_tab import NavigateTab
from .tabs.remote_tab import RemoteTab
from .tabs.screen_tab import ScreenTab
from .tabs.settings_tab import SettingsTab
from .tabs.shell_tab import ShellTab

# Estado que devuelve Adb.probe_device -> (texto en la lista, color).
STATE_LABEL = {
    "device": ("En línea", "#3fb950"),
    "unauthorized": ("Falta autorizar en el dispositivo", "#d29922"),
    "offline": ("ADB sin respuesta", "#d29922"),
    "unreachable": ("Apagado / sin depuración / desconectado", "#f85149"),
    "unknown": ("Comprobando…", "#8b949e"),
}


class MainWindow(QMainWindow):
    """Ventana principal: lista de dispositivos a la izquierda, pestañas a la derecha y el
    registro de actividad abajo. Aquí viven el sondeo periódico y las acciones en lote."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self._polling = False
        self._detecting: set[str] = set()   # dispositivos cuyo tipo se está detectando
        self._wifi_keep: dict[str, float] = {}  # id -> instante del último intento de reactivar el ADB por Wi-Fi
        self.show_all = False               # Ver → Mostrar todas las funciones

        split = QSplitter()
        split.addWidget(self._build_left())
        self.tabs = QTabWidget()
        self.tab_widgets = [
            InfoTab(ctx), KioskTab(ctx), DeployTab(ctx), NavigateTab(ctx), RemoteTab(ctx), ScreenTab(ctx),
            AppsTab(ctx), SettingsTab(ctx), FilesTab(ctx), ShellTab(ctx),
        ]
        for t in self.tab_widgets:
            self.tabs.addTab(t, t.title)
        self.tabs.currentChanged.connect(lambda i: self.tab_widgets[i].on_activated())
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([340, 940])
        self.setCentralWidget(split)

        # Registro de actividad
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumBlockCount(2000)
        self.logbox.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        dock = QDockWidget("Registro", self)
        dock.setWidget(self.logbox)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        ctx.log_line.connect(self._append_log)
        ctx.status_changed.connect(self.refresh_list)

        self._build_menu()
        self.refresh_list()
        ctx.device_changed.connect(self._apply_profile)
        self._apply_profile()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(int(ctx.settings.get("poll_seconds")) * 1000)
        QTimer.singleShot(300, self._startup)

        self.setAcceptDrops(True)  # arrastrar un APK a la ventana lo instala en los dispositivos marcados
        self.alerts = scheduler.AlertTracker(int(ctx.settings.get("alerts_threshold") or 3))
        self._tray = None
        self._mosaic = None
        # Las tareas programadas se comprueban cada 20 s (una tarea se lanza una vez por minuto).
        self.sched_timer = QTimer(self)
        self.sched_timer.timeout.connect(self._tick_schedules)
        self.sched_timer.start(20_000)

    # ---------- panel izquierdo ----------
    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Mis dispositivos Android</b>  "
                             "<small>(marca las casillas para acciones en lote)</small>"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda _: self.edit_device())
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        for text, slot in (("＋ Añadir", self.add_device), ("🔍 Descubrir", self.discover), ("🌐 Buscar en red", self.scan_network),
                           ("✎ Editar", self.edit_device), ("✖ Quitar", self.remove_device)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)

        batch = QToolButton()
        batch.setText("Acción sobre las marcadas ▾")
        batch.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(batch)
        for text, fn in (
            ("Conectar ADB", self._b_connect), ("Desconectar ADB", self._b_disconnect),
            ("Encender (WoL + despertar)", self._b_on), ("Standby", self._b_standby),
            ("Reiniciar…", self._b_reboot), ("Abrir aplicación…", self._b_app),
            ("Activar ADB por Wi-Fi en las marcadas…", self._b_enable_wifi),
            ("Instalar ADB Keeper (activación al arrancar)…", self._b_keeper),
            ("Instalar APK en las marcadas…", self._b_install),
            ("Desinstalar app en las marcadas…", self._b_uninstall),
            ("Aplicar perfil de preparación…", self._b_profile),
            ("Mosaico de pantallas de las marcadas", self.open_mosaic),
            ("Kiosco: fijar URL en las marcadas…", self._b_kiosk_set),
            ("Kiosco: aplicar URL guardada", self._b_kiosk_apply),
            ("Kiosco: configurar Fully (arranque autónomo)…", self._b_fully),
        ):
            m.addAction(text, fn)
        km = m.addMenu("Enviar tecla")
        for label, code in KEYCODES.items():
            km.addAction(label, lambda _=False, c=code, l=label: self._b_key(c, l))
        batch.setMenu(m)
        batch.setStyleSheet("padding: 8px;")
        lay.addWidget(batch)

        sel = QHBoxLayout()
        for text, val in (("Marcar todas", True), ("Desmarcar", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=val: self._check_all(v))
            sel.addWidget(b)
        lay.addLayout(sel)
        return w

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&Aplicación")
        m.addAction("Descubrir dispositivos (USB / red)…", self.discover)
        m.addAction("Buscar dispositivos en la red (subred)…", self.scan_network)
        m.addAction("Programación y avisos…", self.edit_schedules)
        m.addAction("Perfiles de preparación…", self.edit_profiles)
        m.addAction("Exportar inventario a Excel (CSV)…", self.export_inventory)
        m.addSeparator()
        m.addAction("Configuración…", self.open_settings)
        m.addAction("Emparejar con código (Android 11+)…", self.pair)
        m.addAction("Reiniciar servidor ADB", self.restart_adb)
        m.addSeparator()
        m.addAction("Salir", self.close)
        v = mb.addMenu("&Ver")
        self.act_all = v.addAction("Mostrar todas las funciones (ignorar el tipo de dispositivo)")
        self.act_all.setCheckable(True)
        self.act_all.toggled.connect(self._toggle_show_all)
        v.addAction("Mosaico de pantallas…", self.open_mosaic)
        h = mb.addMenu("A&yuda")
        h.addAction("Acerca de", lambda: info(
            self, APP_NAME,
            "Control de dispositivos Android (TV, cajas, tablets y móviles) por ADB, por red o USB, "
            "con escritorio remoto vía scrcpy.\n\n"
            "Para cerrar ADB: adb disconnect IP:5555"))

    # ---------- lista de dispositivos ----------
    def refresh_list(self):
        cur = self.ctx.current.id if self.ctx.current else None
        checked = {
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        }
        self.list.blockSignals(True)
        self.list.clear()
        for d in sorted(self.ctx.store.devices, key=lambda x: (x.group.lower(), x.name.lower())):
            label, color = STATE_LABEL.get(self.ctx.state_of(d), STATE_LABEL["unknown"])
            grp = f"[{d.group}] " if d.group else ""
            icon = profiles.KIND_ICON.get(d.effective_kind, "●")  # 📺 TV · 📦 caja · ▭ tablet · 📱 móvil
            it = QListWidgetItem(f"{icon}  {grp}{d.name}\n     {d.address} · {label}")
            it.setForeground(QColor(color))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if d.id in checked else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, d.id)
            self.list.addItem(it)
            if d.id == cur:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)

    def _selected(self, item, _prev=None):
        self.ctx.current = self.ctx.store.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        self.ctx.device_changed.emit()
        self.tab_widgets[self.tabs.currentIndex()].on_activated()

    def _check_all(self, v: bool):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if v else Qt.CheckState.Unchecked)

    def targets(self) -> list[Device]:
        """Dispositivos sobre los que actuar: los marcados con casilla o, si no hay ninguno,
        el seleccionado en la lista. Avisa si no hay ninguno."""
        ids = [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        ]
        devs = [d for d in (self.ctx.store.get(i) for i in ids) if d]
        if not devs and self.ctx.current:
            devs = [self.ctx.current]
        if not devs:
            warn(self, "Sin dispositivos", "Marca uno o más dispositivos (o selecciona uno) primero.")
        return devs

    def add_device(self):
        dlg = DeviceDialog(self)
        if dlg.exec():
            self.ctx.store.add(dlg.device)
            self.refresh_list()
            self.poll()

    def edit_device(self):
        d = self.ctx.current
        if not d:
            return
        dlg = DeviceDialog(self, d)
        if dlg.exec():
            self.ctx.store.update(dlg.device)
            self.refresh_list()
            self.ctx.device_changed.emit()  # el tipo pudo cambiar: se reaplica el menú
            self.poll()

    def discover(self):
        """Pregunta a adb qué dispositivos ve (USB y red) y deja añadirlos a la lista."""
        def done(found):
            dlg = DiscoverDialog(self, found, {d.serial for d in self.ctx.store.devices})
            if not dlg.exec():
                return
            for dev in dlg.selected():
                self.ctx.store.add(self._device_from_adb(dev))
            self.refresh_list()
            self.poll()

        self.ctx.run(lambda: self.ctx.adb.devices_detail(), done)

    def scan_network(self):
        """Barre una subred buscando dispositivos con ADB por red y propone añadirlos."""
        known = {d.serial for d in self.ctx.store.devices}
        dlg = ScanDialog(self, self.ctx, known, self.ctx.adb.local_subnets())
        if dlg.exec():
            for dev in dlg.selected():
                d = Device(name=dev["model"] or dev["ip"], host=dev["ip"], port=dev["port"])
                if dev.get("kind"):
                    d.detected_kind = dev["kind"]
                self.ctx.store.add(d)
            self.refresh_list()
            self.poll()

    @staticmethod
    def _device_from_adb(dev: dict) -> Device:
        """Crea un Device a partir de una línea de `adb devices -l`."""
        name = dev["model"] or dev["serial"]
        if dev["usb"]:
            return Device(name=name, host=dev["serial"], transport="usb")
        host, _, port = dev["serial"].rpartition(":")
        return Device(name=name, host=host, port=int(port))

    def remove_device(self):
        d = self.ctx.current
        if d and confirm(self, "Quitar dispositivo", f"Se quitará «{d.name}» de la lista (no se toca el dispositivo)."):
            self.ctx.run(lambda: self.ctx.adb.disconnect(d.serial))
            self.ctx.store.remove(d.id)
            self.ctx.current = None
            self.refresh_list()
            self.ctx.device_changed.emit()

    # ---------- sondeo ----------
    def _startup(self):
        if not self.ctx.adb._path_getter():
            warn(self, "ADB no encontrado",
                 "No se encuentra adb.exe. Indica su ruta en Aplicación → Configuración.")
            return
        self.ctx.run(lambda: self.ctx.adb.start_server(), lambda _: self.poll())

    def poll(self):
        """Comprueba el estado de todos los dispositivos en un hilo (varios en paralelo).
        `_polling` evita solapar sondeos si uno tarda más que el intervalo del temporizador."""
        if self._polling or not self.ctx.store.devices or not self.ctx.adb._path_getter():
            return
        self._polling = True
        devs = list(self.ctx.store.devices)
        auto = bool(self.ctx.settings.get("auto_connect"))

        def work():
            adb = self.ctx.adb
            if auto:
                with ThreadPoolExecutor(max_workers=8) as ex:
                    return dict(zip((d.id for d in devs),
                                    ex.map(adb.probe_device, devs)))
            known = adb.devices()
            return {d.id: known.get(d.serial, "unreachable") for d in devs}

        def done(states):
            self._polling = False
            prev = {k: self.ctx.states.get(k) for k in states}
            changed = states != prev
            self.ctx.states.update(states)
            for d in devs:  # el puerto de la depuración inalámbrica cambió y se recuperó por mDNS
                if getattr(d, "port_changed", False):
                    d.port_changed = False
                    self.ctx.store.update(d)
                    self.ctx.log(f"{d.name}: puerto de depuración actualizado a {d.port}")
                    changed = True
            if changed:
                self.refresh_list()
                self.tab_widgets[self.tabs.currentIndex()].on_activated()
            self._kiosk_tick(devs, prev, states)
            self._detect_kinds(devs, states)
            self._check_alerts(devs, states)
            self._keep_wifi_adb(devs, states)

        def err(msg):
            self._polling = False
            self.ctx.log(f"✖ Sondeo: {msg}")

        self.ctx.run(work, done, err)

    # ---------- menú según el tipo de dispositivo ----------
    def _toggle_show_all(self, on: bool):
        self.show_all = on
        self._apply_profile()

    def _apply_profile(self):
        """Muestra solo las pestañas (y controles) que corresponden al tipo del dispositivo
        seleccionado. Con tipo desconocido o «mostrar todo» se ven todas."""
        d = self.ctx.current
        kind = d.effective_kind if d else "auto"
        allowed = profiles.tabs_for(kind, self.show_all)
        for i, t in enumerate(self.tab_widgets):
            self.tabs.setTabVisible(i, t.key in allowed)
            t.apply_kind(kind, self.show_all)
        if not self.tabs.isTabVisible(self.tabs.currentIndex()):
            first = next((i for i in range(self.tabs.count()) if self.tabs.isTabVisible(i)), 0)
            self.tabs.setCurrentIndex(first)
        name = profiles.KIND_NAME.get(kind, kind)
        self.statusBar().showMessage(f"Perfil: {name}" + (" · mostrando todas las funciones" if self.show_all else ""))

    def _detect_kinds(self, devs, states):
        """Para los dispositivos en línea con tipo «auto» y aún sin detectar, pregunta a ADB
        qué son (TV/tablet/móvil) y lo guarda: así el menú correcto aparece también offline."""
        for d in devs:
            if (d.kind != "auto" or d.detected_kind or states.get(d.id) != "device"
                    or d.id in self._detecting):
                continue
            self._detecting.add(d.id)

            def done(kind, d=d):
                self._detecting.discard(d.id)
                d.detected_kind = kind
                self.ctx.store.update(d)
                self.ctx.log(f"{d.name}: detectado como {profiles.KIND_NAME.get(kind, kind)}")
                self.refresh_list()
                if self.ctx.current and self.ctx.current.id == d.id:
                    self.ctx.device_changed.emit()

            self.ctx.run(lambda d=d: self.ctx.adb.detect_kind(d.serial), done,
                         lambda e, d=d: self._detecting.discard(d.id))

    def _kiosk_tick(self, devs, prev, states):
        """Tras cada sondeo: arranca el kiosco en dispositivos que acaban de encenderse y
        vigila las que tienen el vigilante activo."""
        now = time.time()
        for d in devs:
            if not d.kiosk_url or states.get(d.id) != "device":
                continue
            booted = prev.get(d.id) in ("unreachable", "offline")
            if booted and d.kiosk_on_power_on:
                self.ctx.log(f"{d.name}: el dispositivo se ha encendido; iniciando kiosco…")
                self.ctx.kiosk_last[d.id] = now
                self.ctx.run(
                    lambda d=d: self.ctx.kiosk.when_ready(d, wait_adb=False),
                    lambda msg, d=d: self.ctx.log(f"{d.name}: kiosco: {msg}"),
                )
                continue
            if not d.kiosk_watchdog or now - self.ctx.kiosk_last.get(d.id, 0) < 60:
                continue
            self.ctx.kiosk_last[d.id] = now
            self.ctx.run(
                lambda d=d: self.ctx.kiosk.watchdog_check(d),
                lambda msg, d=d: msg and self.ctx.log(f"{d.name}: {msg}"),
            )

    # ---------- acciones en lote ----------
    def _batch(self, label: str, fn, after=None):
        """Ejecuta `fn(dispositivo)` en paralelo sobre los dispositivos marcados (o el seleccionado)
        y escribe el resultado de cada uno en el registro."""
        devs = self.targets()
        if not devs:
            return
        self.ctx.log(f"{label}: " + ", ".join(d.name for d in devs))

        def work():
            with ThreadPoolExecutor(max_workers=8) as ex:
                return list(ex.map(lambda d: (d, fn(d)), devs))

        def done(results):
            for d, r in results:
                self.ctx.log(f"  {d.name}: {r}")
            if after:
                after()
            self.poll()

        self.ctx.run(work, done)

    # ---------- instalar / desinstalar en lote ----------
    APK_EXT = (".apk", ".apks", ".xapk", ".apkm")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(self.APK_EXT)
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(self.APK_EXT)]
        if files:
            self._install_files(files)

    def _b_install(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Elegir paquetes a instalar", "",
                                                "Paquetes Android (*.apk *.apks *.xapk *.apkm)")
        if files:
            self._install_files(files)

    def _install_files(self, files: list[str]):
        """Instala uno o varios paquetes en los dispositivos marcados (o el seleccionado)."""
        devs = self.targets()
        if not devs:
            return
        cmds = "\n".join(f'adb -s {d.serial} install -r "{f}"' for d in devs[:4] for f in files[:3])
        if not confirm(self, "Instalar en el lote",
                       f"Se instalará(n) {', '.join(Path(f).name for f in files)} en {len(devs)} "
                       f"dispositivo(s): {', '.join(d.name for d in devs)}.", cmds + ("\n…" if len(devs) > 4 else "")):
            return

        def fn(d):
            if self.ctx.state_of(d) != "device":
                return "sin conexión: no se instaló"
            out = []
            for f in files:
                r = self.ctx.adb.install_any(d.serial, f)
                out.append(f"{Path(f).name}: " + ("instalado" if "Success" in r.text
                                                  else (r.text.splitlines()[-1] if r.text else "falló")))
            return "; ".join(out)

        self._batch("Instalar paquete(s)", fn)

    def _b_uninstall(self):
        pkg, ok = QInputDialog.getText(self, "Desinstalar en el lote",
                                       "Paquete a desinstalar (p. ej. com.ejemplo.app):")
        pkg = pkg.strip()
        if not ok or not pkg:
            return
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+", pkg):
            return warn(self, "Paquete no válido", "Escribe un nombre de paquete como com.ejemplo.app.")
        devs = self.targets()
        if devs and confirm(self, "Desinstalar en el lote",
                            f"Se desinstalará {pkg} en {len(devs)} dispositivo(s): {', '.join(d.name for d in devs)}.\n"
                            "Las apps del sistema están protegidas y se omiten.",
                            "\n".join(f"adb -s {d.serial} uninstall {pkg}" for d in devs[:5])):
            def fn(d):
                if self.ctx.state_of(d) != "device":
                    return "sin conexión"
                if not self.ctx.adb.is_user_package(d.serial, pkg):
                    return "no está instalada o es una app del sistema (protegida)"
                return self.ctx.adb.uninstall(d.serial, pkg).text or "OK"

            self._batch(f"Desinstalar {pkg}", fn)

    # ---------- perfiles de preparación ----------
    def edit_profiles(self):
        dlg = ProfilesDialog(self, self.ctx)
        dlg.apply_requested.connect(lambda n: (dlg.accept(), self._apply_profile_named(n)))
        dlg.exec()

    def _b_profile(self):
        names = sorted(self.ctx.settings.get("profiles") or {})
        if not names:
            return self.edit_profiles()  # todavía no hay ninguno: se crea primero
        name, ok = QInputDialog.getItem(self, "Aplicar perfil de preparación", "Perfil:", names, 0, False)
        if ok:
            self._apply_profile_named(name)

    def _apply_profile_named(self, name: str):
        try:
            steps = prep.parse((self.ctx.settings.get("profiles") or {}).get(name, ""))
        except prep.ProfileError as e:
            return warn(self, "Perfil no válido", str(e))
        if not steps:
            return warn(self, "Perfil vacío", "El perfil no tiene ningún paso.")
        devs = self.targets()
        if not devs or not confirm(
                self, f"Aplicar «{name}»",
                f"Se aplicarán {len(steps)} paso(s) en {len(devs)} dispositivo(s): {', '.join(d.name for d in devs)}.",
                "\n".join(str(s) for s in steps)):
            return
        touched: list = []

        def fn(d):
            if self.ctx.state_of(d) != "device":
                return "sin conexión"
            msgs, changed = prep.run(self.ctx.adb, d, steps)
            if changed:
                touched.append(d)
            return " | ".join(msgs)

        def after():  # el paso «kiosk» modifica el propio dispositivo: se guarda en el hilo de la UI
            for d in touched:
                self.ctx.store.update(d)
            if touched:
                self.ctx.device_changed.emit()

        self._batch(f"Perfil «{name}»", fn, after)

    # ---------- mosaico ----------
    def open_mosaic(self):
        devs = self.targets()
        if not devs:
            return
        if len(devs) > MAX_TILES:
            info(self, "Mosaico", f"Se muestran los primeros {MAX_TILES} dispositivos de {len(devs)}.")
        if self._mosaic:
            self._mosaic.close()
        self._mosaic = MosaicWindow(self, self.ctx, devs)
        self._mosaic.open_device.connect(self._select_device)
        self._mosaic.show()

    def _select_device(self, dev_id: str):
        """Selecciona un dispositivo en la lista y abre su pestaña Pantalla."""
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == dev_id:
                self.list.setCurrentRow(i)
                break
        screen = next((i for i, t in enumerate(self.tab_widgets) if t.key == "screen"), 0)
        self.tabs.setCurrentIndex(screen)
        self.raise_()
        self.activateWindow()

    # ---------- inventario ----------
    def export_inventory(self):
        """Exporta a CSV (Excel) los dispositivos marcados o, si no hay ninguno marcado, todos."""
        marked = [self.ctx.store.get(self.list.item(i).data(Qt.ItemDataRole.UserRole))
                  for i in range(self.list.count())
                  if self.list.item(i).checkState() == Qt.CheckState.Checked]
        devs = [d for d in marked if d] or list(self.ctx.store.devices)
        if not devs:
            return warn(self, "Sin dispositivos", "No hay dispositivos en la lista.")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar inventario",
                                              f"inventario_{time.strftime('%Y%m%d_%H%M')}.csv",
                                              "CSV para Excel (*.csv)")
        if not path:
            return
        self.ctx.log(f"Recogiendo inventario de {len(devs)} dispositivo(s)…")

        def one(d):
            try:
                return inventory.collect(self.ctx.adb, d, self.ctx.state_of(d))
            except Exception as e:  # un equipo que falla no debe impedir exportar los demás
                row = inventory.collect(self.ctx.adb, d, "unreachable")
                row["Estado"] = f"Error: {e}"
                return row

        def work():
            with ThreadPoolExecutor(max_workers=8) as ex:
                return list(ex.map(one, devs))

        def done(rows):
            inventory.to_csv(rows, path)
            self.ctx.log(f"Inventario guardado en {path}")
            info(self, "Inventario exportado", f"{len(rows)} dispositivo(s) guardados en:\n{path}")

        self.ctx.run(work, done)

    # ---------- tareas programadas y avisos ----------
    def edit_schedules(self):
        if ScheduleDialog(self, self.ctx).exec():
            self.alerts = scheduler.AlertTracker(int(self.ctx.settings.get("alerts_threshold") or 3))

    def _tick_schedules(self):
        """Lanza las tareas que tocan en este minuto (se llama cada 20 s)."""
        now = datetime.now()
        items = scheduler.load(self.ctx.settings.get("schedules") or [])
        fired = False
        for s in items:
            if scheduler.is_due(s, now):
                scheduler.mark_run(s, now)
                fired = True
                self._run_schedule(s)
        if fired:
            self.ctx.settings.set("schedules", scheduler.dump(items))

    def _run_schedule(self, s):
        devs = scheduler.resolve_targets(s, self.ctx.store.devices)
        self.ctx.log(f"⏰ {s.name}: {scheduler.ACTIONS[s.action]} · {len(devs)} dispositivo(s)")
        if not devs:
            return
        steps = None
        if s.action == "profile":
            try:
                steps = prep.parse((self.ctx.settings.get("profiles") or {}).get(s.profile, ""))
            except prep.ProfileError as e:
                return self.ctx.log(f"⏰ {s.name}: perfil no válido: {e}")
        adb = self.ctx.adb

        def one(d):
            state = self.ctx.state_of(d)
            try:
                if s.action == "wake":
                    parts = []
                    if d.mac and d.ip:  # sirve aunque el equipo esté apagado
                        wol.send_magic_packet(d.mac, d.ip)
                        parts.append("WoL")
                    if state == "device":
                        adb.keyevent(d.serial, "KEYCODE_WAKEUP")
                        parts.append("WAKEUP")
                    return ", ".join(parts) or "sin MAC ni ADB"
                if state != "device":
                    return "sin conexión"
                if s.action == "sleep":
                    return adb.keyevent(d.serial, "KEYCODE_SLEEP").text or "OK"
                if s.action == "reboot":
                    return adb.reboot(d.serial).text or "OK"
                if s.action == "kiosk":
                    return "; ".join(self.ctx.kiosk.apply(d)) if d.kiosk_url else "sin URL de kiosco"
                if s.action == "profile":
                    return " | ".join(prep.run(adb, d, steps)[0])
            except Exception as e:
                return f"error: {e}"
            return "acción desconocida"

        def work():
            with ThreadPoolExecutor(max_workers=8) as ex:
                return list(ex.map(lambda d: (d, one(d)), devs))

        def done(res):
            for d, r in res:
                self.ctx.log(f"  ⏰ {d.name}: {r}")
            if s.action == "profile":  # un paso «kiosk» pudo cambiar la URL del dispositivo
                for d, _ in res:
                    self.ctx.store.update(d)

        self.ctx.run(work, done)

    def _check_alerts(self, devs, states):
        """Actualiza el detector de caídas con el último sondeo y avisa si procede."""
        enabled = bool(self.ctx.settings.get("alerts_enabled"))
        for d in devs:
            ev = self.alerts.update(d.id, states.get(d.id, "unknown"))
            if ev and enabled:
                self._alert(ev, d)

    def _alert(self, ev: str, d):
        text = scheduler.format_alert(ev, d.name, d.address)
        self.ctx.log(text)
        if self.ctx.settings.get("alerts_tray"):
            self._tray_message(text)
        hook = (self.ctx.settings.get("alerts_webhook") or "").strip()
        if hook:
            self.ctx.run(lambda: scheduler.post_webhook(hook, text), None,
                         lambda e: self.ctx.log(f"✖ Webhook de avisos: {e}"))

    def _tray_message(self, text: str):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self)
            self._tray.setToolTip(APP_NAME)
            self._tray.show()
        self._tray.showMessage(APP_NAME, text, QSystemTrayIcon.MessageIcon.Warning, 8000)

    # ---------- ADB por Wi-Fi siempre activo ----------
    def _wifi_entry(self, d, ip: str):
        """Crea (si no existe) la entrada de red de un equipo conectado por USB. Devuelve True si se creó."""
        if not ip or self.ctx.store.find_serial(f"{ip}:5555"):
            return False
        self.ctx.store.add(Device(name=f"{d.name} (Wi-Fi)", host=ip, group=d.group, kind=d.kind,
                                  detected_kind=d.detected_kind))
        return True

    def _b_enable_wifi(self):
        """Activa el ADB por Wi-Fi en los dispositivos marcados (deben estar conectados ahora)."""
        devs = self.targets()
        if not devs or not confirm(
                self, "Activar ADB por Wi-Fi",
                f"Se activará la depuración por red en {len(devs)} dispositivo(s): {', '.join(d.name for d in devs)}.\n\n"
                "• Android 11+: «Depuración inalámbrica» y autorización sin caducidad.\n"
                "• ADB por red en el puerto 5555 (se pierde al reiniciar el dispositivo).\n\n"
                "Seguridad: deja un puerto de depuración abierto en la red; úsalo solo en redes de confianza.",
                "adb -s <serie> shell settings put global adb_wifi_enabled 1\nadb -s <serie> tcpip 5555"):
            return
        created: list = []

        def fn(d):
            if self.ctx.state_of(d) != "device":
                return "sin conexión: conéctalo una vez por USB para activarlo"
            adb = self.ctx.adb
            msgs = adb.enable_wifi_debug(d.serial)
            ip = adb.wifi_ip(d.serial)
            if ip:
                up = tcp_open(ip, 5555, 2.0)
                msgs.append(f"{ip}:5555 {'responde' if up else 'NO responde todavía'}")
                if d.is_usb and up:
                    created.append((d, ip))
            return "; ".join(msgs)

        def after():  # alta de las entradas de red, en el hilo de la UI
            new = [d for d, ip in created if self._wifi_entry(d, ip)]
            if new:
                self.refresh_list()
                self.ctx.log("Añadidas entradas Wi-Fi: " + ", ".join(d.name for d in new))

        self._batch("Activar ADB por Wi-Fi", fn, after)

    def _b_keeper(self):
        """Instala ADB Keeper en los marcados: la depuración inalámbrica se reactiva sola al arrancar."""
        apk = paths.find_keeper()
        if not apk:
            return warn(self, "Falta ADB Keeper", "No se encuentra AdbKeeper.apk (carpeta tools\\helper).")
        devs = self.targets()
        if not devs or not confirm(
                self, "Instalar ADB Keeper",
                f"Se instalará una pequeña app auxiliar en {len(devs)} dispositivo(s): {', '.join(d.name for d in devs)}.\n\n"
                "• Se le concede (una sola vez) el permiso para cambiar ajustes seguros del sistema.\n"
                "• Al arrancar el dispositivo, y cada 15 min con Wi-Fi, vuelve a encender la depuración inalámbrica.\n"
                "• Solo Android 11 o superior. Se puede desinstalar como cualquier app.\n\n"
                "Seguridad: mantiene un puerto de depuración abierto en la red; úsalo en redes de confianza.",
                "adb -s <serie> install -r AdbKeeper.apk\nadb -s <serie> shell pm grant com.atvmaster.adbkeeper "
                "android.permission.WRITE_SECURE_SETTINGS"):
            return

        def fn(d):
            if self.ctx.state_of(d) != "device":
                return "sin conexión: conéctalo por USB o red para instalarlo"
            return "; ".join(self.ctx.adb.install_keeper(d.serial, apk))

        self._batch("Instalar ADB Keeper", fn)

    def _ensure_keeper(self, d: Device) -> list[str]:
        """Deja ADB Keeper instalado y en regla en un dispositivo conectado (se ejecuta en un hilo).
        Si ya estaba, solo repara permiso/exclusión de batería; si falta y es Android 11+, lo instala."""
        adb = self.ctx.adb
        if adb.keeper_status(d.serial)["installed"]:
            return ["permiso/exclusión de batería restablecidos"] if adb.ensure_keeper_permission(d.serial) else []
        apk = paths.find_keeper()
        if not apk or adb.wifi_debug_status(d.serial)["sdk"] < 30:
            return []
        return adb.install_keeper(d.serial, apk)

    def _keep_wifi_adb(self, devs, states):
        """Para los equipos marcados «mantener ADB por Wi-Fi», cada vez que aparecen por USB y no
        tienen el ADB por red activo, se activa solos (y se crea su entrada de red). Es lo más
        parecido a «al iniciar» que permite Android sin root: se dispara al arrancar este programa y
        cada vez que se conecta el cable o el equipo se reinicia estando enchufado."""
        now = time.time()
        for d in devs:
            if not d.keep_wifi_adb:
                continue
            if states.get(d.id) != "device":
                # Si desaparece (reinicio, cable desenchufado) se olvida el antirrebote: al volver
                # hay que comprobarlo de inmediato, aunque la última comprobación fuera hace poco.
                self._wifi_keep.pop(d.id, None)
                continue
            if now - self._wifi_keep.get(d.id, 0) < 300:
                continue
            self._wifi_keep[d.id] = now

            if not d.is_usb:
                # Entrada de red: ya hay ADB por Wi-Fi, solo falta que sobreviva a los reinicios (Keeper).
                self.ctx.run(lambda d=d: self._ensure_keeper(d),
                             lambda msgs, d=d: msgs and self.ctx.log(f"{d.name}: ADB Keeper: {'; '.join(msgs)}"),
                             lambda e, d=d: self.ctx.log(f"✖ {d.name}: ADB Keeper: {e}"))
                continue

            def work(d=d):
                kmsgs = self._ensure_keeper(d)
                if kmsgs:
                    self.ctx.log(f"{d.name}: ADB Keeper: {'; '.join(kmsgs)}")
                st = self.ctx.adb.wifi_debug_status(d.serial)
                if st["tcp_port"] and (st["wireless"] or st["sdk"] < 30):
                    return None, self.ctx.adb.wifi_ip(d.serial)  # ya estaba activo
                msgs = self.ctx.adb.enable_wifi_debug(d.serial)
                ip = ""
                for _ in range(5):  # tras reiniciar adbd, la red puede tardar unos segundos en dar la IP
                    ip = self.ctx.adb.wifi_ip(d.serial)
                    if ip:
                        break
                    time.sleep(2)
                return msgs, ip

            def done(res, d=d):
                msgs, ip = res
                if msgs:
                    self.ctx.log(f"{d.name}: ADB por Wi-Fi reactivado ({'; '.join(msgs)})")
                    if any("apaga" in m or "no se pudo" in m for m in msgs):
                        self._wifi_keep[d.id] = time.time() - 240  # algo falló: se reintenta en ~1 min
                if self._wifi_entry(d, ip):
                    self.refresh_list()
                    self.ctx.log(f"{d.name}: añadida su entrada de red {ip}:5555")

            self.ctx.run(work, done, lambda e, d=d: self.ctx.log(f"✖ {d.name}: no se pudo activar el ADB por Wi-Fi: {e}"))

    def _b_connect(self):
        self._batch("Conectar", lambda d: self.ctx.adb.probe_device(d))

    def _b_disconnect(self):
        self._batch("Desconectar", lambda d: self.ctx.adb.disconnect(d.serial).text)

    def _b_on(self):
        def fn(d: Device) -> str:
            parts = []
            if d.mac and d.ip:  # Wake-on-LAN solo tiene sentido por red
                wol.send_magic_packet(d.mac, d.ip)
                parts.append("WoL enviado")
            if self.ctx.state_of(d) == "device":
                self.ctx.adb.keyevent(d.serial, "KEYCODE_WAKEUP")
                parts.append("WAKEUP enviado")
                if d.kiosk_url and d.kiosk_on_power_on:
                    parts.append("kiosco: " + self.ctx.kiosk.when_ready(d, wait_adb=False))
            return ", ".join(parts) or "sin MAC ni ADB: no se puede encender"

        self._batch("Encender", fn)

    def _b_standby(self):
        self._batch("Standby", lambda d: self.ctx.adb.keyevent(d.serial, "KEYCODE_SLEEP").text or "OK")

    def _b_key(self, code: str, label: str):
        self._batch(f"Tecla {label}", lambda d: self.ctx.adb.keyevent(d.serial, code).text or "OK")

    def _b_reboot(self):
        devs = self.targets()
        if devs and confirm(
            self, "Reiniciar dispositivos",
            f"Se reiniciarán {len(devs)} dispositivo(s): {', '.join(d.name for d in devs)}",
            "\n".join(f"adb -s {d.serial} reboot" for d in devs),
        ):
            self._batch("Reiniciar", lambda d: self.ctx.adb.reboot(d.serial).text or "OK")

    def _b_app(self):
        pkg, ok = QInputDialog.getText(self, "Abrir aplicación", "Nombre del paquete (p. ej. org.videolan.vlc):")
        if ok and pkg.strip():
            self._batch(f"Abrir {pkg}",
                        lambda d: self.ctx.adb.launch(d.serial, pkg.strip()).text[:80])

    # ---------- kiosco ----------
    def _b_kiosk_apply(self):
        def fn(d: Device) -> str:
            if not d.kiosk_url:
                return "sin URL de kiosco configurada"
            return "; ".join(self.ctx.kiosk.apply(d))

        self._batch("Aplicar kiosco", fn)

    def _b_fully(self):
        devs = self.targets()
        if not (devs and confirm(
            self, "Configurar Fully en las dispositivos",
            f"En {len(devs)} dispositivo(s) ({', '.join(d.name for d in devs)}) se abrirán los ajustes de Fully "
            "y se activará «Launch on Boot» y «Keep Screen On», y se guardará la Start URL de cada una "
            "(si la tienen configurada). Tarda ≈1 minuto por dispositivo y sus pantallas mostrarán los ajustes "
            "mientras tanto.",
        )):
            return

        def fn(d: Device) -> str:
            if not self.ctx.kiosk.try_begin(d.id):
                return "ocupada con otra operación de kiosco"
            try:
                return "; ".join(self.ctx.fully.with_pkg(d.kiosk_package).configure(d.serial, d.kiosk_url))
            except Exception as e:
                return f"error: {e}"
            finally:
                self.ctx.kiosk.end(d.id)

        self._batch("Configurar Fully", fn)

    def _b_kiosk_set(self):
        devs = self.targets()
        if not devs:
            return
        url, ok = QInputDialog.getText(
            self, "URL del kiosco", f"URL para {len(devs)} dispositivo(s): {', '.join(d.name for d in devs)}")
        if not ok or not url.strip():
            return
        try:
            url = kiosk.normalize_url(url)
        except ValueError as e:
            return warn(self, "URL no válida", str(e))
        for d in devs:
            d.kiosk_url = url
            self.ctx.store.update(d)
        self.ctx.log(f"URL de kiosco guardada en {len(devs)} dispositivo(s): {url}")
        self.ctx.device_changed.emit()
        if confirm(self, "Aplicar ahora", "¿Abrir la URL ahora en esas dispositivos? (cambiará lo que muestran en este momento)"):
            self._b_kiosk_apply()

    # ---------- menú ----------
    def open_settings(self):
        s = self.ctx.settings
        dlg = SettingsDialog(self, s, paths.find_adb(), paths.find_scrcpy())
        if dlg.exec():
            self.timer.start(int(s.get("poll_seconds")) * 1000)
            self.poll()

    def pair(self):
        d = self.ctx.current

        def after_pair(addr):
            def cb(r):
                self.ctx.log(f"adb pair {addr}: {r.text}")
                if r.ok:  # emparejado: ahora el dispositivo ya puede descubrirse y conectarse
                    self.discover()
            return cb

        def open_dialog(services):
            # Pantalla «Emparejar con código» abierta en algún dispositivo de la red (mDNS).
            cands = [f"{s['ip']}:{s['port']}" for s in services if s["kind"] == "pairing"]
            dlg = PairDialog(self, d.ip if d else "", cands)
            if dlg.exec() and dlg.addr.text().strip() and dlg.code.text().strip():
                addr, code = dlg.addr.text().strip(), dlg.code.text().strip()
                self.ctx.run(lambda: self.ctx.adb.pair(addr, code), after_pair(addr))

        self.ctx.run(lambda: self.ctx.adb.mdns_services(max_age=0), open_dialog,
                     lambda e: open_dialog([]))

    def restart_adb(self):
        def work():
            self.ctx.adb.kill_server()
            return self.ctx.adb.start_server()

        self.ctx.run(work, lambda r: (self.ctx.log("Servidor ADB reiniciado"), self.poll()))

    def _append_log(self, msg: str):
        self.logbox.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def closeEvent(self, e):
        self.timer.stop()
        self.sched_timer.stop()
        if self._mosaic:
            self._mosaic.close()
        if self._tray:
            self._tray.hide()
        for t in self.tab_widgets:
            if hasattr(t, "stop_log"):
                t.stop_log()
        super().closeEvent(e)
