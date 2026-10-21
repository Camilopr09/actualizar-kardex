import http.client
import json
import time

import pytest

import demo
import flujo
from servidor import Servidor


class Cliente:
    def __init__(self, srv):
        self.srv = srv

    def pedir(self, metodo, ruta, cuerpo=None, token=True, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.puerto, timeout=10)
        cab = {"Host": host or f"127.0.0.1:{self.srv.puerto}"}
        if token:
            cab["X-Token"] = self.srv.token if token is True else token
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode("utf-8")
            cab["Content-Type"] = "application/json"
        c.request(metodo, ruta, datos, cab)
        r = c.getresponse()
        crudo = r.read()
        c.close()
        try:
            return r.status, json.loads(crudo)
        except ValueError:
            return r.status, crudo

    def get(self, ruta, **kw):
        return self.pedir("GET", ruta, **kw)

    def post(self, ruta, cuerpo=None, **kw):
        return self.pedir("POST", ruta, {} if cuerpo is None else cuerpo, **kw)

    def estado(self):
        return self.get("/api/estado")[1]

    def esperar_fin(self, n_previo, tope=20):
        t = time.time()
        while time.time() - t < tope:
            e = self.estado()
            if e["ultima"] and e["ultima"]["n"] > n_previo and not e["tarea"]:
                return e
            time.sleep(0.05)
        raise AssertionError("la tarea no terminó")


@pytest.fixture
def srv(monkeypatch):
    monkeypatch.setattr(demo, "PAUSA_SESION", 0.2)
    monkeypatch.setattr(demo, "PAUSA_PACIENTE", 0.005)
    monkeypatch.setattr(demo, "PAUSA_ESCRIBIR", 0.05)
    s = Servidor(demo=True)
    s.iniciar()
    yield s
    s.detener()


@pytest.fixture
def c(srv):
    return Cliente(srv)


def test_seguridad(c, srv):
    assert c.get("/api/estado", token=False)[0] == 403
    assert c.get("/api/estado", token="malo")[0] == 403
    assert c.post("/api/analizar", token=False)[0] == 403
    assert c.get("/api/estado", host="evil.example.com")[0] == 403
    assert c.get("/", host=f"evil.example.com:{srv.puerto}", token=False)[0] == 403
    assert c.get("/api/estado", host=f"localhost:{srv.puerto}")[0] == 200
    # la página y los estáticos no piden token; sin ui/index.html sale el marcador
    st, cuerpo = c.get("/", token=False)
    assert st == 200 and b"<html" in cuerpo
    assert c.get("/../servidor.py", token=False)[0] in (403, 404)
    assert c.get("/%2e%2e/servidor.py", token=False)[0] == 404
    assert c.post("/api/noexiste")[0] == 404


def test_estado_inicial(c):
    e = c.estado()
    assert e["version"] == "2.0.0" and e["demo"] is True
    assert set(e["config"]) >= {"url_kardex", "url_agenda", "especialistas", "navegador", "entregas"}
    assert len(e["config"]["entregas"]) == 11 and all(set(d) == {"nombre", "url"} for d in e["config"]["entregas"])
    assert e["config"]["entregas"][0]["nombre"] == "PISO 3 GINECO"
    assert set(e["navegadores"]) == {"chrome", "brave"}
    assert e["sesion_guardada"] is False and e["credenciales"] is True
    assert e["sesion_pasos"] == {"hospital": False, "google": False}
    assert e["tarea"] is None and e["ultima"] is None and e["resultado"] is None
    assert e["escritura"] is None and e["error"] is None
    assert e["progreso"] == {"actual": 0, "total": 0, "paciente": ""}


