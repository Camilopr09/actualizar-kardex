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
    assert set(e["config"]) >= {"url_kardex", "url_agenda", "especialistas", "navegador"}
    assert set(e["navegadores"]) == {"chrome", "brave"}
    assert e["sesion_guardada"] is False and e["credenciales"] is True
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

    assert c.post("/api/analizar")[1] == {"ok": True}
    e = c.esperar_fin(n)
    n = e["ultima"]["n"]
    assert e["ultima"]["tipo"] == "analizar" and e["ultima"]["fin"] == "ok" and e["error"] is None
    r = e["resultado"]
    assert len(r["fecha"]) == 16 and len(r["sistema"]) == 29 and len(r["kardex"]) == 29
    assert len({k["servicio"] for k in r["kardex"]}) == 13
    assert {a["tipo"] for a in r["acciones"]} == {"ACTUALIZAR", "AGREGAR", "RETIRAR", "REVISAR"}
    assert set(r["acciones"][0]) == {"id", "tipo", "paciente", "servicio", "habitacion", "campo", "detalle",
                                     "actual", "nuevo", "automatica", "marcada", "id_sistema", "id_kardex"}
    ids_s, ids_k = {x["id"] for x in r["sistema"]}, {x["id"] for x in r["kardex"]}
    for a in r["acciones"]:
        assert a["id_sistema"] in ids_s | {None} and a["id_kardex"] in ids_k | {None}
        assert (a["id_sistema"] is None) == (a["tipo"] == "RETIRAR")
        assert (a["id_kardex"] is None) == (a["tipo"] == "AGREGAR")
    assert set(r["sistema"][0]) == {"id", "nombre", "habitacion", "medico", "fecha", "dx", "id_kardex"}
    assert set(r["kardex"][0]) == {"id", "servicio", "nombre", "habitacion", "dx", "id_sistema"}
    assert e["progreso"]["total"] > 0 and e["progreso"]["actual"] == e["progreso"]["total"]
    assert any("Análisis terminado" in linea for linea in e["registro"])
    assert all(linea[2] == ":" for linea in e["registro"])

    auto = [a for a in r["acciones"] if a["automatica"]]
    otros = [a for a in r["acciones"] if not a["automatica"]]
    assert auto and all(a["tipo"] == "ACTUALIZAR" for a in auto)
    ids = [a["id"] for a in auto[:4]] + [otros[0]["id"]]      # el no automático se ignora
    st, _ = c.post("/api/escribir", {"ids": ids})
    assert st == 200
    e = c.esperar_fin(n)
    esc = e["escritura"]
    assert e["ultima"]["tipo"] == "escribir" and len(esc["escritas"]) == 3 and len(esc["omitidas"]) == 1
    assert esc["omitidas"][0]["motivo"].startswith("La fila cambió")
    assert set(esc["escritas"][0]) == {"id", "paciente", "campo"}
    assert set(esc["omitidas"][0]) == {"id", "paciente", "campo", "motivo"}
    quedan = {a["id"] for a in e["resultado"]["acciones"]}
    assert not quedan & {x["id"] for x in esc["escritas"]}
    assert esc["omitidas"][0]["id"] in quedan

    st, r = c.post("/api/escribir", {"ids": [otros[0]["id"]]})
    assert st == 400 and r["ok"] is False
    assert c.post("/api/escribir", {"ids": "a1"})[0] == 400


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

    def falla(cfg, log, progreso, cancelado):
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
