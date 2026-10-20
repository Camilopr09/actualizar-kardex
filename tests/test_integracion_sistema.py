"""Ejecuta flujo.analizar de verdad (Playwright + Chromium sin ventana) contra el simulador de
Hospital Office y del kardex (tests/simulador). Se salta si no hay playwright o Chromium."""
import time

import pytest

import flujo
import sistema
from chromium_pruebas import disponible
from errores import ErrorApp
from simulador.servidor import CLAVE, USUARIO, Simulador

CHROMIUM = disponible()
pytestmark = pytest.mark.skipif(CHROMIUM is None, reason="falta playwright o Chromium")


@pytest.fixture(autouse=True)
def navegador_de_prueba(monkeypatch, datos_temporales):
    monkeypatch.setenv("KARDEX_CHROME", CHROMIUM)
    monkeypatch.setenv("KARDEX_HEADLESS", "1")
    flujo.hospital_guardar(USUARIO, CLAVE)          # por defecto la app entra sola


def _cfg(sim):
    return {"url_kardex": sim.url_kardex, "url_agenda": sim.url_agenda,
            "especialistas": ["DAZA", "FABIAN", "EMILIANI"], "navegador": "chrome"}


def _analizar(sim, cancelado=lambda: False):
    registro, avance = [], []
    res = flujo.analizar(_cfg(sim), registro.append, lambda i, n, nombre: avance.append((i, n, nombre)), cancelado)
    return res, registro, avance


def _acc(acciones, paciente, tipo, campo=None):
    return [a for a in acciones if a.paciente == paciente and a.tipo == tipo and (campo is None or a.campo == campo)]


def test_analizar_contra_el_simulador():
    with Simulador() as sim:
        (pacientes, kardex, acciones), registro, avance = _analizar(sim)

    por = {p.nombre: p for p in pacientes}
    assert len(pacientes) == 6 and len(kardex) == 6
    # modos y casilla «Últimas 24 horas»: ESCOBAR solo aparece si se desmarca
    assert por["ESCOBAR TRUJILLO IVAN"].modo == "Urgencias" and por["ESCOBAR TRUJILLO IVAN"].habitacion == "U-07"
    assert por["ALVARADO RUIZ PEDRO PABLO"].modo == "Hospitalización"
    assert por["ALVARADO RUIZ PEDRO PABLO"].habitacion == "2-01"
    # progreso: solo los pacientes que están en el kardex y en el sistema (5)
    assert [(i, n) for i, n, _ in avance] == [(i, 5) for i in range(1, 6)]

    # ---- ALVARADO: toma la hoja del ESPECIALISTA más reciente (no la de enfermería, más nueva)
    a = por["ALVARADO RUIZ PEDRO PABLO"]
    assert a.encontrado_detalle and not a.aviso
    assert a.dx == "1. COLECISTITIS AGUDA\n2. HTA"
    assert a.medico == "DAZA PEREZ JUAN" and a.fecha == "19/10/2026 06:30"
    assert a.evolucion == ("19/10/2026 - DR. DAZA PEREZ JUAN (MEDICINA INTERNA)\n"
                           "EXAMEN FISICO: ALERTA, SIN DOLOR ANALISIS: EVOLUCION FAVORABLE")
    assert "NO DEBE LEERSE" not in a.tratamiento and "OTRO DX" not in a.dx
    # PLAN sin «igual manejo»: el tratamiento es el plan tal cual
    assert a.tratamiento == "PLAN\n1. DIETA LIQUIDA\n2. CEFAZOLINA 1 G IV C/8H\n3. OMEPRAZOL 40 MG IV C/24H"
    for campo in ("DX", "EVOLUCIÓN", "TRATAMIENTO"):
        act = _acc(acciones, "PEDRO ALVARADO", "ACTUALIZAR", campo)
        assert len(act) == 1 and act[0].automatica and act[0].nuevo == {
            "DX": "DX:\n" + a.dx, "EVOLUCIÓN": a.evolucion, "TRATAMIENTO": a.tratamiento}[campo]

    # ---- BENAVIDES: IGUAL MANEJO conserva el tratamiento del kardex y suma lo nuevo de las órdenes
    b = por["BENAVIDES LUNA SOFIA"]
    assert b.tratamiento.splitlines() == ["IGUAL MANEJO (DR. FABIAN GOMEZ LUIS 19/10/2026)", "NVO",
                                          "CEFTRIAXONA 2 G — 2 G IV C/24H", "DIETA BLANDA",
                                          "ENOXAPARINA 40 MG — 40 MG SC C/24H"]
    (bt,) = _acc(acciones, "SOFIA BENAVIDES LUNA", "ACTUALIZAR", "TRATAMIENTO")
    assert bt.nuevo == b.tratamiento and bt.actual.splitlines()[0] == "PLAN"
    assert not _acc(acciones, "SOFIA BENAVIDES LUNA", "ACTUALIZAR", "DX")      # el DX ya coincide

    # ---- CORREA: kardex al día -> ninguna acción
    assert not [x for x in acciones if x.paciente == "TOMAS CORREA MEJIA"]

    # ---- DUQUE: solo hay hoja de una persona que no es especialista -> aviso REVISAR
    d = por["DUQUE SALAS MARIA ELENA"]
    assert "no es de un especialista" in d.aviso and "TORRES NIETO ROSA" in d.aviso
    rev = _acc(acciones, "MARIA DUQUE SALAS", "REVISAR")
    assert len(rev) == 1 and "especialista" in rev[0].detalle and not rev[0].automatica

    # ---- GUTIERREZ: otra habitación -> REVISAR HABITACIÓN
    hab = _acc(acciones, "LAURA GUTIERREZ OSORIO", "REVISAR", "HABITACIÓN")
    assert hab and (hab[0].actual, hab[0].nuevo) == ("4-05", "4-08")

    # ---- AGREGAR / RETIRAR
    ag = [x for x in acciones if x.tipo == "AGREGAR"]
    assert [x.paciente for x in ag] == ["ESCOBAR TRUJILLO IVAN"] and not ag[0].automatica
    ret = [x for x in acciones if x.tipo == "RETIRAR"]
    assert [x.paciente for x in ret] == ["ELSA FIGUEROA PARDO"] and ret[0].servicio == "URGENCIAS"
    assert any("Leyendo la Agenda" in linea for linea in registro)


