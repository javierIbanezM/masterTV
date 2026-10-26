"""Diálogos: alta/edición de dispositivo, emparejamiento, descubrimiento y configuración."""
from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import wol
from ..store import KIND_LABELS, KINDS, Device
from .common import warn

# Nombre de host o IP (red). Para USB el "host" es el nº de serie, que admite más caracteres.
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")


class DeviceDialog(QDialog):
    """Alta/edición de un dispositivo. Al aceptar, el resultado queda en `self.device`."""

    def __init__(self, parent=None, device: Device | None = None):
        super().__init__(parent)
        self.setWindowTitle("Editar dispositivo" if device else "Añadir dispositivo")
        self.setMinimumWidth(460)
        self.device = device
        f = QFormLayout(self)
        self.name = QLineEdit(device.name if device else "")
        # Conexión: por red (IP:puerto) o por cable (nº de serie USB).
        self.transport = QComboBox()
        self.transport.addItem("Red / Wi-Fi (IP:puerto)", "wifi")
        self.transport.addItem("Cable USB (nº de serie)", "usb")
        self.transport.setCurrentIndex(1 if device and device.is_usb else 0)
        self.transport.currentIndexChanged.connect(self._sync_transport)
        self.host = QLineEdit(device.host if device else "")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(device.port if device else 5555)
        self.mac = QLineEdit(device.mac if device else "")
        self.mac.setPlaceholderText("Opcional · AA:BB:CC:DD:EE:FF (para Wake-on-LAN)")
        self.group = QLineEdit(device.group if device else "")
        self.group.setPlaceholderText("Opcional · p. ej. Planta 1")
        # Tipo de dispositivo: informativo y para ajustar el comportamiento; "auto" lo detecta.
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(KIND_LABELS[k], k)
        self.kind.setCurrentIndex(max(0, KINDS.index(device.kind)) if device and device.kind in KINDS else 0)
        f.addRow("Nombre", self.name)
        f.addRow("Tipo", self.kind)
        f.addRow("Conexión", self.transport)
        self.host_label = QLabel()
        f.addRow(self.host_label, self.host)
        self.port_label = QLabel("Puerto ADB")
        f.addRow(self.port_label, self.port)
        f.addRow("MAC", self.mac)
        f.addRow("Grupo", self.group)
        # Al detectarlo conectado (por red o cable) se instala/repara ADB Keeper, que reactiva solo la
        # depuración inalámbrica al arrancar; si es una entrada USB, además se activa el ADB por Wi-Fi
        # y se crea su entrada de red.
        self.keep = QCheckBox("Mantener el ADB por Wi-Fi activo (instala ADB Keeper al conectarlo, Android 11+)")
        self.keep.setChecked(bool(device and device.keep_wifi_adb))
        f.addRow(self.keep)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._sync_transport()

    def _sync_transport(self):
        """Adapta los campos al tipo de conexión (USB no usa puerto ni MAC)."""
        usb = self.transport.currentData() == "usb"
        self.host_label.setText("Nº de serie USB" if usb else "IP o host")
        self.host.setPlaceholderText("Lo ves con «Descubrir dispositivos»" if usb else "192.168.1.50")
        for w in (self.port, self.port_label, self.mac):
            w.setEnabled(not usb)

    def _ok(self):
        host = self.host.text().strip()
        usb = self.transport.currentData() == "usb"
        valid = _SERIAL_RE.match(host) if usb else _HOST_RE.match(host)
        if not self.name.text().strip() or not valid:
            return warn(self, "Datos incompletos",
                        "Indica un nombre y un nº de serie válidos." if usb
                        else "Indica un nombre y una IP/host válidos.")
        mac = self.mac.text().strip()
        if mac and not usb:
            try:
                mac = wol.normalize_mac(mac)
            except ValueError as e:
                return warn(self, "MAC no válida", str(e))
        d = self.device or Device(name="", host="")
        d.name, d.host, d.port = self.name.text().strip(), host, self.port.value()
        d.mac, d.group = ("" if usb else mac), self.group.text().strip()
        d.transport, d.kind = self.transport.currentData(), self.kind.currentData()
        d.keep_wifi_adb = self.keep.isChecked()
        self.device = d
        self.accept()


