"""Pruebas de la lógica de Android TV Master (no necesitan PyQt ni dispositivos).

Ejecutar desde la carpeta del proyecto:   python -m unittest discover -s tests -v
"""
import csv
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atvmaster import inventory, kiosk, prep, profiles, scheduler, wol  # noqa: E402
from atvmaster.adb import Adb, Result, is_dangerous_shell  # noqa: E402
from atvmaster.store import Device  # noqa: E402


class FakeAdb(Adb):
    """Adb con respuestas guardadas: registra cada llamada y no ejecuta nada real."""

    def __init__(self, shell_map=None, run_map=None):
        super().__init__(lambda: "adb")
        self.shell_map, self.run_map, self.log = shell_map or {}, run_map or {}, []

    def run(self, args, serial=None, timeout=20, input_data=None):
        self.log.append(("run", tuple(args)))
        for k, v in self.run_map.items():
            if tuple(args)[: len(k)] == k:
                return v
        return Result(0, "", "")

    def shell(self, serial, command, timeout=20):
        self.log.append(("shell", command))
        for k, v in self.shell_map.items():
            if k in command:
                return v
        return Result(0, "", "")


class TestDevice(unittest.TestCase):
    def test_serial_wifi_y_usb(self):
        self.assertEqual(Device(name="a", host="10.0.0.5").serial, "10.0.0.5:5555")
        u = Device(name="u", host="ABC123", transport="usb")
        self.assertEqual((u.serial, u.ip, u.address), ("ABC123", "", "USB ABC123"))

    def test_tipo_efectivo(self):
        d = Device(name="a", host="h")
        self.assertEqual(d.effective_kind, "auto")
        d.detected_kind = "pda"
        self.assertEqual(d.effective_kind, "pda")
        d.kind = "tv"  # lo elegido a mano manda sobre lo detectado
        self.assertEqual(d.effective_kind, "tv")


class TestProfiles(unittest.TestCase):
    def test_pestanas_por_tipo(self):
        self.assertNotIn("kiosk", profiles.tabs_for("phone"))
        self.assertIn("kiosk", profiles.tabs_for("pda"))
        self.assertEqual(profiles.tabs_for("auto"), profiles.ALL_TABS)
        self.assertEqual(profiles.tabs_for("phone", show_all=True), profiles.ALL_TABS)

    def test_funciones(self):
        self.assertTrue(profiles.has_feature("tv", "channels"))
        self.assertFalse(profiles.has_feature("phone", "channels"))
        self.assertTrue(profiles.has_feature("pda", "pda_extras"))
        self.assertTrue(profiles.has_feature("auto", "gestures"))  # tipo desconocido: se muestra todo