def test_config(c):
    st, r = c.post("/api/config", {"navegador": "brave", "especialistas": [" DAZA ", "X"], "url_kardex": "http://k/"})
    assert st == 200 and r["ok"] and r["config"]["navegador"] == "brave"
    assert r["config"]["especialistas"] == ["DAZA", "X"]
    assert c.estado()["config"]["url_kardex"] == "http://k/"
    assert flujo.cargar_config()["navegador"] == "brave"          # quedó en disco
    for malo in ({"navegador": "edge"}, {"especialistas": "DAZA"}, {"especialistas": ["", "A"]},
                 {"url_kardex": 5}, {"url_kardex": "--renderer-cmd-prefix=x"}, {"url_agenda": ""}):
        st, r = c.post("/api/config", malo)
        assert st == 400 and r["ok"] is False
    assert c.estado()["config"]["navegador"] == "brave"


DOC = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-aBcDe/edit"


def test_config_entregas(c):
    nuevas = [{"nombre": "  PISO 6 ", "url": DOC}, {"nombre": "URGENCIAS CARRERA 47", "url": DOC + "?tab=t.0"}]
    st, r = c.post("/api/config", {"entregas": nuevas})
    assert st == 200 and r["ok"]
    assert r["config"]["entregas"] == [{"nombre": "PISO 6", "url": DOC}, {"nombre": "URGENCIAS CARRERA 47", "url": DOC + "?tab=t.0"}]
    assert c.estado()["config"]["entregas"] == r["config"]["entregas"]
    assert flujo.cargar_config()["entregas"] == r["config"]["entregas"]          # quedó en disco
    assert c.post("/api/config", {"entregas": []})[0] == 200                     # vacía: no se lee ninguna
    assert c.estado()["config"]["entregas"] == []
    # un cambio parcial de otra cosa no toca las entregas
    c.post("/api/config", {"entregas": nuevas})
    c.post("/api/config", {"navegador": "brave"})
    assert len(c.estado()["config"]["entregas"]) == 2
    bien = {"nombre": "A", "url": DOC}
    for malo in ("PISO 6", {"nombre": "A"}, [5], [{"nombre": "A", "url": 5}], [{"nombre": 5, "url": DOC}],
                 [{"nombre": "", "url": DOC}], [{"nombre": "   ", "url": DOC}], [{"nombre": "A" * 81, "url": DOC}],
                 [{"nombre": "A", "url": "https://evil.example.com/document/d/abc/edit"}],
                 [{"nombre": "A", "url": "https://docs.google.com.evil.example.com/document/d/abc/edit"}],
                 [{"nombre": "A", "url": "https://docs.google.com/spreadsheets/d/abc/edit"}],
                 [{"nombre": "A", "url": "https://docs.google.com/document/d//edit"}],
                 [{"nombre": "A", "url": "docs.google.com/document/d/abc/edit"}],
                 [{"nombre": "A", "url": "--renderer-cmd-prefix=x"}], [bien] * 31):
        st, r = c.post("/api/config", {"entregas": malo})
        assert st == 400 and r["ok"] is False, malo
    assert len(c.estado()["config"]["entregas"]) == 2                            # lo inválido no cambió nada
    st, r = c.post("/api/config", {"entregas": [{"nombre": "A" * 80, "url": DOC}] * 30})   # los límites exactos sí
    assert st == 200 and len(r["config"]["entregas"]) == 30


def test_json_invalido(c, srv):
    k = http.client.HTTPConnection("127.0.0.1", srv.puerto, timeout=5)
    k.request("POST", "/api/config", b"{no", {"X-Token": srv.token, "Host": f"127.0.0.1:{srv.puerto}"})
    assert k.getresponse().status == 400