def test_cancelar_se_revisa_antes_de_cada_paciente():
    from errores import Cancelado
    with Simulador() as sim:
        llamadas = []

        def cancelado():
            llamadas.append(1)
            return len(llamadas) > 1
        with pytest.raises(Cancelado):
            _analizar(sim, cancelado)


def test_login_automatico_con_credenciales_correctas():
    with Simulador() as sim:
        (pacientes, _, _), registro, avance = _analizar(sim)
        assert sim.logins == 1
    assert len(pacientes) == 6 and len(avance) == 5
    assert not any(CLAVE in linea for linea in registro)


def test_credenciales_malas_dan_error_de_sesion_sin_la_clave_en_el_diagnostico(datos_temporales):
    flujo.hospital_guardar(USUARIO, "Otra-Clave-Mala-999")
    with Simulador() as sim:
        registro = []
        with pytest.raises(ErrorApp) as e:
            flujo.analizar(_cfg(sim), registro.append, lambda *a: None, lambda: False)
        assert sim.logins == 0
    assert e.value.codigo == "sesion" and e.value.mensaje.startswith("Usuario o contraseña de Hospital Office no válidos")
    assert flujo.hospital_credenciales() is None          # se borran para no bloquear la cuenta
    archivos = list((datos_temporales / "diagnostico").glob("*"))
    assert any(a.suffix == ".html" for a in archivos) and any(a.suffix == ".png" for a in archivos)
    for a in archivos:
        if a.suffix == ".html":
            assert "Otra-Clave-Mala-999" not in a.read_text(encoding="utf-8")
    assert not any("Otra-Clave-Mala-999" in linea for linea in registro)


def test_sin_credenciales_espera_a_que_la_persona_inicie_sesion(monkeypatch, datos_temporales):
    flujo.hospital_quitar()
    ctxs = []
    real = sistema.abrir_contexto
    monkeypatch.setattr(sistema, "abrir_contexto", lambda *a, **k: ctxs.append(real(*a, **k)) or ctxs[-1])
    hecho = {"t0": None, "login": False}

    def cancelado():              # se llama desde el mismo hilo de Playwright: aquí «la persona» entra
        if hecho["t0"] is None and any("te espero" in m for m in registro):
            hecho["t0"] = time.monotonic()
        if hecho["t0"] and not hecho["login"] and time.monotonic() - hecho["t0"] > 2:
            hecho["login"] = True
            pg = ctxs[0].pages[0]
            pg.fill("input[type=text]", USUARIO)
            pg.fill("input[type=password]", CLAVE)
            pg.click("text=Ingresar")
        return False
    registro, avance, esperas = [], [], []
    with Simulador() as sim:
        (pacientes, _, _) = flujo.analizar(
            _cfg(sim), registro.append, lambda i, n, nombre: (esperas if i == 0 else avance).append((i, n, nombre)),
            cancelado)[0:3]
    assert hecho["login"] and len(pacientes) == 6 and len(avance) == 5
    assert esperas == [(0, 0, "Esperando inicio de sesión…")]