class TestAdbParsing(unittest.TestCase):
    def test_mdns_moderno_y_clasico(self):
        a = FakeAdb(run_map={("mdns", "services"): Result(
            0,
            "List of discovered mdns services\n"
            "adb-A\t_adb-tls-connect._tcp\t192.168.2.50:41234\n"
            "adb-A\t_adb-tls-pairing._tcp\t192.168.2.50:37051\n"
            "adb-S21L04768\t_adb._tcp\t192.168.60.205:5555\n", "")})
        got = [(s["kind"], s["ip"], s["port"]) for s in a.mdns_services(max_age=0)]
        self.assertEqual(got, [("connect", "192.168.2.50", 41234), ("pairing", "192.168.2.50", 37051),
                               ("connect", "192.168.60.205", 5555)])
        self.assertEqual(a.mdns_port_for("192.168.2.50"), 41234)

    def test_devices_detail_incluye_mdns_no_conectados(self):
        a = FakeAdb(run_map={
            ("devices", "-l"): Result(0, "List of devices attached\nS26EC0772 device usb:1 model:Memor_11 transport_id:3", ""),
            ("mdns", "services"): Result(0, "x\nadb-B\t_adb._tcp\t192.168.60.205:5555", ""),
        })
        det = {d["serial"]: d for d in a.devices_detail()}
        self.assertTrue(det["S26EC0772"]["usb"])
        self.assertEqual(det["S26EC0772"]["model"], "Memor 11")
        self.assertEqual(det["192.168.60.205:5555"]["state"], "mdns")

    def test_detect_kind(self):
        def k(chars="default", vendor="Google", leanback="false"):
            return FakeAdb(shell_map={"ro.build.characteristics": Result(0, chars, ""),
                                      "ro.product.manufacturer": Result(0, vendor, ""),
                                      "ro.product.brand": Result(0, vendor, ""),
                                      "has-feature": Result(0, leanback, "")}).detect_kind("s")
        self.assertEqual(k(chars="tv"), "tv")
        self.assertEqual(k(vendor="Datalogic"), "pda")
        self.assertEqual(k(vendor="Zebra Technologies"), "pda")
        self.assertEqual(k(chars="tablet"), "tablet")
        self.assertEqual(k(leanback="true"), "tv")
        self.assertEqual(k(), "phone")

    def test_battery(self):
        a = FakeAdb(shell_map={"dumpsys battery": Result(0, "  level: 36\n  status: 2", "")})
        self.assertEqual(a.battery("s"), "36 % (cargando)")

    def test_peligrosos(self):
        for c in ("rm -rf /sdcard", "pm uninstall x", "reboot", "settings put global a b", "wm size 1x1"):
            self.assertTrue(is_dangerous_shell(c), c)
        for c in ("ls /sdcard", "getprop ro.product.model", "dumpsys battery"):
            self.assertFalse(is_dangerous_shell(c), c)

    def test_scan_subnet_rechaza_redes_enormes(self):
        with self.assertRaises(Exception):
            Adb.scan_subnet("10.0.0.0/8")


class TestInstall(unittest.TestCase):
    def test_apk_simple_y_formato_invalido(self):
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d, "a.apk"); apk.write_bytes(b"x")
            a = FakeAdb()
            a.install_any("s", str(apk))
            self.assertEqual(a.log[-1], ("run", ("install", "-r", str(apk))))
            bad = Path(d, "a.exe"); bad.write_bytes(b"x")
            self.assertEqual(a.install_any("s", str(bad)).rc, 1)
            self.assertEqual(a.install_any("s", str(Path(d, "no_existe.apk"))).rc, 1)

    def test_paquete_dividido_usa_install_multiple_y_evita_rutas(self):
        with tempfile.TemporaryDirectory() as d:
            z = Path(d, "app.xapk")
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("base.apk", b"1"); zf.writestr("../../evil.apk", b"2"); zf.writestr("icon.png", b"3")
            a = FakeAdb()
            a.install_any("s", str(z))
            kind, args = a.log[-1]
            self.assertEqual(args[:2], ("install-multiple", "-r"))
            names = sorted(Path(x).name for x in args[2:])
            self.assertEqual(names, ["base.apk", "evil.apk"])  # solo el nombre base: sin salir de la carpeta
            self.assertFalse(Path(d, "..", "evil.apk").exists())

    def test_zip_corrupto(self):
        with tempfile.TemporaryDirectory() as d:
            z = Path(d, "roto.apks"); z.write_bytes(b"no es un zip")
            self.assertEqual(FakeAdb().install_any("s", str(z)).rc, 1)