class DiscoverDialog(QDialog):
    """Lista lo que adb ve ahora mismo (USB y red) para añadirlo con un clic.
    `found` es el resultado de Adb.devices_detail(); `known` los serial ya guardados."""

    def __init__(self, parent, found: list[dict], known: set[str]):
        super().__init__(parent)
        self.setWindowTitle("Descubrir dispositivos")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Dispositivos que ADB ve ahora mismo. Marca los que quieras añadir.\n"
            "Si un móvil no aparece: activa «Depuración USB», conéctalo por cable y acepta el aviso "
            "de autorización en su pantalla."))
        self.list = QListWidget()
        self._items: list[tuple[QListWidgetItem, dict]] = []
        for dev in found:
            state = {"device": "listo", "unauthorized": "falta autorizar en el dispositivo",
                     "offline": "sin respuesta",
                     "mdns": "visible en la red (se conectará al añadir)"}.get(dev["state"], dev["state"])
            via = "USB" if dev["usb"] else "red"
            it = QListWidgetItem(f"{dev['model'] or 'Dispositivo'} · {dev['serial']} · {via} · {state}")
            if dev["serial"] in known:
                it.setText(it.text() + "  (ya está en la lista)")
                it.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)
            self._items.append((it, dev))
        if not found:
            self.list.addItem("No se ha detectado ningún dispositivo.")
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def selected(self) -> list[dict]:
        return [dev for it, dev in self._items if it.checkState() == Qt.CheckState.Checked]


class ScanDialog(QDialog):
    """Busca en una subred dispositivos con ADB por red abierto (por defecto el puerto 5555) y los
    anunciados por mDNS (depuración inalámbrica de Android 11+). Solo hace conexiones TCP; al
    encontrar uno se conecta con `adb connect` para leer modelo y tipo.

    Si un dispositivo aún no ha autorizado este PC, saldrá «falta autorizar» y en su pantalla
    aparecerá el aviso de «Permitir depuración USB/inalámbrica»."""

    def __init__(self, parent, ctx, known: set[str], subnets: list[str]):
        super().__init__(parent)
        self.ctx, self.known = ctx, known
        self._results: list[tuple[QListWidgetItem, dict]] = []
        self.setWindowTitle("Buscar dispositivos en la red")
        self.setMinimumSize(620, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Busca dispositivos con ADB por red en tu subred. Cada uno debe tener la depuración por red\n"
            "activada (Android 11+: «Depuración inalámbrica»; anteriores: tras `adb tcpip 5555`)."))
        row = QHBoxLayout()
        self.subnet = QComboBox()
        self.subnet.setEditable(True)
        self.subnet.addItems(subnets or ["192.168.1.0/24"])
        self.ports = QLineEdit("5555")
        self.ports.setMaximumWidth(120)
        self.ports.setToolTip("Puertos TCP a probar, separados por comas")
        self.btn = QPushButton("🔍 Buscar")
        self.btn.clicked.connect(self._scan)
        row.addWidget(QLabel("Subred"))
        row.addWidget(self.subnet, 1)
        row.addWidget(QLabel("Puertos"))
        row.addWidget(self.ports)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.status = QLabel("Elige la subred y pulsa Buscar.")
        lay.addWidget(self.status)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Añadir los marcados")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _scan(self):
        cidr = self.subnet.currentText().strip()
        try:
            ports = tuple(int(x) for x in self.ports.text().replace(" ", "").split(",") if x)
            if not ports or not all(0 < p < 65536 for p in ports):
                raise ValueError
        except ValueError:
            return warn(self, "Puertos no válidos", "Escribe puertos entre 1 y 65535 separados por comas.")
        self.btn.setEnabled(False)
        self.list.clear()
        self._results = []
        self.status.setText(f"Buscando en {cidr}… (puede tardar unos segundos)")
        adb = self.ctx.adb

        def work():
            from concurrent.futures import ThreadPoolExecutor
            hits = set(adb.scan_subnet(cidr, ports))
            # Android 11+ anuncia su puerto aleatorio por mDNS: también se incluyen.
            for s in adb.mdns_services(max_age=0):
                if s["kind"] == "connect":
                    hits.add((s["ip"], s["port"]))
            todo = [h for h in sorted(hits) if f"{h[0]}:{h[1]}" not in self.known]
            with ThreadPoolExecutor(max_workers=8) as ex:
                return list(ex.map(lambda h: adb.identify(h[0], h[1]), todo)), len(hits)

        def done(res):
            found, total = res
            self.btn.setEnabled(True)
            labels = {"device": "listo", "unauthorized": "falta autorizar en el dispositivo",
                      "offline": "sin respuesta", "unreachable": "no responde"}
            for dev in found:
                it = QListWidgetItem(f"{dev['model'] or 'Dispositivo'} · {dev['serial']} · "
                                     f"{labels.get(dev['state'], dev['state'])}")
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if dev["state"] in ("device", "unauthorized")
                                 else Qt.CheckState.Unchecked)
                self.list.addItem(it)
                self._results.append((it, dev))
            self.status.setText(f"{total} dirección(es) con ADB abierto, {len(found)} nueva(s) "
                                f"(las que ya tienes en la lista no se repiten).")

        def err(msg):
            self.btn.setEnabled(True)
            self.status.setText(f"Error: {msg}")

        self.ctx.run(work, done, err)

    def selected(self) -> list[dict]:
        return [dev for it, dev in self._results if it.checkState() == Qt.CheckState.Checked]