def test_flujo_completo(c):
    n = 0
    assert c.post("/api/sesion")[1] == {"ok": True}
    e = c.esperar_fin(n)
    n = e["ultima"]["n"]
    assert e["ultima"] == {"n": 1, "tipo": "sesion", "fin": "ok"} and e["sesion_guardada"] is True
    assert e["sesion_pasos"] == {"hospital": True, "google": True}

    assert c.post("/api/analizar")[1] == {"ok": True}
    e = c.esperar_fin(n)
    n = e["ultima"]["n"]
    assert e["ultima"]["tipo"] == "analizar" and e["ultima"]["fin"] == "ok" and e["error"] is None
    r = e["resultado"]
    # 29 filas en el kardex; en el sistema faltan 2 (altas) y se suman 3 pacientes de las entregas que no están en el kardex
    assert len(r["fecha"]) == 16 and len(r["sistema"]) == 30 and len(r["kardex"]) == 29
    assert len({k["servicio"] for k in r["kardex"]}) == 13
    assert {a["tipo"] for a in r["acciones"]} == {"ACTUALIZAR", "AGREGAR", "MOVER", "RETIRAR", "REVISAR"}
    assert set(r["acciones"][0]) == {"id", "tipo", "paciente", "servicio", "habitacion", "campo", "detalle",
                                     "actual", "nuevo", "automatica", "marcada", "id_sistema", "id_kardex",
                                     "destino", "insertar", "fila_nueva", "habitacion_nueva"}
    ids_s, ids_k = {x["id"] for x in r["sistema"]}, {x["id"] for x in r["kardex"]}
    for a in r["acciones"]:
        if a["tipo"] == "RETIRAR":
            assert a["id_sistema"] is None and a["id_kardex"] in ids_k
        elif a["tipo"] == "AGREGAR":
            assert a["id_kardex"] is None and a["id_sistema"] in ids_s
        elif a["paciente"] == "UCI 7":              # documento de entregas que no se pudo leer: sin paciente
            assert a["tipo"] == "REVISAR" and a["id_sistema"] is None and a["id_kardex"] is None
        else:
            assert a["id_sistema"] in ids_s and a["id_kardex"] in ids_k
    assert set(r["sistema"][0]) == {"id", "nombre", "habitacion", "medico", "fecha", "dx", "id_kardex"}
    assert set(r["kardex"][0]) == {"id", "servicio", "nombre", "habitacion", "dx", "id_sistema"}
    assert e["progreso"]["total"] == 32 and e["progreso"]["actual"] == 32       # 29 del kardex + 3 de las entregas
    assert any("Análisis terminado" in linea for linea in e["registro"])
    assert all(linea[2] == ":" for linea in e["registro"])

    # lo nuevo, serializado para la interfaz
    agregar = [a for a in r["acciones"] if a["tipo"] == "AGREGAR"]
    con_destino = [a for a in agregar if a["automatica"]]
    assert len(agregar) == 3 and len(con_destino) == 2
    a = next(x for x in con_destino if x["destino"] == "PISO 6")
    assert [c_ for c_, _ in a["fila_nueva"]] == ["DATOS", "DX", "EVOLUCIÓN", "TRATAMIENTO", "IMÁGENES / NOTAS"]
    assert a["fila_nueva"][0][1].splitlines() == ["611", a["paciente"], "47 AÑOS", "CC 1015000111"]
    assert a["habitacion_nueva"] == "611" and a["marcada"] and a["servicio"] == "PISO 6"
    manual = next(x for x in agregar if not x["automatica"])
    assert manual["destino"] == "" and not manual["marcada"] and "agrégalo a mano" in manual["detalle"]
    assert manual["fila_nueva"] and manual["fila_nueva"][0][0] == "DATOS"
    mover = [a for a in r["acciones"] if a["tipo"] == "MOVER"]
    assert sorted((a["servicio"], a["destino"], a["habitacion_nueva"]) for a in mover) == [
        ("PISO 4A", "PISO 4C", "405"), ("PISO 6", "PISO 5", "512")]
    assert all(a["automatica"] and a["marcada"] and a["fila_nueva"] == [] for a in mover)
    hab = [a for a in r["acciones"] if a["tipo"] == "ACTUALIZAR" and a["campo"] == "HABITACIÓN"]
    assert [(a["actual"], a["nuevo"], a["habitacion_nueva"]) for a in hab] == [("302", "306", "306")]
    imagenes = [a for a in r["acciones"] if a["campo"] == "IMÁGENES / NOTAS"]
    assert len(imagenes) == 2 and all(a["insertar"] and a["insertar"] in a["nuevo"] for a in imagenes)
    assert all(a["insertar"] == "" for a in r["acciones"] if a["campo"] != "IMÁGENES / NOTAS")
    doc = next(a for a in r["acciones"] if a["paciente"] == "UCI 7")
    assert doc["detalle"].startswith("No pude leer el documento de entregas UCI 7:") and not doc["automatica"]

    # se escriben las automáticas marcadas de ACTUALIZAR, AGREGAR y MOVER; las manuales se ignoran
    auto = [a for a in r["acciones"] if a["automatica"]]
    otros = [a for a in r["acciones"] if not a["automatica"]]
    assert {a["tipo"] for a in auto} == {"ACTUALIZAR", "AGREGAR", "MOVER"} and len(auto) == 19
    st, _ = c.post("/api/escribir", {"ids": [x["id"] for x in auto] + [otros[0]["id"]]})      # el no automático se ignora
    assert st == 200
    e = c.esperar_fin(n)
    esc = e["escritura"]
    assert e["ultima"]["tipo"] == "escribir" and len(esc["escritas"]) == 18 and len(esc["omitidas"]) == 1
    assert esc["omitidas"][0]["motivo"].startswith("La fila cambió")
    assert set(esc["escritas"][0]) == {"id", "paciente", "campo", "tipo", "destino"}
    assert set(esc["omitidas"][0]) == {"id", "paciente", "campo", "tipo", "destino", "motivo"}
    assert {(x["tipo"], x["destino"]) for x in esc["escritas"] if x["tipo"] != "ACTUALIZAR"} == {
        ("AGREGAR", "PISO 6"), ("AGREGAR", "URGENCIAS 47"), ("MOVER", "PISO 5"), ("MOVER", "PISO 4C")}
    quedan = {a["id"] for a in e["resultado"]["acciones"]}
    assert not quedan & {x["id"] for x in esc["escritas"]}
    assert esc["omitidas"][0]["id"] in quedan
    assert {x["id"] for x in otros} <= quedan

    st, r = c.post("/api/escribir", {"ids": [otros[0]["id"]]})
    assert st == 400 and r["ok"] is False
    st, r = c.post("/api/escribir", {"ids": [manual["id"]]})        # AGREGAR sin tabla destino: a mano
    assert st == 400 and r["ok"] is False
    assert c.post("/api/escribir", {"ids": "a1"})[0] == 400