class TestPrep(unittest.TestCase):
    def test_perfil_valido(self):
        steps = prep.parse(prep.EXAMPLE + "\ngrant com.a.b CAMERA\nkiosk srv.local/x com.fullykiosk.emm  # comentario\nwake\n")
        self.assertEqual([s.name for s in steps],
                         ["stayawake", "timeout", "animations", "grant", "kiosk", "wake"])
        self.assertEqual(steps[1].args, ["600000"])  # 10m -> ms
        self.assertEqual(steps[4].args[0], "http://srv.local/x")

    def test_rechaza_lo_peligroso_o_mal_formado(self):
        for linea in ("shell rm -rf /", "setting global a b; reboot", "setting foo a b", "brightness 999",
                      "timeout 1s", "uninstall no_es_paquete", "grant com.a.b $(reboot)",
                      "density 5", "kiosk http://a b", "stayawake maybe", "wake ahora"):
            with self.assertRaises(prep.ProfileError, msg=linea):
                prep.parse(linea)

    def test_error_indica_la_linea(self):
        with self.assertRaises(prep.ProfileError) as cm:
            prep.parse("wake\n\nbrightness 999")
        self.assertIn("Línea 3", str(cm.exception))

    def test_ejecucion_y_proteccion_de_apps_de_sistema(self):
        a = FakeAdb(shell_map={"pm list packages -3": Result(0, "package:com.user.app", "")})
        d = Device(name="x", host="h")
        msgs, changed = prep.run(a, d, prep.parse(
            "stayawake on\nkiosk http://s/x\nuninstall com.android.settings\nuninstall com.user.app"))
        self.assertTrue(changed and d.kiosk_url == "http://s/x")
        self.assertTrue(any("sistema" in m and m.startswith("✖") for m in msgs))     # protegida
        self.assertIn(("run", ("uninstall", "com.user.app")), a.log)                  # la de usuario sí
        self.assertNotIn(("run", ("uninstall", "com.android.settings")), a.log)
        self.assertTrue(any("stay_on_while_plugged_in" in c for k, c in a.log if k == "shell"))


class TestScheduler(unittest.TestCase):
    def test_disparo_por_hora_y_dia(self):
        s = scheduler.Schedule(name="n", time="07:00", action="wake", days=[0])   # lunes
        lunes = datetime(2026, 10, 19, 7, 0)
        self.assertTrue(scheduler.is_due(s, lunes))
        self.assertFalse(scheduler.is_due(s, datetime(2026, 10, 20, 7, 0)))       # martes
        self.assertFalse(scheduler.is_due(s, datetime(2026, 10, 19, 7, 1)))       # otro minuto
        scheduler.mark_run(s, lunes)
        self.assertFalse(scheduler.is_due(s, lunes))                              # no repite en el mismo minuto
        s.enabled, s.last_run = False, ""
        self.assertFalse(scheduler.is_due(s, lunes))

    def test_validacion_y_carga_tolerante(self):
        with self.assertRaises(ValueError):
            scheduler.Schedule(name="n", time="25:00", action="wake").validate()
        with self.assertRaises(ValueError):
            scheduler.Schedule(name="n", time="07:00", action="profile").validate()   # falta el perfil
        ok = scheduler.dump([scheduler.Schedule(name="a", time="08:30", action="sleep")])
        got = scheduler.load(ok + [{"name": "mala", "time": "xx", "action": "wake"}, {"basura": 1}])
        self.assertEqual([g.name for g in got], ["a"])

    def test_objetivos(self):
        devs = [Device(name="a", host="1", group="Planta 1"), Device(name="b", host="2", group="Planta 2")]
        self.assertEqual(len(scheduler.resolve_targets(scheduler.Schedule(name="n", time="07:00", action="wake"), devs)), 2)
        g = scheduler.Schedule(name="n", time="07:00", action="wake", targets="group:planta 1")
        self.assertEqual([d.name for d in scheduler.resolve_targets(g, devs)], ["a"])
        i = scheduler.Schedule(name="n", time="07:00", action="wake", targets=f"ids:{devs[1].id}")
        self.assertEqual([d.name for d in scheduler.resolve_targets(i, devs)], ["b"])

    def test_avisos_de_caida(self):
        t = scheduler.AlertTracker(threshold=3)
        self.assertIsNone(t.update("x", "unreachable"))            # nunca estuvo en línea: no avisa
        self.assertIsNone(t.update("x", "device"))
        self.assertIsNone(t.update("x", "unreachable"))
        self.assertIsNone(t.update("x", "unreachable"))
        self.assertEqual(t.update("x", "unreachable"), "down")      # 3 sondeos seguidos
        self.assertIsNone(t.update("x", "unreachable"))             # solo avisa una vez
        self.assertEqual(t.update("x", "device"), "up")             # recuperado
        self.assertIsNone(t.update("x", "device"))
        t.update("y", "device"); t.update("y", "unreachable"); t.update("y", "device")  # fallo puntual
        self.assertIsNone(t.update("y", "unreachable"))             # el contador se reinició

    def test_webhook_solo_http(self):
        for url in ("file:///etc/passwd", "ftp://x", "javascript:1", "x"):
            with self.assertRaises(ValueError):
                scheduler.post_webhook(url, "hola")