class PairDialog(QDialog):
    """Emparejamiento inalámbrico (Android 11+): adb pair IP:PUERTO CÓDIGO."""

    def __init__(self, parent=None, host: str = "", candidates: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Emparejar con código")
        self.setMinimumWidth(460)
        f = QFormLayout(self)
        self.addr = QLineEdit(f"{host}:" if host else "")
        self.addr.setPlaceholderText("IP:PUERTO que muestra el dispositivo")
        # Dispositivos que ahora mismo muestran la pantalla «Emparejar con código» (mDNS).
        if candidates:
            self.addr.setText(candidates[0])
            if len(candidates) > 1:
                combo = QComboBox()
                combo.addItems(candidates)
                combo.activated.connect(lambda i: self.addr.setText(candidates[i]))
                f.addRow("Detectados en la red", combo)
        else:
            f.addRow(QLabel("En el dispositivo: Opciones de desarrollador → Depuración inalámbrica →\n"
                            "«Emparejar dispositivo con código», y déjala abierta para que se detecte."))
        self.code = QLineEdit()
        self.code.setPlaceholderText("Código de 6 dígitos")
        f.addRow("IP:PUERTO de emparejamiento", self.addr)
        f.addRow("Código", self.code)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


class SettingsDialog(QDialog):
    """Rutas de adb/scrcpy, carpeta de capturas e intervalo de sondeo. Escribe en `settings`."""

    def __init__(self, parent, settings, adb_found: str | None, scrcpy_found: str | None):
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.setMinimumWidth(560)
        self.s = settings
        f = QFormLayout(self)
        self.adb = QLineEdit(settings.get("adb_path"))
        self.adb.setPlaceholderText(adb_found or "No encontrado")
        self.scrcpy = QLineEdit(settings.get("scrcpy_path"))
        self.scrcpy.setPlaceholderText(scrcpy_found or "No encontrado")
        self.cap = QLineEdit(settings.get("capture_dir"))
        self.cap.setPlaceholderText("Por defecto: Imágenes\\AndroidTvMaster")
        self.poll = QSpinBox()
        self.poll.setRange(3, 300)
        self.poll.setSuffix(" s")
        self.poll.setValue(int(settings.get("poll_seconds")))
        self.auto = QCheckBox("Conectar automáticamente los dispositivos de la lista")
        self.auto.setChecked(bool(settings.get("auto_connect")))
        f.addRow("adb.exe", self._with_browse(self.adb, file_filter="adb (adb.exe)"))
        f.addRow("scrcpy.exe", self._with_browse(self.scrcpy, file_filter="scrcpy (scrcpy.exe)"))
        f.addRow("Carpeta de capturas", self._with_browse(self.cap, folder=True))
        f.addRow("Intervalo de sondeo", self.poll)
        f.addRow(self.auto)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _with_browse(self, edit: QLineEdit, folder: bool = False, file_filter: str = "") -> QWidget:
        """Campo de texto con un botón «…» que abre el selector de archivo o carpeta."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        b = QPushButton("…")
        b.setFixedWidth(32)

        def pick():
            if folder:
                p = QFileDialog.getExistingDirectory(self, "Carpeta")
            else:
                p, _ = QFileDialog.getOpenFileName(self, "Ejecutable", "", f"{file_filter};;Todos (*)")
            if p:
                edit.setText(p)

        b.clicked.connect(pick)
        h.addWidget(edit, 1)
        h.addWidget(b)
        return w

    def _save(self):
        self.s.values.update(
            adb_path=self.adb.text().strip(),
            scrcpy_path=self.scrcpy.text().strip(),
            capture_dir=self.cap.text().strip(),
            poll_seconds=self.poll.value(),
            auto_connect=self.auto.isChecked(),
        )
        self.s.save()
        self.accept()