def test_escribir_acepta_agregar_y_mover(c):
    c.post("/api/analizar")
    e = c.esperar_fin(0)
    acciones = e["resultado"]["acciones"]
    ids = [a["id"] for a in acciones if a["tipo"] in ("AGREGAR", "MOVER") and a["automatica"]]
    assert len(ids) == 4
    assert c.post("/api/escribir", {"ids": ids})[0] == 200
    e = c.esperar_fin(1)
    assert [x["tipo"] for x in e["escritura"]["escritas"]] == ["MOVER", "MOVER", "AGREGAR", "AGREGAR"]
    assert not e["escritura"]["omitidas"]       # solo se «omite» una ACTUALIZAR cuando hay varias
    assert not {a["id"] for a in e["resultado"]["acciones"]} & set(ids)


def test_409_con_tarea_en_curso(c, monkeypatch):
    monkeypatch.setattr(demo, "PAUSA_SESION", 0.6)
    assert c.post("/api/sesion")[0] == 200
    assert c.estado()["tarea"] == {"tipo": "sesion"}
    for ruta in ("/api/analizar", "/api/sesion"):
        st, r = c.post(ruta)
        assert st == 409 and r == {"ok": False, "mensaje": "Ya hay una tarea en curso"}
    assert c.post("/api/escribir", {"ids": ["a0"]})[0] == 409
    c.esperar_fin(0)
    assert c.post("/api/analizar")[0] == 200
    c.post("/api/cancelar")
    c.esperar_fin(1)