class TestInventory(unittest.TestCase):
    def test_fila_sin_conexion_y_con_conexion(self):
        d = Device(name="Memor", host="S1", transport="usb", group="Alm", kiosk_url="http://x")
        a = FakeAdb(shell_map={"ro.product.manufacturer": Result(0, "Datalogic", ""),
                               "getprop ro.product.model": Result(0, "Memor 11", ""),
                               "ip -o -4 addr": Result(0, "31: wlan0    inet 192.168.60.24/24 brd x", ""),
                               "df -h /data": Result(0, "/dev/x 50G 10G 38G 21% /data", ""),
                               "pm list packages -3": Result(0, "package:com.aza.scanner\npackage:es.tlsi.mobile", "")})
        off = inventory.collect(a, d, "unreachable")
        self.assertEqual((off["Estado"], off["Modelo"], off["Conexión"]), ("Apagado / desconectado", "", "USB"))
        on = inventory.collect(a, d, "device")
        self.assertEqual((on["Estado"], on["Nº apps de usuario"], on["Almacenamiento libre"], on["IP"]),
                         ("En línea", "2", "38G", "192.168.60.24"))

    def test_csv_excel_y_formulas(self):
        rows = [{c: "" for c in inventory.COLUMNS} | {"Nombre": "=HYPERLINK(\"http://malo\")", "Modelo": "Memor; 11 ñ"}]
        with tempfile.TemporaryDirectory() as d:
            p = inventory.to_csv(rows, Path(d, "inv.csv"))
            raw = p.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))                      # BOM: Excel abre bien los acentos
            data = list(csv.reader(p.read_text("utf-8-sig").splitlines(), delimiter=";"))
            self.assertEqual(data[0], inventory.COLUMNS)
            self.assertTrue(data[1][0].startswith("'="))                          # sin fórmulas inyectadas


