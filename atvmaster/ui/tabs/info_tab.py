from __future__ import annotations

import time

from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHeaderView,
)

from ... import wol
from ..base_tab import DeviceTab
from ...store import Device
from ..common import confirm, info, warn


class InfoTab(DeviceTab):
    """Resumen del dispositivo (propiedades, tipo, batería, red, almacenamiento) y botones de
    energía: encender (Wake-on-LAN + KEYCODE_WAKEUP), standby, reiniciar y apagar."""

    title = "Resumen y energía"
    key = "info"  # identificador para profiles.py

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = QVBoxLayout(self)

        power = QGroupBox("Energía")
        pl = QHBoxLayout(power)
        self._power_btns = {}
        for text, slot in (("⏻ Encender", self.power_on), ("☾ Standby", self.standby),
                           ("↻ Reiniciar", self.reboot), ("⏹ Apagar del todo", self.power_off)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            pl.addWidget(b)
            self._power_btns[text] = b
        lay.addWidget(power)

        top = QHBoxLayout()
        self.refresh_btn = QPushButton("Actualizar información")
        self.refresh_btn.clicked.connect(self.refresh)
        self.mac_btn = QPushButton("Detectar y guardar MAC")
        self.mac_btn.clicked.connect(self.detect_mac)
        # Solo útil con dispositivos conectados por cable: activa ADB por red y crea la entrada Wi-Fi.
        self.wifi_btn = QPushButton("Pasar de USB a Wi-Fi")
        self.wifi_btn.clicked.connect(self.enable_wifi)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.mac_btn)
        top.addWidget(self.wifi_btn)
        top.addStretch(1)
        lay.addLayout(top)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Propiedad", "Valor"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        lay.addWidget(self.table, 3)

        lay.addWidget(QLabel("Almacenamiento y memoria"))
        self.storage = QPlainTextEdit()
        self.storage.setReadOnly(True)
        self.storage.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(self.storage, 2)

    def apply_kind(self, kind: str, show_all: bool) -> None:
        """«Apagar del todo» solo en TV/cajas: en móviles y tablets suele pedir root."""
        from ...profiles import has_feature
        self._power_btns["⏹ Apagar del todo"].setVisible(has_feature(kind, "power_off", show_all))

    def on_device_changed(self):
        self.table.setRowCount(0)
        self.storage.clear()
        d = self.ctx.current
        self.wifi_btn.setEnabled(bool(d and d.is_usb))
        self.mac_btn.setEnabled(bool(d and not d.is_usb))  # la MAC solo sirve para Wake-on-LAN

    def on_activated(self):
        if self.ctx.current and self.is_online() and self.table.rowCount() == 0:
            self.refresh()

    def refresh(self):
        def work(s):
            return (self.ctx.adb.device_info(s),
                    self.ctx.adb.shell(s, "df -h; echo; head -n 4 /proc/meminfo", timeout=30).out)

        def done(res):
            data, st = res
            self.table.setRowCount(len(data))
            for i, (k, v) in enumerate(data.items()):
                self.table.setItem(i, 0, QTableWidgetItem(k))
                self.table.setItem(i, 1, QTableWidgetItem(v))
            self.storage.setPlainText(st)

        self.call(work, done)

    def enable_wifi(self):
        """USB -> Wi-Fi: `adb tcpip 5555`, lee la IP del dispositivo y ofrece guardarlo por red.
        Después el cable ya no hace falta (el dispositivo debe estar en la misma red que el PC)."""
        d = self.ctx.current
        if not d or not d.is_usb:
            return warn(self, "Sin dispositivo USB", "Selecciona un dispositivo conectado por USB.")

        def work(s):
            self.ctx.adb.enable_wifi_debug(s)  # depuración inalámbrica (Android 11+) + ADB clásico 5555
            time.sleep(1)
            return self.ctx.adb.wifi_ip(s)

        def done(ip):
            if not ip:
                return warn(self, "Sin IP", "El dispositivo no tiene IP en la red (¿Wi-Fi apagado?).")
            if confirm(self, "ADB por Wi-Fi activado",
                       f"El dispositivo está en {ip}:5555.\n¿Añadirlo a la lista como dispositivo de red?",
                       f"adb connect {ip}:5555"):
                self.ctx.store.add(Device(name=f"{d.name} (Wi-Fi)", host=ip, group=d.group, kind=d.kind))
                self.ctx.status_changed.emit()

        self.call(work, done)

    def detect_mac(self):
        d = self.ctx.current
        if not d:
            return warn(self, "Sin dispositivo", "Selecciona un dispositivo primero.")

        def work(s):
            return self.ctx.adb.mac(s)

        def done(mac):
            if not mac:
                return warn(self, "MAC no encontrada",
                            "El dispositivo no expone su MAC y no está en la caché ARP del PC. "
                            "Introdúcela a mano editando el dispositivo.")
            d.mac = mac
            self.ctx.store.update(d)
            info(self, "MAC guardada", f"{d.name}: {mac}")
            self.ctx.status_changed.emit()

        self.call(work, done)

    def power_on(self):
        d = self.ctx.current
        if not d:
            return warn(self, "Sin dispositivo", "Selecciona un dispositivo primero.")

        def work(s):
            msgs = []
            if d.mac and d.ip:  # Wake-on-LAN: solo para dispositivos por red
                try:
                    sent = wol.send_magic_packet(d.mac, d.ip)
                    msgs.append(f"Wake-on-LAN enviado a {', '.join(sent)}")
                except ValueError as e:
                    msgs.append(str(e))
            if self.ctx.state_of(d) == "device":
                self.ctx.adb.keyevent(s, "KEYCODE_WAKEUP")
                msgs.append("KEYCODE_WAKEUP enviado por ADB")
                if d.kiosk_url and d.kiosk_on_power_on:
                    msgs.append("kiosco: " + self.ctx.kiosk.when_ready(d, wait_adb=False))
            elif not d.mac:
                msgs.append("Sin conexión ADB y sin MAC guardada: no hay forma de despertarlo.")
            return "; ".join(msgs)

        self.ctx.run(lambda: work(d.serial), lambda m: self.ctx.log(f"{d.name}: {m}"))

    def standby(self):
        self.call(lambda s: self.ctx.adb.keyevent(s, "KEYCODE_SLEEP"),
                  lambda r: self.ctx.log("Standby enviado (KEYCODE_SLEEP)"))

    def reboot(self):
        s = self.serial()
        if s and confirm(self, "Reiniciar dispositivo", "Se reiniciará el dispositivo y se perderá la conexión.",
                         f"adb -s {s} reboot"):
            self.call(lambda s: self.ctx.adb.reboot(s), lambda r: self.ctx.log("Reinicio enviado"))

    def power_off(self):
        s = self.serial()
        if s and confirm(
            self, "Apagar del todo",
            "El dispositivo se apagará por completo. Para encenderla tendrás que usar el mando o "
            "Wake-on-LAN (si tu modelo lo soporta).",
            f"adb -s {s} shell reboot -p",
        ):
            self.call(lambda s: self.ctx.adb.power_off(s), lambda r: self.ctx.log("Apagado enviado"))