def test_cancelar_analisis(c, monkeypatch):
    monkeypatch.setattr(demo, "PAUSA_PACIENTE", 0.05)
    c.post("/api/analizar")
    t = time.time()
    while c.estado()["progreso"]["actual"] < 2 and time.time() - t < 10:
        time.sleep(0.02)
    assert c.post("/api/cancelar")[1] == {"ok": True}
    e = c.esperar_fin(0)
    assert e["ultima"] == {"n": 1, "tipo": "analizar", "fin": "cancelado"}
    assert e["resultado"] is None and e["error"] is None
    # y se puede volver a analizar
    c.post("/api/analizar")
    assert c.esperar_fin(1)["resultado"] is not None


def test_error_de_tarea(c, srv, monkeypatch):
    from errores import ErrorApp

    def falla(nav, cfg, log, progreso, cancelado):
        raise ErrorApp("sesion", "Hospital Office pide iniciar sesión.")
    monkeypatch.setattr(srv.backend, "analizar", falla)
    c.post("/api/analizar")
    e = c.esperar_fin(0)
    assert e["ultima"]["fin"] == "error"
    assert e["error"] == {"codigo": "sesion", "mensaje": "Hospital Office pide iniciar sesión."}
    monkeypatch.setattr(srv.backend, "analizar", lambda *a: 1 / 0)
    c.post("/api/analizar")
    e = c.esperar_fin(1)
    assert e["error"]["codigo"] == "otro"


def test_credenciales(c, datos_temporales):
    cred = datos_temporales / "credentials.json"
    tok = datos_temporales / "token.json"
    tok.write_text("{}")
    bueno = json.dumps({"installed": {"client_id": "x", "client_secret": "y"}})
    assert c.post("/api/credenciales", {"contenido": bueno})[0] == 200
    assert json.loads(cred.read_text())["installed"]["client_id"] == "x"
    assert not tok.exists()                                    # token viejo descartado
    assert c.post("/api/credenciales", {"contenido": json.dumps({"web": {"a": 1}})})[0] == 200
    for malo in ("no es json", "[]", json.dumps({"otra": {}}), json.dumps({"installed": "x"}), None, 5):
        st, r = c.post("/api/credenciales", {"contenido": malo})
        assert st == 400 and r["ok"] is False and r["codigo"] == "credenciales"
    assert json.loads(cred.read_text()).get("web")             # el inválido no pisó el válido
    tok.write_text("{}")
    assert c.post("/api/credenciales/quitar")[1] == {"ok": True}
    assert not cred.exists() and not tok.exists()
    assert c.post("/api/credenciales/quitar")[0] == 200        # idempotente


def test_hospital_guardar_y_quitar(c, srv):
    e = c.estado()
    assert e["hospital_guardado"] is False and e["hospital_usuario"] == ""
    for malo in ({}, {"usuario": "", "clave": "x"}, {"usuario": "u", "clave": ""}, {"usuario": "  ", "clave": "x"},
                 {"usuario": 5, "clave": "x"}):
        st, r = c.post("/api/hospital", malo)
        assert st == 400 and r["ok"] is False
    assert c.estado()["hospital_guardado"] is False
    assert c.post("/api/hospital", {"usuario": " medico.prueba ", "clave": "Clave-Muy-Secreta-77"}) == (200, {"ok": True})
    e = c.estado()
    assert e["hospital_guardado"] is True and e["hospital_usuario"] == "medico.prueba"
    assert "Clave-Muy-Secreta-77" not in json.dumps(e, ensure_ascii=False)      # ni en el registro ni en el estado
    assert c.post("/api/hospital/quitar")[1] == {"ok": True}
    e = c.estado()
    assert e["hospital_guardado"] is False and e["hospital_usuario"] == ""
    assert c.post("/api/hospital/quitar")[0] == 200


def test_hospital_en_modo_real_se_guarda_cifrado(datos_temporales, monkeypatch):
    s = Servidor(demo=False)
    s.iniciar()
    try:
        k = Cliente(s)
        assert k.post("/api/hospital", {"usuario": "medico.prueba", "clave": "Clave-Muy-Secreta-77"})[0] == 200
        crudo = (datos_temporales / "hospital.bin").read_bytes()
        assert b"Clave-Muy-Secreta-77" not in crudo
        assert flujo.hospital_credenciales() == {"usuario": "medico.prueba", "clave": "Clave-Muy-Secreta-77"}
        e = k.estado()
        assert e["hospital_guardado"] and "Clave-Muy-Secreta-77" not in json.dumps(e)
        assert not any("Clave-Muy-Secreta-77" in linea for linea in e["registro"])
        k.post("/api/hospital/quitar")
        assert not (datos_temporales / "hospital.bin").exists()
    finally:
        s.detener()