class TestWifiDebug(unittest.TestCase):
    STATUS = "@@v\n{sdk}\n@@w\n{w}\n@@p\n{p}\n@@t\n{t}"

    def adb(self, sdk=33, w="0", p="", t="null"):
        a = FakeAdb(shell_map={"echo @@v": Result(0, self.STATUS.format(sdk=sdk, w=w, p=p, t=t), ""),
                               "echo ok": Result(0, "ok", ""),
                               "sys.boot_completed": Result(0, "1", ""),
                               "ip -o -4 addr": Result(0, "31: wlan0    inet 192.168.1.5/24 brd x", ""),
                               "settings get global adb_wifi_enabled": Result(0, "1", ""),
                               "settings get global adb_allowed_connection_time": Result(0, "0", "")})
        a.RESTART_SETTLE = 0
        a.FINAL_CHECK_DELAY = 0
        return a

    def test_estado(self):
        self.assertEqual(self.adb(w="1", p="5555", t="0").wifi_debug_status("s"),
                         {"sdk": 33, "wireless": True, "tcp_port": 5555, "no_expiry": True})
        self.assertEqual(self.adb().wifi_debug_status("s"),
                         {"sdk": 33, "wireless": False, "tcp_port": 0, "no_expiry": False})

    def test_activar_android_11_mas_con_tcpip_el_ultimo(self):
        a = self.adb(sdk=33, w="1")   # el sistema mantiene la depuración inalámbrica encendida
        msgs = a.enable_wifi_debug("s")
        cmds = [c for k, c in a.log if k == "shell" and "settings put" in c]
        self.assertEqual(cmds, ["settings put global adb_wifi_enabled 1",
                                "settings put global adb_allowed_connection_time 0"])
        runs = [c for k, c in a.log if k == "run"]
        self.assertEqual(runs[0], ("tcpip", "5555"))              # tcpip reinicia adbd: va al final
        self.assertEqual(runs[1], ("wait-for-device",))
        self.assertIn(("shell", "echo ok"), a.log)                # y espera a que el shell responda
        self.assertEqual(len(msgs), 3)

    def test_si_el_sistema_aun_arranca_reintenta_y_no_da_por_hecho(self):
        """Regresión del reinicio real: tras arrancar, `settings` aún no existe y el put falla."""
        a = self.adb(sdk=33, w="1")
        fallos = {"n": 0}
        original = a.shell

        def shell(serial, command, timeout=20):
            if command.startswith("settings put global adb_wifi_enabled") and fallos["n"] < 2:
                fallos["n"] += 1
                a.log.append(("shell", command))
                return Result(255, "", "cmd: Can't find service: settings")
            return original(serial, command, timeout)

        a.shell = shell
        import time as _t
        real_sleep, _t.sleep = _t.sleep, lambda s: None     # sin esperas reales en la prueba
        try:
            msgs = a.enable_wifi_debug("s")
        finally:
            _t.sleep = real_sleep
        self.assertEqual(fallos["n"], 2)
        self.assertEqual(sum(1 for k, c in a.log if c == "settings put global adb_wifi_enabled 1"), 3)
        self.assertIn("Depuración inalámbrica activada", msgs)

    def test_si_nunca_responde_lo_dice(self):
        a = self.adb(sdk=33)
        a.shell_map["settings get global adb_wifi_enabled"] = Result(0, "0", "")    # no se aplica nunca
        import time as _t
        real_sleep, _t.sleep = _t.sleep, lambda s: None
        try:
            msgs = a.enable_wifi_debug("s")
        finally:
            _t.sleep = real_sleep
        self.assertIn("Depuración inalámbrica: no se pudo activar", msgs)

    def test_espera_al_wifi_antes_de_activar_la_depuracion_inalambrica(self):
        """Regresión del reinicio real: activarla sin Wi-Fi hace que Android la apague sola."""
        a = self.adb(sdk=33)
        ips = iter(["", "", "31: wlan0    inet 192.168.1.5/24 brd x"])
        original = a.shell

        def shell(serial, command, timeout=20):
            if "ip -o -4 addr" in command:
                a.log.append(("shell", command))
                return Result(0, next(ips, "31: wlan0    inet 192.168.1.5/24"), "")
            return original(serial, command, timeout)

        a.shell = shell
        import time as _t
        real_sleep, _t.sleep = _t.sleep, lambda s: None
        try:
            a.enable_wifi_debug("s")
        finally:
            _t.sleep = real_sleep
        order = [c for k, c in a.log if k == "shell" and ("ip -o -4" in c or "adb_wifi_enabled 1" in c)]
        self.assertEqual(sum(1 for c in order if "ip -o -4" in c), 3)           # esperó hasta tener IP
        self.assertTrue("ip -o -4" in order[2] and "adb_wifi_enabled 1" in order[3])  # y solo entonces la activó

    def test_reintenta_si_el_sistema_la_apaga_sola(self):
        a = self.adb(sdk=33)
        estados = iter(["1", "0", "1", "1"])
        original = a.shell

        def shell(serial, command, timeout=20):
            if command.startswith("echo @@v"):  # wifi_debug_status: la 1ª lectura (sdk) y la final
                a.log.append(("shell", command))
                return Result(0, f"@@v\n33\n@@w\n{next(estados, '1')}\n@@p\n5555\n@@t\n0", "")
            return original(serial, command, timeout)

        a.shell = shell
        import time as _t
        real_sleep, _t.sleep = _t.sleep, lambda s: None
        try:
            msgs = a.enable_wifi_debug("s")
        finally:
            _t.sleep = real_sleep
        self.assertIn("Depuración inalámbrica reactivada (el sistema la había apagado)", msgs)

    def test_android_antiguo_solo_adb_clasico(self):
        a = self.adb(sdk=28)
        msgs = a.enable_wifi_debug("s")
        self.assertFalse([c for k, c in a.log if k == "shell" and "settings put" in c])
        self.assertIn(("run", ("tcpip", "5555")), a.log)
        self.assertTrue(any("anterior a 11" in m for m in msgs))

    def test_desactivar(self):
        a = self.adb(sdk=33)
        a.disable_wifi_debug("s")
        self.assertIn(("shell", "settings put global adb_wifi_enabled 0"), a.log)
        self.assertIn(("run", ("usb",)), a.log)


