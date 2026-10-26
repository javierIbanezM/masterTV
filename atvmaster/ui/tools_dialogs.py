"""Diálogos de herramientas: programación y avisos, y perfiles de preparación."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTime, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QTimeEdit,
    QVBoxLayout, QWidget,
)

from .. import prep, scheduler
from .common import confirm, info, warn


# ============================================================ programación y avisos

class ScheduleEditDialog(QDialog):
    """Alta/edición de una tarea programada. El resultado queda en `self.schedule`."""

    def __init__(self, parent, devices: list, profiles: list[str], schedule: scheduler.Schedule | None = None):
        super().__init__(parent)
        self.setWindowTitle("Editar tarea" if schedule else "Nueva tarea programada")
        self.setMinimumWidth(480)
        self.schedule = schedule
        s = schedule or scheduler.Schedule(name="", time="07:00", action="wake")
        f = QFormLayout(self)
        self.name = QLineEdit(s.name)
        self.name.setPlaceholderText("Ej.: Encender pantallas por la mañana")
        self.time = QTimeEdit(QTime.fromString(s.time, "HH:mm"))
        self.time.setDisplayFormat("HH:mm")
        days_box = QWidget()
        dl = QHBoxLayout(days_box)
        dl.setContentsMargins(0, 0, 0, 0)
        self.days = []
        for i, n in enumerate(scheduler.DAY_NAMES):
            c = QCheckBox(n)
            c.setChecked(i in s.days)
            self.days.append(c)
            dl.addWidget(c)
        self.action = QComboBox()
        for k, v in scheduler.ACTIONS.items():
            self.action.addItem(v, k)
        self.action.setCurrentIndex(max(0, list(scheduler.ACTIONS).index(s.action)))
        self.profile = QComboBox()
        self.profile.addItems(profiles)
        if s.profile in profiles:
            self.profile.setCurrentText(s.profile)
        self.action.currentIndexChanged.connect(self._sync)

        # A quién afecta: todos, un grupo o dispositivos concretos.
        self.mode = QComboBox()
        self.mode.addItems(["Todos los dispositivos", "Un grupo", "Dispositivos concretos"])
        self.group = QComboBox()
        self.group.addItems(sorted({d.group for d in devices if d.group}))
        self.devlist = QListWidget()
        self.devlist.setMaximumHeight(110)
        sel = set(s.targets[4:].split(",")) if s.targets.startswith("ids:") else set()
        for d in devices:
            it = QListWidgetItem(f"{d.name} ({d.address})")
            it.setData(Qt.ItemDataRole.UserRole, d.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if d.id in sel else Qt.CheckState.Unchecked)
            self.devlist.addItem(it)
        if s.targets.startswith("group:"):
            self.mode.setCurrentIndex(1)
            self.group.setCurrentText(s.targets[6:])
        elif s.targets.startswith("ids:"):
            self.mode.setCurrentIndex(2)
        self.mode.currentIndexChanged.connect(self._sync)

        f.addRow("Nombre", self.name)
        f.addRow("Hora", self.time)
        f.addRow("Días", days_box)
        f.addRow("Acción", self.action)
        f.addRow("Perfil", self.profile)
        f.addRow("Afecta a", self.mode)
        f.addRow("Grupo", self.group)
        f.addRow("Dispositivos", self.devlist)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._sync()

    def _sync(self):
        self.profile.setEnabled(self.action.currentData() == "profile")
        self.group.setEnabled(self.mode.currentIndex() == 1)
        self.devlist.setEnabled(self.mode.currentIndex() == 2)

    def _ok(self):
        m = self.mode.currentIndex()
        if m == 1:
            targets = f"group:{self.group.currentText()}"
        elif m == 2:
            ids = [self.devlist.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.devlist.count())
                   if self.devlist.item(i).checkState() == Qt.CheckState.Checked]
            targets = "ids:" + ",".join(ids)
        else:
            targets = "all"
        s = scheduler.Schedule(
            name=self.name.text().strip() or "Tarea", time=self.time.time().toString("HH:mm"),
            action=self.action.currentData(), days=[i for i, c in enumerate(self.days) if c.isChecked()],
            targets=targets, profile=self.profile.currentText() if self.action.currentData() == "profile" else "",
            enabled=self.schedule.enabled if self.schedule else True,
            id=self.schedule.id if self.schedule else scheduler.uuid.uuid4().hex[:8],
        )
        try:
            s.validate()
        except ValueError as e:
            return warn(self, "Datos incompletos", str(e))
        if m == 1 and not self.group.currentText():
            return warn(self, "Sin grupo", "Ningún dispositivo tiene grupo asignado.")
        if m == 2 and targets == "ids:":
            return warn(self, "Sin dispositivos", "Marca al menos un dispositivo.")
        if s.action == "reboot" and not confirm(
                self, "Reinicio programado",
                "Esta tarea REINICIARÁ los dispositivos elegidos cada vez que se dispare. ¿Seguro?"):
            return
        self.schedule = s
        self.accept()


class ScheduleDialog(QDialog):
    """Tareas programadas y avisos de caída. Guarda en los ajustes (settings.json)."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Programación y avisos")
        self.setMinimumSize(700, 560)
        lay = QVBoxLayout(self)

        box = QGroupBox("Tareas programadas")
        bl = QVBoxLayout(box)
        bl.addWidget(QLabel("Se ejecutan mientras esta aplicación está abierta (no es un servicio de Windows): "
                            "si el PC o la app están apagados a esa hora, no se lanzan."))
        self.list = QListWidget()
        bl.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, slot in (("＋ Nueva…", self.add), ("✎ Editar…", self.edit), ("✖ Quitar", self.remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        bl.addLayout(row)
        lay.addWidget(box, 2)

        ab = QGroupBox("Avisos cuando un dispositivo deja de responder")
        af = QFormLayout(ab)
        st = ctx.settings
        self.a_on = QCheckBox("Avisar de caídas y recuperaciones")
        self.a_on.setChecked(bool(st.get("alerts_enabled")))
        self.a_n = QSpinBox()
        self.a_n.setRange(1, 20)
        self.a_n.setValue(int(st.get("alerts_threshold") or 3))
        self.a_n.setSuffix(" sondeos seguidos")
        self.a_tray = QCheckBox("Notificación de Windows (bandeja del sistema)")
        self.a_tray.setChecked(bool(st.get("alerts_tray")))
        self.a_hook = QLineEdit(st.get("alerts_webhook") or "")
        self.a_hook.setPlaceholderText("Webhook de Teams/Slack/Discord, o Telegram: …/sendMessage?chat_id=ID")
        test = QPushButton("Enviar aviso de prueba")
        test.clicked.connect(self._test_hook)
        af.addRow(self.a_on)
        af.addRow("Avisar tras", self.a_n)
        af.addRow(self.a_tray)
        af.addRow("Webhook (opcional)", self.a_hook)
        af.addRow(test)
        af.addRow(QLabel("Un dispositivo solo avisa si alguna vez estuvo en línea. El aviso también se "
                         "escribe siempre en el registro."))
        lay.addWidget(ab)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.items = scheduler.load(st.get("schedules") or [])
        self._fill()

    def _profiles(self) -> list[str]:
        return sorted((self.ctx.settings.get("profiles") or {}).keys())

    def _fill(self):
        self.list.clear()
        for s in self.items:
            it = QListWidgetItem(f"{s.name}  —  {s.describe()}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if s.enabled else Qt.CheckState.Unchecked)
            self.list.addItem(it)

    def _sync_enabled(self):
        for i, s in enumerate(self.items):
            s.enabled = self.list.item(i).checkState() == Qt.CheckState.Checked

    def add(self):
        dlg = ScheduleEditDialog(self, self.ctx.store.devices, self._profiles())
        if dlg.exec():
            self._sync_enabled()
            self.items.append(dlg.schedule)
            self._fill()

    def edit(self):
        i = self.list.currentRow()
        if i < 0:
            return warn(self, "Sin selección", "Selecciona una tarea.")
        self._sync_enabled()
        dlg = ScheduleEditDialog(self, self.ctx.store.devices, self._profiles(), self.items[i])
        if dlg.exec():
            self.items[i] = dlg.schedule
            self._fill()

    def remove(self):
        i = self.list.currentRow()
        if i >= 0:
            self._sync_enabled()
            del self.items[i]
            self._fill()

    def _test_hook(self):
        url = self.a_hook.text().strip()
        if not url:
            return warn(self, "Sin webhook", "Escribe la URL del webhook.")
        self.ctx.run(lambda: scheduler.post_webhook(url, "🧪 Aviso de prueba de Android TV Master"),
                     lambda _: info(self, "Webhook", "Enviado. Comprueba que ha llegado."),
                     lambda e: warn(self, "No se pudo enviar", str(e)))

    def _save(self):
        self._sync_enabled()
        st = self.ctx.settings
        hook = self.a_hook.text().strip()
        if hook and not hook.lower().startswith(("http://", "https://")):
            return warn(self, "Webhook no válido", "Debe empezar por http:// o https://")
        st.values.update(schedules=scheduler.dump(self.items), alerts_enabled=self.a_on.isChecked(),
                         alerts_threshold=self.a_n.value(), alerts_tray=self.a_tray.isChecked(),
                         alerts_webhook=hook)
        st.save()
        self.accept()


# ============================================================ perfiles de preparación

class ProfilesDialog(QDialog):
    """Editor de perfiles de preparación. `apply_requested(nombre)` se emite al pulsar «Aplicar»."""

    apply_requested = pyqtSignal(str)

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Perfiles de preparación")
        self.setMinimumSize(760, 520)
        self.profiles: dict[str, str] = dict(ctx.settings.get("profiles") or {})
        if not self.profiles:
            self.profiles["Terminal de almacén (ejemplo)"] = prep.EXAMPLE
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._load)
        left.addWidget(QLabel("<b>Perfiles</b>"))
        left.addWidget(self.list, 1)
        for text, slot in (("＋ Nuevo", self.new), ("✖ Eliminar", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            left.addWidget(b)
        right = QVBoxLayout()
        right.addWidget(QLabel(
            "Un paso por línea (# = comentario). Pasos: setting · stayawake · timeout · animations · brightness · "
            "rotation · density · install · uninstall · grant · launch · kiosk · wake · home.\n"
            "Cada línea se valida; no se pueden ejecutar comandos libres."))
        self.text = QPlainTextEdit()
        self.text.setStyleSheet("font-family: Consolas, monospace;")
        right.addWidget(self.text, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        row = QHBoxLayout()
        for text, slot in (("✔ Validar", self.validate), ("💾 Guardar", self.save),
                           ("▶ Guardar y aplicar a los marcados…", self.apply)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        right.addLayout(row)
        lay.addLayout(left, 1)
        lay.addLayout(right, 3)
        self._refill()

    def _refill(self, select: str | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems(sorted(self.profiles))
        self.list.blockSignals(False)
        names = sorted(self.profiles)
        name = select if select in self.profiles else (names[0] if names else None)
        if name:
            self.list.setCurrentRow(names.index(name))
            self._load(name)

    def _load(self, name: str):
        self.text.setPlainText(self.profiles.get(name, ""))
        self.status.setText("")

    def current(self) -> str | None:
        it = self.list.currentItem()
        return it.text() if it else None

    def new(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Nuevo perfil", "Nombre del perfil:")
        name = name.strip()
        if ok and name:
            self.profiles.setdefault(name, "# Un paso por línea\n")
            self._refill(name)

    def delete(self):
        n = self.current()
        if n and confirm(self, "Eliminar perfil", f"Se eliminará el perfil «{n}»."):
            del self.profiles[n]
            self.ctx.settings.set("profiles", dict(self.profiles))
            self._refill()

    def validate(self) -> bool:
        try:
            steps = prep.parse(self.text.toPlainText())
        except prep.ProfileError as e:
            self.status.setText(f"✖ {e}")
            return False
        self.status.setText(f"✔ Perfil válido: {len(steps)} paso(s).")
        return True

    def save(self) -> bool:
        n = self.current()
        if not n or not self.validate():
            return False
        self.profiles[n] = self.text.toPlainText()
        self.ctx.settings.set("profiles", dict(self.profiles))
        self.status.setText(self.status.text() + "  Guardado.")
        return True

    def apply(self):
        if self.save():
            self.apply_requested.emit(self.current())
