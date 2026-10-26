"""Configura Fully Kiosk (versión gratuita) navegando por sus ajustes con uiautomator.

Guarda la «Start URL» y activa «Launch on Boot» / «Keep Screen On» DENTRO del dispositivo, de modo que
el kiosco arranque solo, sin depender de este programa. Fully no expone ningún intent ni API
gratuita para ello, por eso se maneja su interfaz como lo haría una persona con el mando.
Los textos son los de Fully en inglés.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from typing import Callable

from .adb import Adb, AdbError, shell_quote

FULLY_PKG = "de.ozerov.fully"
EMM_PKG = "com.fullykiosk.emm"
_NODE = re.compile(r"<node\b([^>]*)>")
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass
class UiNode:
    text: str
    rid: str
    cls: str
    checked: bool
    x: int
    y: int


def parse_ui(xml: str) -> list[UiNode]:
    nodes = []
    for m in _NODE.finditer(xml):
        a = {k: html.unescape(v) for k, v in _ATTR.findall(m.group(1))}
        b = _BOUNDS.search(a.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = map(int, b.groups())
        nodes.append(UiNode(
            a.get("text", ""),
            a.get("resource-id", "").split("/")[-1],
            a.get("class", "").split(".")[-1],
            a.get("checked") == "true",
            (x1 + x2) // 2,
            (y1 + y2) // 2,
        ))
    return nodes


class FullyConfigurator:
    def __init__(self, adb: Adb, log: Callable[[str], None] = print, pkg: str = FULLY_PKG):
        self.adb, self.log, self.pkg = adb, log, pkg

    def with_pkg(self, pkg: str) -> "FullyConfigurator":
        """Mismo asistente pero para otra edición de Fully (Play o EMM)."""
        return FullyConfigurator(self.adb, self.log, pkg)

    def dump(self, s: str) -> list[UiNode]:
        """Lee la pantalla con `uiautomator dump` (XML con todos los elementos y sus coordenadas).
        Se reintenta 3 veces porque justo tras una transición de pantalla suele salir vacío."""
        for _ in range(3):
            self.adb.shell(s, "uiautomator dump /sdcard/.atvm_ui.xml >/dev/null 2>&1", timeout=40)
            xml = self.adb.shell(s, "cat /sdcard/.atvm_ui.xml; rm -f /sdcard/.atvm_ui.xml",
                                 timeout=30).out
            if "<node" in xml:
                return parse_ui(xml)
            time.sleep(1.5)
        raise AdbError("No se pudo leer la pantalla del dispositivo (uiautomator)")

    def tap(self, s: str, n: UiNode) -> None:
        self.adb.tap(s, n.x, n.y)
        time.sleep(1.5)

    @staticmethod
    def _title(nodes: list[UiNode], title: str) -> UiNode | None:
        return next((n for n in nodes if n.rid == "title" and n.text == title), None)

    # En la pantalla de ajustes de Fully cada fila es: título (rid "title"), resumen ("summary")
    # y, si es un interruptor, un "switch_widget". Pertenecen a la misma fila cuando su
    # coordenada Y está a menos de 40 px por debajo del título.
    @staticmethod
    def _switch(nodes: list[UiNode], title: UiNode) -> UiNode | None:
        cands = [n for n in nodes if n.rid == "switch_widget" and 0 <= n.y - title.y <= 40]
        return min(cands, key=lambda n: n.y - title.y) if cands else None

    @staticmethod
    def _summary(nodes: list[UiNode], title: UiNode) -> str:
        cands = [n for n in nodes if n.rid == "summary" and 0 <= n.y - title.y <= 40]
        return cands[0].text if cands else ""

    def _find(self, s: str, title: str, swipes: int = 10) -> tuple[list[UiNode], UiNode]:
        """Localiza una fila de ajustes, desplazando la lista si hace falta."""
        info = self.adb.display_info(s)
        w, h = info["width"], info["height"]
        for _ in range(swipes + 1):
            nodes = self.dump(s)
            t = self._title(nodes, title)
            if t:
                return nodes, t
            self.adb.swipe(s, w // 2, int(h * 0.8), w // 2, int(h * 0.25), 400)
            time.sleep(1)
        raise AdbError(f"No encuentro «{title}» en los ajustes de Fully (¿idioma distinto de inglés?)")

    def _settings_state(self, s: str) -> str:
        """'main' (lista principal), 'inner' (dentro de una categoría) o 'out' (fuera de los ajustes)."""
        nodes = self.dump(s)
        if any(n.rid == "button1" for n in nodes):
            return "inner"
        if any(n.text == "Search in Settings" for n in nodes):
            return "main"
        in_settings = any(
            (n.rid in ("list_container", "list") and n.cls in ("FrameLayout", "ListView"))
            or (n.rid == "summary" and n.cls == "TextView")
            for n in nodes
        )
        return "inner" if in_settings else "out"

    def _answer_start_url_prompt(self, s: str, nodes: list[UiNode] | None = None) -> bool:
        """Fully pregunta «Open the new Start URL now?» tras cambiarla: se acepta (YES)."""
        nodes = nodes or self.dump(s)
        if any(n.rid == "alertTitle" and "Start URL" in n.text for n in nodes):
            yes = next((n for n in nodes if n.rid == "button1"), None)
            if yes:
                self.tap(s, yes)
                time.sleep(3)
                return True
        return False

    def open_settings(self, s: str) -> None:
        # Si ya estamos dentro de una categoría de ajustes, se retrocede hasta la lista principal.
        state = self._settings_state(s)
        for _ in range(6):
            if state != "inner":
                break
            self.adb.keyevent(s, "KEYCODE_BACK")
            time.sleep(2)
            state = self._settings_state(s)
        if state == "main":
            return
        info = self.adb.display_info(s)
        w, h = info["width"], info["height"]
        if self.adb.foreground(s)[1] != self.pkg:
            self.adb.launch(s, self.pkg)
            time.sleep(6)
        # Fully no tiene un intent para abrir sus ajustes: se despliega su menú lateral deslizando
        # desde el borde izquierdo y se pulsa el icono de ajustes. Las posiciones son relativas
        # a la resolución (pensadas para pantalla horizontal, como una TV); en móviles en
        # vertical pueden no acertar: allí es preferible usar la Administración remota (REST).
        self.adb.swipe(s, 2, h // 2, int(w * 0.3), h // 2, 300)
        time.sleep(2)
        self.adb.tap(s, int(w * 0.052), int(h * 0.093))
        time.sleep(3)
        if not any(n.text == "Search in Settings" for n in self.dump(s)):
            raise AdbError("No se pudieron abrir los ajustes de Fully")

    def back_to_main_list(self, s: str) -> None:
        self.adb.keyevent(s, "KEYCODE_BACK")
        time.sleep(2)
        if not any(n.text == "Search in Settings" for n in self.dump(s)):
            raise AdbError("Al volver atrás se salió de los ajustes de Fully")

    def open_category(self, s: str, title: str, expect: str) -> None:
        """Entra en una categoría y comprueba que aparece una fila propia de ella (`expect`)."""
        _, t = self._find(s, title)
        self.tap(s, t)
        nodes = self.dump(s)
        if any(n.text == expect for n in nodes):
            return
        if not any(n.rid == "title" and n.text == title and n.y < 40 for n in nodes):
            raise AdbError(f"No se abrió «{title}»")

    def read_start_url(self, s: str) -> str:
        nodes, t = self._find(s, "Start URL")
        return self._summary(nodes, t)

    def set_start_url(self, s: str, url: str) -> None:
        nodes, t = self._find(s, "Start URL")
        current = self._summary(nodes, t)
        self.tap(s, t)
        edit = next((n for n in self.dump(s) if n.cls == "EditText"), None)
        if not edit:
            raise AdbError("No se abrió el cuadro de edición de «Start URL»")
        self.adb.tap(s, edit.x, edit.y)
        time.sleep(1)
        # Vaciar el campo y escribir la nueva URL
        self.adb.shell(s, "input keyevent KEYCODE_MOVE_END " +
                       " ".join(["KEYCODE_DEL"] * (len(current) + 10)))
        self.adb.text(s, url)
        time.sleep(0.5)
        dlg = self.dump(s)
        ok = (next((n for n in dlg if n.rid == "button1"), None)
              or next((n for n in dlg if n.cls == "Button"
                       and n.text.upper() in ("OK", "ACEPTAR", "ACCEPT")), None))
        if not ok:
            raise AdbError("No se encuentra el botón de aceptar del cuadro de «Start URL»")
        self.tap(s, ok)
        self._answer_start_url_prompt(s)
        got = self.read_start_url(s)
        if got != url:
            raise AdbError(f"La Start URL quedó como «{got}» y no como «{url}»")

    def ensure_switch(self, s: str, title: str, want: bool) -> tuple[bool, bool]:
        """Devuelve (valor_antes, valor_despues)."""
        nodes, t = self._find(s, title)
        sw = self._switch(nodes, t)
        if not sw:
            raise AdbError(f"«{title}» no es un interruptor")
        before = sw.checked
        if before != want:
            self.tap(s, sw)
            nodes, t = self._find(s, title)
            sw = self._switch(nodes, t)
            if not sw or sw.checked != want:
                raise AdbError(f"No se pudo cambiar «{title}» (¿pide algún permiso en pantalla?)")
        return before, want

    def configure(self, s: str, url: str = "", launch_on_boot: bool = True,
                  keep_screen_on: bool = True, check_only: bool = False) -> list[str]:
        report: list[str] = []
        self.open_settings(s)

        self.open_category(s, "Web Content Settings", expect="Start URL")
        cur = self.read_start_url(s)
        if url and cur != url and not check_only:
            self.set_start_url(s, url)
            report.append(f"Start URL: {cur or '(vacía)'} → {url}")
        else:
            report.append(f"Start URL: {cur}" +
                          ("" if not url or cur == url else "  (distinta de la configurada)"))
        self.back_to_main_list(s)

        self.open_category(s, "Device Management", expect="Keep Screen On")
        for title, want in (("Launch on Boot", launch_on_boot), ("Keep Screen On", keep_screen_on)):
            if check_only:
                nodes, t = self._find(s, title)
                sw = self._switch(nodes, t)
                report.append(f"{title}: {'activado' if sw and sw.checked else 'DESACTIVADO'}")
                continue
            before, after = self.ensure_switch(s, title, want)
            report.append(f"{title}: {'activado' if after else 'desactivado'}" +
                          ("" if before == after else
                           f" (antes: {'activado' if before else 'desactivado'})"))
        self.exit_settings(s)
        target = url or cur
        if target:
            self.adb.kiosk_launch(s, target, self.pkg)
        else:
            self.adb.launch(s, self.pkg)
        return report

    def exit_settings(self, s: str) -> None:
        """Vuelve a la página pulsando «Atrás» solo mientras se vean los ajustes: una pulsación
        de más cerraría Fully y dejaría el dispositivo en el inicio de Android."""
        for _ in range(5):
            nodes = self.dump(s)
            if self._answer_start_url_prompt(s, nodes):
                continue
            if self._settings_state(s) == "out":
                return
            self.adb.keyevent(s, "KEYCODE_BACK")
            time.sleep(2)
        raise AdbError("No se pudo salir de los ajustes de Fully")