def test_sin_credenciales_se_puede_cancelar_la_espera(datos_temporales):
    from errores import Cancelado
    flujo.hospital_quitar()
    with Simulador() as sim:
        n = []

        def cancelado():
            n.append(1)
            return len(n) > 2
        with pytest.raises(Cancelado):
            _analizar(sim, cancelado)


def test_sesion_que_vence_a_mitad_se_vuelve_a_iniciar():
    with Simulador(vence_tras=12) as sim:
        (pacientes, _, acciones), registro, avance = _analizar(sim)
        assert sim.logins == 2                      # el segundo login es el re-login
    por = {p.nombre: p for p in pacientes}
    assert all(p.encontrado_detalle for p in pacientes if p.nombre in
               {"ALVARADO RUIZ PEDRO PABLO", "BENAVIDES LUNA SOFIA", "CORREA MEJIA TOMAS",
                "DUQUE SALAS MARIA ELENA", "GUTIERREZ OSORIO LAURA"}), [p.aviso for p in por.values()]
    assert len(avance) == 5


def test_navegacion_por_menu_principal_y_atencion_de_pacientes():
    with Simulador() as sim:
        (pacientes, _, _), _, _ = _analizar(sim)
        assert any(s["menu"] for s in sim.sesiones.values())     # pasó por /Menu.aspx
    assert len(pacientes) == 6


def test_agenda_directa_sin_menu_no_basta_y_sin_enlaces_es_error_de_agenda():
    # el simulador ya no entrega la Agenda sin pasar por el menú; si el menú no existe, error «agenda»
    with Simulador() as sim:
        sim.agenda_requiere_menu = True
        import simulador.servidor as m
        original = m.MENU
        m.MENU = "<html><body><h1>Menú vacío</h1></body></html>"
        try:
            with pytest.raises(ErrorApp) as e:
                _analizar(sim)
        finally:
            m.MENU = original
    assert e.value.codigo == "agenda"


def test_kardex_inaccesible_produce_error_kardex():
    with Simulador() as sim:
        sim.kardex_sirve = False
        with pytest.raises(ErrorApp) as e:
            _analizar(sim)
    assert e.value.codigo == "kardex"


def test_fallo_de_agenda_en_un_paciente_no_aborta_el_analisis():
    # visitas 1 y 2: listado (Urgencias / Hospitalización); visita 3: la Agenda de ALVARADO (el primero del kardex)
    # (ir_agenda se recupera una vez: la segunda visita también está rota para que el paciente falle)
    with Simulador(agenda_rota_en=[3, 4]) as sim:
        (pacientes, _, acciones), registro, avance = _analizar(sim)
    por = {p.nombre: p for p in pacientes}
    assert "No pude leer su historia" in por["ALVARADO RUIZ PEDRO PABLO"].aviso
    assert not por["ALVARADO RUIZ PEDRO PABLO"].encontrado_detalle
    assert por["BENAVIDES LUNA SOFIA"].encontrado_detalle        # los demás siguieron
    assert len(avance) == 5
    assert _acc(acciones, "PEDRO ALVARADO", "REVISAR")


def test_agenda_sin_grillas_en_el_listado_es_error_de_agenda():
    with Simulador(agenda_rota_en=[1]) as sim:
        with pytest.raises(ErrorApp) as e:
            _analizar(sim)
    assert e.value.codigo == "agenda"


def _sesion(sim, **kw):
    pasos = []
    flujo.iniciar_sesion(_cfg(sim), lambda m: None, pasos.append, **kw)
    return pasos


def test_iniciar_sesion_detecta_hospital_y_termina_con_terminar():
    with Simulador(exige_login=False, agenda_requiere_menu=False) as sim:
        llamadas = []

        def terminar():
            llamadas.append(1)
            return len(llamadas) > 4
        pasos = _sesion(sim, terminar=terminar)
    assert pasos[-1]["hospital"] is True and pasos[-1]["google"] is False


def test_iniciar_sesion_con_login_no_cuenta_hospital():
    with Simulador() as sim:
        llamadas = []

        def terminar():
            llamadas.append(1)
            return len(llamadas) > 3
        pasos = _sesion(sim, terminar=terminar)
    assert all(p == {"hospital": False, "google": False} for p in pasos)