class TestKeeper(unittest.TestCase):
    def adb(self, sdk=33, installed=True, granted=True, install_ok=True, exempt=True):
        a = FakeAdb(
            shell_map={"echo @@v": Result(0, f"@@v\n{sdk}\n@@w\n0\n@@p\n\n@@t\nnull", ""),
                       "cmd deviceidle whitelist":
                           Result(0, "user,com.atvmaster.adbkeeper,10177" if exempt else "", ""),
                       "pm list packages com.atvmaster.adbkeeper":
                           Result(0, "package:com.atvmaster.adbkeeper" if installed else "", ""),
                       "dumpsys package com.atvmaster.adbkeeper":
                           Result(0, f"android.permission.WRITE_SECURE_SETTINGS: granted={'true' if granted else 'false'}", "")},
            run_map={("install", "-r"): Result(0 if install_ok else 1, "Success" if install_ok else "Failure [x]", "")})
        a.KEEPER_FLUSH_DELAY = 0
        return a

    def test_repara_el_permiso_perdido(self):
        a = self.adb(installed=True, granted=False)
        self.assertTrue(a.ensure_keeper_permission("s"))
        self.assertTrue(any(c.startswith("pm grant com.atvmaster.adbkeeper") for k, c in a.log if k == "shell"))
        b = self.adb(installed=True, granted=True)
        self.assertFalse(b.ensure_keeper_permission("s"))
        self.assertFalse(any("pm grant" in c for k, c in b.log if k == "shell"))
        c = self.adb(installed=False)
        self.assertFalse(c.ensure_keeper_permission("s"))

    def test_excluye_del_ahorro_de_bateria(self):
        # Sin la exclusión Android retiene el aviso de arranque (standby bucket «nunca usada»).
        a = self.adb()
        msgs = a.install_keeper("s", "K.apk")
        self.assertIn(("shell", "cmd deviceidle whitelist +com.atvmaster.adbkeeper"), a.log)
        self.assertTrue(any("ahorro de batería" in m for m in msgs))
        b = self.adb(installed=True, granted=True, exempt=False)   # versión anterior sin exclusión
        self.assertTrue(b.ensure_keeper_permission("s"))
        self.assertIn(("shell", "cmd deviceidle whitelist +com.atvmaster.adbkeeper"), b.log)
        self.assertFalse([1 for k, c in b.log if k == "shell" and "pm grant" in c])

    def test_espera_a_que_se_guarde_el_permiso(self):
        a = self.adb()
        msgs = a.install_keeper("s", "K.apk")
        self.assertIn(("shell", "sync"), a.log)
        self.assertIn("Permiso guardado", msgs)

    def test_flujo_completo(self):
        a = self.adb()
        msgs = a.install_keeper("s", "K.apk")
        self.assertEqual(msgs[0], "ADB Keeper instalado")
        cmds = [c for k, c in a.log if k == "shell"]
        self.assertTrue(any(c.startswith("pm grant com.atvmaster.adbkeeper android.permission.WRITE_SECURE_SETTINGS") for c in cmds))
        self.assertTrue(any("am start -n com.atvmaster.adbkeeper/.MainActivity --ez silent true" in c for c in cmds))

    def test_android_anterior_a_11_no_instala(self):
        a = self.adb(sdk=28)
        self.assertIn("anterior a 11", a.install_keeper("s", "K.apk")[0])
        self.assertFalse([1 for k, c in a.log if k == "run" and c[0] == "install"])

    def test_si_la_instalacion_falla_no_sigue(self):
        a = self.adb(install_ok=False)
        msgs = a.install_keeper("s", "K.apk")
        self.assertEqual(len(msgs), 1)
        self.assertFalse([1 for k, c in a.log if k == "shell" and "pm grant" in c])

    def test_sin_permiso_no_lo_abre(self):
        a = self.adb(granted=False)
        msgs = a.install_keeper("s", "K.apk")
        self.assertTrue(any("No se pudo conceder" in m for m in msgs))
        self.assertFalse([1 for k, c in a.log if k == "shell" and "am start" in c])

    def test_estado(self):
        self.assertEqual(self.adb().keeper_status("s"), {"installed": True, "granted": True})
        self.assertEqual(self.adb(installed=False).keeper_status("s"), {"installed": False, "granted": False})


