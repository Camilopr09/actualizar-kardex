"""NavegadorVivo con un «playwright» falso: sin navegador real."""
import threading

import pytest

from errores import Cancelado, ErrorApp
from navegador_vivo import NavegadorVivo


class CtxFalso:
    def __init__(self, hilo):
        self.hilo, self.pages, self.cerrado, self.cbs = hilo, [object()], False, []

    def on(self, evento, cb):
        self.cbs.append((evento, cb))

    def new_page(self):
        self.pages.append(object())
        return self.pages[-1]

    def close(self):
        self.cerrado = True

    def matar(self):                       # la persona cerró la ventana
        self.cerrado = True
        for ev, cb in self.cbs:
            if ev == "close":
                cb(self)


class PwFalso:
    def __init__(self):
        self.hilo_inicio, self.parado = None, False

    def start(self):
        self.hilo_inicio = threading.current_thread()
        return self

    def stop(self):
        self.parado = True


@pytest.fixture
def mundo():
    m = {"pw": PwFalso(), "ctxs": [], "pref": "chrome", "prefs_abiertas": []}

    def abrir(pw, carpeta, pref, log):
        ctx = CtxFalso(threading.current_thread())
        m["ctxs"].append(ctx)
        m["prefs_abiertas"].append(pref)
        return ctx
    m["nav"] = NavegadorVivo("carpeta", lambda: m["pref"], lambda x: None, fabrica_playwright=lambda: m["pw"], abrir=abrir)
    yield m
    m["nav"].cerrar()


def test_corre_en_un_hilo_dedicado_con_el_contexto_vivo(mundo):
    nav = mundo["nav"]
    hilos = {nav.ejecutar(lambda ctx: threading.current_thread()) for _ in range(3)}
    assert len(hilos) == 1 and hilos != {threading.current_thread()}
    assert mundo["pw"].hilo_inicio in hilos                 # Playwright nació en ese hilo
    assert nav.ejecutar(lambda ctx, a, b: (ctx, a + b), 2, 3) == (mundo["ctxs"][0], 5)
    assert len(mundo["ctxs"]) == 1                          # se abrió una sola vez


def test_la_excepcion_se_relanza_en_quien_llama(mundo):
    def malo(ctx):
        raise ErrorApp("agenda", "falla")
    with pytest.raises(ErrorApp) as e:
        mundo["nav"].ejecutar(malo)
    assert e.value.codigo == "agenda"
    with pytest.raises(Cancelado):
        mundo["nav"].ejecutar(lambda ctx: (_ for _ in ()).throw(Cancelado()))
    assert mundo["nav"].ejecutar(lambda ctx: "sigue") == "sigue"      # el hilo sobrevive
    assert not mundo["ctxs"][0].cerrado                                # y el contexto no se cerró


def test_si_el_contexto_se_cerro_se_reabre(mundo):
    nav = mundo["nav"]
    nav.ejecutar(lambda ctx: None)
    mundo["ctxs"][0].matar()
    nav.ejecutar(lambda ctx: None)
    assert len(mundo["ctxs"]) == 2 and mundo["ctxs"][0].cerrado


def test_sin_pestanas_se_abre_una_y_si_falla_se_reabre(mundo):
    nav = mundo["nav"]
    nav.ejecutar(lambda ctx: None)
    ctx = mundo["ctxs"][0]
    ctx.pages.clear()
    assert nav.ejecutar(lambda c: len(c.pages)) == 1 and len(mundo["ctxs"]) == 1
    ctx.pages.clear()
    ctx.new_page = lambda: (_ for _ in ()).throw(RuntimeError("muerto"))
    nav.ejecutar(lambda c: None)
    assert len(mundo["ctxs"]) == 2


def test_contexto_que_muere_a_mitad_da_error_claro_y_el_siguiente_reabre(mundo):
    nav = mundo["nav"]

    def tarea(ctx):
        ctx.matar()
        raise RuntimeError("Target closed")
    with pytest.raises(ErrorApp) as e:
        nav.ejecutar(tarea)
    assert e.value.codigo == "navegador" and "Vuelve a intentarlo" in e.value.mensaje
    assert nav.ejecutar(lambda ctx: ctx) is mundo["ctxs"][1]


def test_cambio_de_navegador_cierra_y_reabre(mundo):
    nav = mundo["nav"]
    nav.ejecutar(lambda ctx: None)
    mundo["pref"] = "brave"
    nav.ejecutar(lambda ctx: None)
    assert mundo["prefs_abiertas"] == ["chrome", "brave"] and mundo["ctxs"][0].cerrado


def test_cerrar_termina_el_hilo_y_cierra_todo(mundo):
    nav = mundo["nav"]
    nav.ejecutar(lambda ctx: None)
    assert nav.hilo_vivo
    nav.cerrar()
    assert not nav.hilo_vivo and mundo["ctxs"][0].cerrado and mundo["pw"].parado
    with pytest.raises(ErrorApp):
        nav.ejecutar(lambda ctx: None)
    nav.cerrar()                                            # idempotente


def test_cerrar_sin_haber_usado_el_navegador(mundo):
    mundo["nav"].cerrar()
    assert mundo["ctxs"] == []