def test_escribir_sin_credenciales(c, srv, monkeypatch):
    monkeypatch.setattr(srv.backend, "credenciales_ok", lambda: False)
    st, r = c.post("/api/escribir", {"ids": ["a0"]})
    assert st == 400 and r["codigo"] == "credenciales" and r["ok"] is False


def test_abrir(c, srv):
    visto = []
    srv.demo = False
    srv.abrir_url = lambda url, pref: visto.append((url, pref))
    assert c.post("/api/abrir", {"que": "agenda"})[0] == 200
    assert visto == [(srv.cfg["url_agenda"], srv.cfg["navegador"])]
    assert c.post("/api/abrir", {"que": "otro"})[0] == 400


def test_salir(c, srv):
    assert c.post("/api/salir")[1] == {"ok": True}
    assert srv.salir.wait(3)


def test_inactividad(srv):
    assert not srv.inactivo(60)
    time.sleep(0.05)
    assert srv.inactivo(0.01)


def test_carpeta_ui_con_pyinstaller(tmp_path, monkeypatch):
    import sys
    import servidor
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "index.html").write_text("<title>empaquetada</title>", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert servidor.carpeta_ui() == tmp_path / "ui"
    s = Servidor(demo=True)
    s.iniciar()
    try:
        assert b"empaquetada" in Cliente(s).get("/", token=False)[1]
    finally:
        s.detener()


def test_sesion_terminar_corta_la_tarea(c, monkeypatch):
    monkeypatch.setattr(demo, "PAUSA_SESION", 60.0)
    assert c.post("/api/sesion")[1] == {"ok": True}
    assert c.post("/api/sesion/terminar")[1] == {"ok": True}
    e = c.esperar_fin(0)
    assert e["ultima"] == {"n": 1, "tipo": "sesion", "fin": "ok"} and e["sesion_guardada"] is True


def test_navegador_vivo_solo_en_modo_real(srv, datos_temporales):
    assert srv.nav is None                                   # demo: sin navegador real
    cerrado = []

    class NavFalso:
        def ejecutar(self, f, *a):
            return f(None, *a)

        def cerrar(self):
            cerrado.append(1)
    real = Servidor(demo=False, nav=NavFalso())
    real.iniciar()
    try:
        assert isinstance(real.nav, NavFalso)
    finally:
        real.detener()
    assert cerrado == [1]                                    # apagar la app cierra el navegador
    por_defecto = Servidor(demo=False)
    from navegador_vivo import NavegadorVivo
    assert isinstance(por_defecto.nav, NavegadorVivo) and not por_defecto.nav.hilo_vivo   # perezoso
    por_defecto.httpd.server_close()


def test_las_tareas_reciben_el_navegador_vivo(datos_temporales, monkeypatch):
    vistos = []

    class Backend(demo.Demo):
        def iniciar_sesion(self, nav, cfg, log, pasos, terminar):
            vistos.append(("sesion", nav))

        def analizar(self, nav, cfg, log, progreso, cancelado):
            vistos.append(("analizar", nav))
            raise ErrorApp("agenda", "x")
    from errores import ErrorApp
    nav = object()
    s = Servidor(demo=False, nav=type("N", (), {"cerrar": lambda self: None})())
    s.nav = nav
    s.backend = Backend()
    s.iniciar()
    try:
        k = Cliente(s)
        k.post("/api/sesion")
        k.esperar_fin(0)
        k.post("/api/analizar")
        k.esperar_fin(1)
    finally:
        s.nav = None
        s.detener()
    assert vistos == [("sesion", nav), ("analizar", nav)]