class TestImei(unittest.TestCase):
    # Salida real de `service call iphonesubinfo` en un Datalogic Memor 11 (Android 13).
    PARCEL = ("Result: Parcel(\n"
              "  0x00000000: 00000000 0000000f 00350033 00340032 '........3.5.2.4.'\n"
              "  0x00000010: 00300036 00310038 00330030 00380037 '6.0.8.1.0.3.7.8.'\n"
              "  0x00000020: 00330033 00000031                   '3.3.1...')")

    def test_decodifica_el_parcel_real(self):
        from atvmaster.adb import parse_parcel_string
        self.assertEqual(parse_parcel_string(self.PARCEL), "352460810378331")

    def test_luhn(self):
        from atvmaster.adb import luhn_ok
        self.assertTrue(luhn_ok("490154203237518"))        # IMEI de ejemplo válido
        self.assertFalse(luhn_ok("490154203237519"))       # un dígito mal
        self.assertFalse(luhn_ok("12345"))
        self.assertFalse(luhn_ok("49015420323751a"))

    def test_respuestas_de_error_no_dan_imei(self):
        from atvmaster.adb import parse_parcel_string
        for t in ("Result: Parcel(fffffffc ffffffff 00000000  '............')", "Result: Parcel(00000000 ffffffff)", "",
                  "Error: permission denied"):
            self.assertEqual(parse_parcel_string(t), "", t)

    def test_imei_valida_y_no_repite(self):
        a = FakeAdb(shell_map={"iphonesubinfo": Result(0, self.PARCEL, "")})   # todas las variantes dan el mismo
        self.assertEqual(a.imei("s"), ["352460810378331"])                       # y sale una sola vez

    def test_basura_con_longitud_valida_se_descarta(self):
        a = FakeAdb(shell_map={"iphonesubinfo": Result(0, self.PARCEL.replace("00330033 00000031", "00330033 00000032"), "")})
        self.assertEqual(a.imei("s"), [])                  # el dígito de control no cuadra

    def test_solo_con_telefonia(self):
        self.assertTrue(FakeAdb(shell_map={"has-feature": Result(0, "true", "")}).has_telephony("s"))
        self.assertFalse(FakeAdb(shell_map={"has-feature": Result(0, "false", "")}).has_telephony("s"))


class TestMisc(unittest.TestCase):
    def test_wol_y_url(self):
        self.assertEqual(wol.normalize_mac("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")
        with self.assertRaises(ValueError):
            wol.normalize_mac("zz")
        self.assertEqual(kiosk.normalize_url("srv/x"), "http://srv/x")
        for bad in ("", "ftp://x", "http://a b"):
            with self.assertRaises(ValueError):
                kiosk.normalize_url(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
