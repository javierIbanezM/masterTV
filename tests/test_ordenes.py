"""Pruebas de las órdenes remotas firmadas (ver atvmaster/ordenes.py)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atvmaster import ordenes  # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    HAY_CRIPTO = True
except ImportError:  # pragma: no cover
    HAY_CRIPTO = False


@unittest.skipUnless(HAY_CRIPTO, "falta la librería cryptography")
class TestOrdenes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        base = Path(cls.dir.name)
        clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.priv, cls.pub, cls.otra_pub = base / "priv.pem", base / "pub.pem", base / "otra.pem"
        cls.priv.write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
        cls.pub.write_bytes(clave.public_key().public_bytes(serialization.Encoding.PEM,
                                                            serialization.PublicFormat.SubjectPublicKeyInfo))
        cls.otra_pub.write_bytes(otra.public_key().public_bytes(serialization.Encoding.PEM,
                                                                serialization.PublicFormat.SubjectPublicKeyInfo))

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_firma_y_verificacion(self):
        t = ordenes.fichero_firmado("S21L04768", [ordenes.orden_desinstalar("es.tlsi.mobile")], self.priv)
        self.assertTrue(ordenes.verificar(t, self.pub))
        self.assertFalse(ordenes.verificar(t, self.otra_pub), "otra clave pública no debe validar")

    def test_si_se_toca_el_payload_la_firma_falla(self):
        f = json.loads(ordenes.fichero_firmado("S21L04768", [ordenes.orden_desinstalar("es.tlsi.mobile")], self.priv))
        f["payload"] = f["payload"].replace("es.tlsi.mobile", "com.aza.scanner")
        self.assertFalse(ordenes.verificar(json.dumps(f), self.pub))

    def test_payload_con_vigencia_y_destino(self):
        p = json.loads(ordenes.construir_payload("*", [ordenes.orden_cerrar("com.aza.scanner")], horas=2, ahora=1000))
        self.assertEqual((p["emitido"], p["caduca"], p["destino"]), (1000, 1000 + 7200, "*"))

    def test_instalar_exige_sha256_y_url_http(self):
        h = "a" * 64
        o = ordenes.orden_instalar("http://srv/a.apk", h.upper(), "com.aza.scanner")
        self.assertEqual(o["sha256"], h)
        for url, sha in (("ftp://srv/a.apk", h), ("http://srv/a.apk", "corto"), ("file:///a.apk", h)):
            with self.assertRaises(ordenes.OrdenError):
                ordenes.orden_instalar(url, sha)

    def test_paquetes_protegidos_y_nombres_invalidos(self):
        for p in ("com.android.settings", "com.datalogic.scan2deploy", "com.mediatek.camera", "android",
                  "com.azalogistics.pda", "x; rm -rf /", "sinpunto"):
            with self.assertRaises(ordenes.OrdenError, msg=p):
                ordenes.orden_desinstalar(p)

    def test_el_launcher_solo_se_actualiza_con_su_orden(self):
        h = "b" * 64
        self.assertEqual(ordenes.orden_actualizar_launcher("http://srv/l.apk", h)["tipo"], "actualizar_launcher")
        with self.assertRaises(ordenes.OrdenError):
            ordenes.orden_instalar("http://srv/l.apk", h, "com.azalogistics.pda")

    def test_ids_repetidos_y_destinos_invalidos(self):
        a = ordenes.orden_cerrar("com.aza.scanner", id="x1")
        with self.assertRaises(ordenes.OrdenError):
            ordenes.construir_payload("S21L04768", [a, dict(a)])
        for d in ("", "../x", "a b"):
            with self.assertRaises(ordenes.OrdenError):
                ordenes.construir_payload(d, [a])
        with self.assertRaises(ordenes.OrdenError):
            ordenes.construir_payload("S21L04768", [])

    def test_publicar_es_atomico_y_valida_el_nombre(self):
        with tempfile.TemporaryDirectory() as d:
            r = ordenes.publicar(d, "S21L04768", "{}")
            self.assertEqual(r, Path(d) / "ordenes" / "S21L04768.json")
            self.assertEqual(list((Path(d) / "ordenes").glob("*.tmp")), [])
            with self.assertRaises(ordenes.OrdenError):
                ordenes.publicar(d, "../../x", "{}")


if __name__ == "__main__":
    unittest.main()
