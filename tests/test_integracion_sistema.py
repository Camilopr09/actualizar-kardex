"""Ejecuta flujo.analizar de verdad (Playwright + Chromium sin ventana) contra el simulador de
Hospital Office y del kardex (tests/simulador). Se salta si no hay playwright o Chromium."""
import time

import pytest

import flujo
import sistema
from navegador_vivo import NavegadorVivo
from chromium_pruebas import disponible
from errores import ErrorApp
from simulador.servidor import CLAVE, GRID_PEND, USUARIO, Simulador

CHROMIUM = disponible()
VENCE = 12              # petición protegida en la que vence la sesión
pytestmark = pytest.mark.skipif(CHROMIUM is None, reason="falta playwright o Chromium")


@pytest.fixture(autouse=True)
def navegador_de_prueba(monkeypatch, datos_temporales):
    monkeypatch.setenv("KARDEX_CHROME", CHROMIUM)
    monkeypatch.setenv("KARDEX_HEADLESS", "1")
    flujo.hospital_guardar(USUARIO, CLAVE)          # por defecto la app entra sola


@pytest.fixture
def nav(datos_temporales):
    """Navegador vivo de la prueba (se cierra al final)."""
    n = NavegadorVivo(datos_temporales, lambda: "chrome")
    yield n
    n.cerrar()


@pytest.fixture(autouse=True)
def _nav_global(nav):
    global NAV
    NAV = nav


def _cfg(sim):
    return {"url_kardex": sim.url_kardex, "url_agenda": sim.url_agenda,
            "especialistas": ["DAZA", "FABIAN", "EMILIANI"], "navegador": "chrome"}


def _analizar(sim, cancelado=lambda: False):
    registro, avance = [], []
    res = flujo.analizar(NAV, _cfg(sim), registro.append, lambda i, n, nombre: avance.append((i, n, nombre)), cancelado)
    return res, registro, avance


def _acc(acciones, paciente, tipo, campo=None):
    return [a for a in acciones if a.paciente == paciente and a.tipo == tipo and (campo is None or a.campo == campo)]


def test_analizar_contra_el_simulador():
    with Simulador() as sim:
        (pacientes, kardex, acciones), registro, avance = _analizar(sim)

    por = {p.nombre: p for p in pacientes}
    # solo los pacientes del kardex que están en el sistema (7 de 8): la lista general del hospital NO se trae
    assert len(kardex) == 8 and len(pacientes) == 7
    assert "ROSARIO QUIJANO LOPEZ" not in por and "ELSA MARINA ROJAS DIAZ" not in por
    # progreso: n = pacientes del kardex (también los que no aparecen)
    assert [(i, n) for i, n, _ in avance] == [(i, 8) for i in range(1, 9)]
    # modo preferido según el servicio: ESCOBAR está en «PISO 5» (Hospitalización) pero es de Urgencias -> prueba el otro
    esc = por["IVAN ESCOBAR TRUJILLO"]
    assert esc.modo == "Urgencias" and esc.habitacion == "H4CAM-09" and esc.documento == "1020304055"
    assert por["PEDRO PABLO ALVARADO RUIZ"].modo == "Hospitalización"
    assert por["PEDRO PABLO ALVARADO RUIZ"].habitacion == "6PISO-607"
    assert por["PEDRO PABLO ALVARADO RUIZ"].tipo_documento == "CC" and por["PEDRO PABLO ALVARADO RUIZ"].estado == "P"
    # «Actualizar» se pulsó con «Últimas 24 horas» desmarcada en los dos modos
    assert ("Hospitalización", False) in sim.actualizaciones and ("Urgencias", False) in sim.actualizaciones

    # ---- ALVARADO: toma la hoja del ESPECIALISTA más reciente (no la de enfermería, más nueva)
    a = por["PEDRO PABLO ALVARADO RUIZ"]
    assert a.encontrado_detalle and not a.aviso
    assert a.dx == "1. COLECISTITIS AGUDA\n2. HTA"
    assert a.medico == "DAZA PEREZ JUAN" and a.fecha == "19/10/2026 06:30"
    assert a.evolucion == ("19/10/2026 - DR. DAZA PEREZ JUAN (MEDICINA INTERNA)\n"
                           "EVOLUCION FAVORABLE")       # texto de la pestaña ANALISIS (sin el «-MEDICINA INTERNA-»)
    assert "NO DEBE LEERSE" not in a.tratamiento and "OTRO DX" not in a.dx
    assert a.tratamiento == "PLAN\n1. DIETA LIQUIDA\n2. CEFAZOLINA 1 G IV C/8H\n3. OMEPRAZOL 40 MG IV C/24H"
    for campo in ("DX", "EVOLUCIÓN", "TRATAMIENTO"):
        act = _acc(acciones, "PEDRO ALVARADO", "ACTUALIZAR", campo)
        assert len(act) == 1 and act[0].automatica and act[0].nuevo == {
            "DX": "DX:\n" + a.dx, "EVOLUCIÓN": a.evolucion, "TRATAMIENTO": a.tratamiento}[campo]

    # ---- DX/EVOLUCIÓN/PLAN leídos por pestañas (clic en cada una; solo una es visible a la vez)
    # ESCOBAR: ANALISIS vacío -> SINTOMAS DESCRITOS + EXAMEN FISICO; DX tipo (a) con 3 ítems
    assert esc.dx == "1. PANCREATITIS AGUDA\n2. COLELITIASIS\n3. DM2"
    assert esc.evolucion == "19/10/2026 - DR. DAZA PEREZ JUAN\nDOLOR ABDOMINAL ABDOMEN BLANDO"
    assert esc.tratamiento == "PLAN\n1. NVO"
    # MONTENEGRO: DX tipo (b): el renglón «DIAGNÓSTICO» es el encabezado; lo anterior (evolución) se descarta
    assert por["JAIRO ANDRES MONTENEGRO VEGA"].dx.splitlines() == [
        "- SINDROME COLEDOCIANO /COLESTASIS SEVERA",
        "- POST DE DRENAJE BILIAR INTERNO - EXTERNO + DILATACIÓN PERCUTÁNEA DE LA AMPOLLA Y DEL CONDUCTO BILIAR (13/10/26)",
        "- FALLA RENAL CRONICA AGUDIZADA"]
    assert por["JAIRO ANDRES MONTENEGRO VEGA"].tratamiento == "PLAN\n1. DIETA NORMAL\n2. CEFTRIAXONA 2 G IV C/24H"
    # GUTIERREZ: «IDX:» y luego la sección «EVOLUCION:» dentro del mismo textarea -> solo el diagnóstico
    assert por["LAURA GUTIERREZ OSORIO"].dx == "1. APENDICITIS AGUDA COMPLICADA"
    assert por["LAURA GUTIERREZ OSORIO"].evolucion == "19/10/2026 - DR. FABIAN GOMEZ LUIS (MEDICINA INTERNA)\nEVOLUCION FAVORABLE"

    # ---- BENAVIDES: IGUAL MANEJO conserva el tratamiento del kardex y suma lo nuevo de las órdenes
    b = por["SOFIA BENAVIDES LUNA"]
    assert b.tratamiento.splitlines() == ["IGUAL MANEJO (DR. FABIAN GOMEZ LUIS 19/10/2026)", "NVO",
                                          "CEFTRIAXONA 2 G — 2 G IV C/24H", "DIETA BLANDA",
                                          "ENOXAPARINA 40 MG — 40 MG SC C/24H"]
    (bt,) = _acc(acciones, "SOFIA BENAVIDES LUNA", "ACTUALIZAR", "TRATAMIENTO")
    assert bt.nuevo == b.tratamiento and bt.actual.splitlines()[0] == "PLAN"
    assert not _acc(acciones, "SOFIA BENAVIDES LUNA", "ACTUALIZAR", "DX")      # el DX ya coincide

    # ---- CORREA: kardex al día y habitación «CUB 12» ≡ «HOS82-12» -> ninguna acción
    assert not [x for x in acciones if x.paciente == "TOMAS CORREA MEJIA"]

    # ---- DUQUE: solo hay hoja de una persona que no es especialista -> aviso REVISAR (y «305B» ≡ «3PISO-305B»)
    d = por["MARIA ELENA DUQUE SALAS"]
    assert "no es de un especialista" in d.aviso and "TORRES NIETO ROSA" in d.aviso
    rev = _acc(acciones, "MARIA DUQUE SALAS", "REVISAR")
    assert len(rev) == 1 and "especialista" in rev[0].detalle and not rev[0].automatica

    # ---- habitaciones: «607» ≡ «6PISO-607», «426» ≡ «4PISO-426», «CUB 9» ≡ «H4CAM-09», PASILLO no se compara
    for nombre in ("PEDRO ALVARADO", "SOFIA BENAVIDES LUNA", "IVAN ESCOBAR TRUJILLO", "HERNAN PALACIOS"):
        assert not _acc(acciones, nombre, "REVISAR", "HABITACIÓN"), nombre
    hab = _acc(acciones, "LAURA GUTIERREZ OSORIO", "REVISAR", "HABITACIÓN")
    assert len(hab) == 1 and (hab[0].actual, hab[0].nuevo) == ("405", "4PISO-408")
    assert len([x for x in acciones if x.campo == "HABITACIÓN"]) == 1

    # ---- HERNAN PALACIOS: el nombre del kardex no se parece, pero el documento coincide
    j = por["JAIRO ANDRES MONTENEGRO VEGA"]
    assert j.encontrado_detalle and j.habitacion == "PEDIA-07"
    assert _acc(acciones, "HERNAN PALACIOS", "ACTUALIZAR", "DX")
    assert not _acc(acciones, "HERNAN PALACIOS", "RETIRAR")

    # ---- RETIRAR: no aparece en ningún modo (y no se confunde con la tocaya ELSA MARINA ROJAS DIAZ)
    ret = [x for x in acciones if x.tipo == "RETIRAR"]
    assert [x.paciente for x in ret] == ["ELSA FIGUEROA PARDO"] and ret[0].servicio == "URGENCIAS"
    # ---- AGREGAR: sin lista de atendidos no se propone ningún paciente (la lista general es de todo el hospital)
    assert not [x for x in acciones if x.tipo == "AGREGAR"]
    assert registro.count("No hay lista de pacientes atendidos: no se proponen pacientes nuevos") == 1
    assert any("Leyendo la Agenda" in linea for linea in registro)


@pytest.mark.parametrize("pag_cliente", [True, False])
def test_agregar_solo_desde_atendidos_con_paginacion(pag_cliente):
    # la grilla de atendidos (inexistente en el sistema real; respaldo) tiene páginas de 2 filas:
    # GUTIERREZ y DUQUE (del kardex) en la 1.ª y QUIJANO (no está en el kardex) en la 2.ª
    with Simulador(con_atendidos=True, tam_atendidos=2, pag_cliente=pag_cliente) as sim:
        (pacientes, _, acciones), registro, _ = _analizar(sim)
    por = {p.nombre: p for p in pacientes}
    # los del kardex que ya fueron atendidos se encuentran en la grilla de atendidos y se leen completos
    assert por["MARIA ELENA DUQUE SALAS"].aviso and por["LAURA GUTIERREZ OSORIO"].encontrado_detalle
    ag = [x for x in acciones if x.tipo == "AGREGAR"]
    assert [x.paciente for x in ag] == ["ROSARIO QUIJANO LOPEZ"] and not ag[0].automatica and not ag[0].marcada
    assert ag[0].habitacion == "3PISO-311"
    # nunca de la lista «Pacientes Por Atender» (ELSA MARINA ROJAS DIAZ, PEDRO NEL SIERRA CANO, rellenos…)
    assert len(pacientes) == 8 and len(ag) == 1
    assert not any("No hay lista de pacientes atendidos" in linea for linea in registro)


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
    assert len(pacientes) == 7 and len(avance) == 8
    assert not any(CLAVE in linea for linea in registro)


def test_credenciales_malas_dan_error_de_sesion_sin_la_clave_en_el_diagnostico(datos_temporales):
    flujo.hospital_guardar(USUARIO, "Otra-Clave-Mala-999")
    with Simulador() as sim:
        registro = []
        with pytest.raises(ErrorApp) as e:
            flujo.analizar(NAV, _cfg(sim), registro.append, lambda *a: None, lambda: False)
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
            pg.click("input[type=text]")
            pg.keyboard.press("Control+A")
            pg.keyboard.type(USUARIO)
            pg.fill("input[type=password]", CLAVE)
            pg.click("input[type=image]")
        return False
    registro, avance, esperas = [], [], []
    with Simulador() as sim:
        (pacientes, _, _) = flujo.analizar(
            NAV, _cfg(sim), registro.append, lambda i, n, nombre: (esperas if i == 0 else avance).append((i, n, nombre)),
            cancelado)[0:3]
    assert hecho["login"] and len(pacientes) == 7 and len(avance) == 8
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
    with Simulador(vence_tras=VENCE) as sim:
        (pacientes, _, acciones), registro, avance = _analizar(sim)
        assert sim.logins == 2                      # el segundo login es el re-login
    assert all(p.encontrado_detalle for p in pacientes if not p.aviso), [p.aviso for p in pacientes]
    assert len(pacientes) == 7 and len(avance) == 8


def test_navegacion_por_el_acordeon_menu_principal_y_atencion_de_pacientes():
    with Simulador() as sim:
        (pacientes, _, _), _, _ = _analizar(sim)
        assert any(s["menu"] for s in sim.sesiones.values())     # pasó por «Atencion de Pacientes»
    assert len(pacientes) == 7


def test_sin_enlace_de_atencion_de_pacientes_es_error_de_agenda():
    # el simulador no entrega la grilla sin pasar por el menú; si el menú no trae el enlace, error «agenda»
    with Simulador(con_atencion_en_menu=False) as sim:
        with pytest.raises(ErrorApp) as e:
            _analizar(sim)
    assert e.value.codigo == "agenda"


def test_kardex_inaccesible_produce_error_kardex():
    with Simulador() as sim:
        sim.kardex_sirve = False
        with pytest.raises(ErrorApp) as e:
            _analizar(sim)
    assert e.value.codigo == "kardex"


def test_fallo_de_agenda_en_un_paciente_no_aborta_el_analisis():
    # visita 1: entrada; 2: búsqueda de ALVARADO (el primero del kardex); 3 y 4: su historia (la 4.ª es el
    # intento de recuperación de ir_agenda y la 5.ª su último recurso (la URL aprendida): también rotas para que falle)
    with Simulador(agenda_rota_en=[3, 4, 5]) as sim:
        (pacientes, _, acciones), registro, avance = _analizar(sim)
    por = {p.nombre: p for p in pacientes}
    assert "No pude leer su historia" in por["PEDRO PABLO ALVARADO RUIZ"].aviso
    assert not por["PEDRO PABLO ALVARADO RUIZ"].encontrado_detalle
    assert por["SOFIA BENAVIDES LUNA"].encontrado_detalle        # los demás siguieron
    assert len(avance) == 8
    assert _acc(acciones, "PEDRO ALVARADO", "REVISAR")


def test_agenda_sin_grillas_al_entrar_es_error_de_agenda():
    with Simulador(agenda_rota_en=[1]) as sim:
        with pytest.raises(ErrorApp) as e:
            _analizar(sim)
    assert e.value.codigo == "agenda"


def _sesion(sim, **kw):
    pasos = []
    flujo.iniciar_sesion(NAV, _cfg(sim), lambda m: None, pasos.append, **kw)
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


def _ctx_vivo(nav):
    return nav.ejecutar(lambda ctx: ctx)


def test_dos_analisis_seguidos_hacen_un_solo_login(nav):
    with Simulador() as sim:
        (p1, _, _), _, _ = _analizar(sim)
        ctx1 = _ctx_vivo(nav)
        (p2, _, _), _, _ = _analizar(sim)
        assert _ctx_vivo(nav) is ctx1               # el navegador no se cerró entre análisis
        assert sim.logins == 1
        # una sola pestaña de Hospital Office reutilizada: no se acumulan pestañas
        assert nav.ejecutar(lambda ctx: len(ctx.pages)) == 1
    assert len(p1) == len(p2) == 7


def test_tras_un_error_de_agenda_el_contexto_sigue_abierto(nav):
    with Simulador(con_atencion_en_menu=False) as sim:
        with pytest.raises(ErrorApp) as e:
            _analizar(sim)
        assert e.value.codigo == "agenda"
        ctx = _ctx_vivo(nav)
        assert nav.ejecutar(lambda c: [p.is_closed() for p in c.pages]) == [False]
        assert _ctx_vivo(nav) is ctx


def test_si_se_cierra_el_contexto_entre_analisis_se_reabre_y_se_vuelve_a_entrar(nav):
    with Simulador() as sim:
        _analizar(sim)
        assert sim.logins == 1
        ctx1 = _ctx_vivo(nav)
        nav.ejecutar(lambda ctx: ctx.close())             # «la persona cerró la ventana»
        (p2, _, _), _, _ = _analizar(sim)
        assert _ctx_vivo(nav) is not ctx1
        assert sim.logins == 2
    assert len(p2) == 7


def test_iniciar_sesion_no_cierra_el_navegador(nav):
    with Simulador(exige_login=False, agenda_requiere_menu=False) as sim:
        llamadas = []
        _sesion(sim, terminar=lambda: llamadas.append(1) or len(llamadas) > 2)
        assert nav.ejecutar(lambda ctx: len(ctx.pages)) == 2      # Agenda + kardex, abiertas
        (pacientes, _, _), _, _ = _analizar(sim)                    # reutiliza la pestaña de la Agenda
        assert nav.ejecutar(lambda ctx: len(ctx.pages)) == 2
    assert len(pacientes) == 7


# ---------------------------------------------------------------- pruebas con el Sistema directo
@pytest.fixture
def sis(tmp_path):
    """Fábrica de Sistema contra un simulador: sis(sim, con_credenciales=True) -> Sistema (el navegador se cierra al final)."""
    from playwright.sync_api import sync_playwright
    cerrar = []

    def fabrica(sim, credenciales=True):
        pw = sync_playwright().start()
        ctx = sistema.abrir_contexto(pw, tmp_path / "perfil", "chrome", lambda m: None)
        cerrar.append((pw, ctx))
        return sistema.Sistema(ctx, _cfg(sim), lambda m: None, tmp_path / "diag",
                               credenciales={"usuario": USUARIO, "clave": CLAVE} if credenciales else None)
    yield fabrica
    for pw, ctx in cerrar:
        try:
            ctx.close()
        finally:
            pw.stop()


@pytest.mark.parametrize("boton", ["image", "enlace", "enter"])
def test_login_con_watermark_y_boton_entrar_como_imagen(sis, boton):
    with Simulador(boton_login=boton) as sim:
        s = sis(sim)
        s.page.goto(sim.url_agenda)
        assert sistema.pagina_pide_login(s.page)
        assert s.page.input_value("#txtUsuario") == "Usuario"         # texto guía, no un valor real
        assert s.page.locator("button, input[type=submit]").count() == 0
        s.asegurar_sesion()
        assert sim.logins == 1
        assert "(Salir)" in s.page.inner_text("body") and "DashBoard" in s.page.inner_text("body")


@pytest.mark.parametrize("desplegado", [False, True])
@pytest.mark.parametrize("id_pend", [None, "ctl00_cph1_cbpPanel1_grdPorAtender"])
def test_acordeon_y_grilla_por_id_o_por_titulo(sis, desplegado, id_pend):
    with Simulador(menu_desplegado=desplegado, id_pend=id_pend) as sim:
        s = sis(sim)
        s.ir_agenda()
        # «Menu Principal» no se vuelve a pulsar si ya estaba desplegado (pulsarlo pliega el acordeón)
        assert s.grid_pend == (id_pend or GRID_PEND)
        assert "Atencion De Pacientes" in s.page.inner_text("body")
        assert s._filas(s.grid_pend)


@pytest.mark.parametrize("variante", [
    {"iframe": True}, {"sin_titulo": True}, {"icono_en_cabecera": True}, {"agenda_redirige": True},
    {"iframe": True, "sin_titulo": True, "icono_en_cabecera": True, "menu_desplegado": True}])
def test_variantes_de_la_navegacion_hasta_la_grilla(sis, variante):
    with Simulador(**variante) as sim:
        s = sis(sim)
        s.ir_agenda()
        assert sim.logins == 1                                     # tras entrar no se vuelve a llenar el login
        assert s.grid_pend == (sim.cfg["id_pend"])
        assert (s._fr() is not s.page.main_frame) == bool(variante.get("iframe"))
        assert s._filas(s.grid_pend)
        # segunda vez: por la URL aprendida, sin volver a iniciar sesión ni pasar por el menú
        s.ir_agenda()
        assert sim.logins == 1 and s._filas(s.grid_pend)
        if variante.get("agenda_redirige"):
            assert sim.visitas_url_agenda == 1                     # url_agenda no se vuelve a pedir en bucle
        # filtros, lectura de filas y «Atender» usan el frame de la grilla
        p = s.buscar("HERNAN PALACIOS", "1020304057", "CC", ["Hospitalización", "Urgencias"])
        assert p and p.nombre == "JAIRO ANDRES MONTENEGRO VEGA"
        assert s._atender(p)
        ev = s._ultimo_formato("HOJA DE EVOLUCION", ["DAZA"], estructurado=True)
        assert ev and ev["formato"]["DIAGNOSTICO"]["DX"].startswith("EVOLUCION UCI")
        s._recargar()
        s._fr().wait_for_selector("#ctl00_cph1_ASPxRoundPanel2_grdFormatos")
        assert s._ultimo_formato("HOJA DE EVOLUCION", ["DAZA"]) is not None


def test_login_realista_sin_password_ni_login_en_la_url(sis):
    # usuario con texto guía, contraseña type=text que pasa a password al enfocar, botón input[type=image] src=/img/entrar.png
    with Simulador(login_realista=True) as sim:
        s = sis(sim)
        s.page.goto(sim.url_agenda)
        assert "login" not in s.page.url.lower() and sim.ruta_login in s.page.url
        assert sistema.pagina_pide_login(s.page)
        s.ir_agenda()
        assert sim.logins == 1 and s._filas(s.grid_pend)
        assert not sistema.pagina_pide_login(s.page)
        assert "(Salir)" in s.page.inner_text("body") or s.grid_pend


def test_login_realista_con_clave_mala_da_error_de_sesion(sis):
    with Simulador(login_realista=True) as sim:
        s = sis(sim)
        s.cred = {"usuario": USUARIO, "clave": "mala"}
        with pytest.raises(ErrorApp) as e:
            s.ir_agenda()
    assert e.value.codigo == "sesion" and e.value.mensaje.startswith(s.MSG_LOGIN_MALO)


def test_login_realista_sin_credenciales_espera_a_la_persona(sis):
    with Simulador(login_realista=True) as sim:
        s = sis(sim, credenciales=False)
        s.ESPERA_PERSONA = 2
        with pytest.raises(ErrorApp) as e:
            s.ir_agenda()                  # detecta el login y espera (se agotan los 2 s)
    assert e.value.codigo == "sesion" and "agotaron" in e.value.mensaje


def test_falta_menu_principal_dice_el_paso_que_fallo(sis):
    with Simulador() as sim:
        s = sis(sim)
        s.asegurar_sesion()
        s._clic_texto = lambda *a, **k: False
        assert not s._por_el_menu()
        assert s._paso == 'No encontré "Menu Principal"'


def test_menu_sin_atencion_de_pacientes_dice_el_paso_que_fallo(sis):
    with Simulador(con_atencion_en_menu=False) as sim:
        s = sis(sim)
        with pytest.raises(ErrorApp) as e:
            s.ir_agenda()
        assert e.value.codigo == "agenda"
        assert e.value.mensaje.startswith('Pulsé "Menu Principal" pero no apareció "Atencion de Pacientes"')
        assert "(página: DashBoard — /Dashboard.aspx)" in e.value.mensaje


def test_mensaje_sin_menu_principal_en_ir_agenda(sis):
    with Simulador() as sim:
        s = sis(sim)
        s._clic_texto = lambda *a, **k: False          # como si la cabecera no existiera
        with pytest.raises(ErrorApp) as e:
            s.ir_agenda()
        assert e.value.mensaje == 'No encontré "Menu Principal" (página: DashBoard — /Dashboard.aspx)'
        assert any(a.suffix == ".png" for a in (s.diag).glob("*"))


def test_el_dashboard_no_se_confunde_con_un_login(pagina):
    pie = "<p>Software Asistencial eHC - Desarrollado por el Departamento de Sistemas</p>"
    pagina.set_content(f'<div>NOMBRE(<a href="#">Salir</a>)</div><input type="text"><input type="text">'
                       f'<input type="image" src="data:,x" width="20" height="20">{pie}')
    assert not sistema.pagina_pide_login(pagina)
    # login sin password real ni botón con texto: dos campos y el pie bastan
    pagina.set_content(f'<input type="text" value="Usuario"><input type="text">{pie}')
    assert sistema.pagina_pide_login(pagina)


def test_actualizar_es_necesario_para_que_la_grilla_cambie(pagina):
    with Simulador(exige_login=False, agenda_requiere_menu=False) as sim:
        pagina.goto(sim.url_agenda)
        antes = pagina.locator(f'[id^="{GRID_PEND}_DXDataRow"] td:first-child').all_inner_texts()
        assert "TOMAS CORREA MEJIA" in antes and "SOFIA BENAVIDES LUNA" not in antes     # abre en Urgencias
        pagina.get_by_label("Hospitalización").check()
        pagina.get_by_label("Últimas 24 horas.").uncheck()
        pagina.wait_for_timeout(800)
        assert pagina.locator(f'[id^="{GRID_PEND}_DXDataRow"] td:first-child').all_inner_texts() == antes   # sin Actualizar
        pagina.get_by_text("Actualizar", exact=True).click()
        pagina.wait_for_function("() => !ASPxClientControl.GetControlCollection().elements['%s'].InCallback()" % GRID_PEND)
        pagina.wait_for_timeout(500)
        despues = pagina.locator(f'[id^="{GRID_PEND}_DXDataRow"] td:first-child').all_inner_texts()
        assert despues != antes and "TOMAS CORREA MEJIA" not in despues
    assert ("Hospitalización", False) in sim.actualizaciones


@pytest.mark.parametrize("opciones", [
    {}, {"filtro_contiene": True}, {"campos_legibles": True}, {"autofilter_roto": True}, {"pag_cliente": False}])
def test_buscar_por_documento_aunque_el_nombre_este_mal(sis, opciones):
    with Simulador(**opciones) as sim:
        s = sis(sim)
        p = s.buscar("HERNAN PALACIOS", "1020304057", "CC", ["Hospitalización", "Urgencias"])
        assert p and p.nombre == "JAIRO ANDRES MONTENEGRO VEGA" and p.documento == "1020304057"
        assert (p.tipo_documento, p.habitacion, p.estado, p.modo) == ("CC", "PEDIA-07", "P", "Hospitalización")
        # tras cambiar de columna de filtro (documento -> nombre) no queda el filtro anterior
        assert s.buscar("ELSA FIGUEROA PARDO", "1020309999", "CC", ["Urgencias", "Hospitalización"]) is None
        # sin documento: filtra por Paciente (primera palabra) y empareja por nombre; no toma al tocayo
        q = s.buscar("PEDRO ALVARADO", "", "", ["Hospitalización", "Urgencias"])
        assert q and q.nombre == "PEDRO PABLO ALVARADO RUIZ" and q.documento == "1020304051"


@pytest.mark.parametrize("pag_cliente", [True, False])
def test_lectura_completa_recorre_todas_las_paginas(sis, pag_cliente):
    with Simulador(pag_cliente=pag_cliente) as sim:
        s = sis(sim)
        s.ir_agenda()
        s._modo("Hospitalización")
        filas = s._leer_todo(s.grid_pend)
        assert len(filas) > 10 and {f["pagina"] for f in filas} >= {0, 1}
        assert len({(f["nombre"], f["numero"]) for f in filas}) == len(filas)        # sin repetidos


def test_leer_formato_por_pestanas_y_orden_sin_pestanas(sis):
    with Simulador() as sim:
        s = sis(sim)
        p = s.buscar("PEDRO ALVARADO", "1020304051", "CC", ["Hospitalización"])
        assert s._atender(p)
        ev = s._ultimo_formato("HOJA DE EVOLUCION", ["DAZA"], estructurado=True)
        f = ev["formato"]
        assert list(f) == ["DIAGNOSTICO", "UNIDAD EN DONDE SE ENCUENTRA EL PACIENTE", "HIPOTESIS DIAGNOSTICA",
                           "SINTOMAS DESCRITOS", "EXAMEN FISICO", "ANALISIS", "PLAN", "SOLICITUD MATERIAL ESPECIAL"]
        d = f["DIAGNOSTICO"]       # textarea deshabilitada + combos; etiqueta = celda anterior de la fila
        assert d["DX"] == "1. COLECISTITIS AGUDA\n2. HTA" and d["SOSPECHA DENGUE"] == "NO"
        assert d["RIESGO DE VENTILACION"] == "NO APLICA" and d["PACIENTE CON SINTOMAS RESPIRATORIOS"] == "NO"
        assert f["ANALISIS"]["_texto"] == "-MEDICINA INTERNA-\nEVOLUCION FAVORABLE"
        assert f["PLAN"]["PLAN"].startswith("1. DIETA LIQUIDA") and f["HIPOTESIS DIAGNOSTICA"]["_texto"] == ""
        assert f["SOLICITUD MATERIAL ESPECIAL"] == {"_texto": ""}               # pestaña sin controles
        # el panel es el de la fila elegida (su título lleva el N° del formato)
        assert s._titulo_detalle() == ("22807102", "HOJA DE EVOLUCION MEDICO ESPECIALISTA")
        # las órdenes no tienen pestañas: texto completo
        s.page.reload(wait_until="domcontentloaded")
        od = s._ultimo_formato("ORDEN M")
        assert od["formato"] is None and "CEFAZOLINA 1G" in od["texto"]
        assert s._leer_formato()["FORMATO"]["_texto"] == od["texto"]


# ---------------------------------------------------------------- informes de imagenología
def _historia(s, pid):
    """Abre la historia del paciente `pid` del simulador (buscándolo en la Agenda y pulsando «Atender», como la app)."""
    from simulador.servidor import PACIENTES
    _, nombre, tipo, doc, _hab, modo, *_ = next(x for x in PACIENTES if x[0] == pid)
    p = s.buscar(nombre, doc, tipo, [modo])
    assert p and s._atender(p), nombre
    return p


def test_leer_imagenes_de_una_historia(sis):
    with Simulador() as sim:
        s = sis(sim)
        _historia(s, 1)
        res = s._leer_imagenes()
        # más reciente primero (en la grilla el más antiguo va antes); cada dato sale de la pestaña EXAMEN
        assert res == [
            {"numero": "22807105", "fecha_grilla": "19/10/2026 16:38:38", "fecha_texto": "19 DE OCTUBRE DEL 2026",
             "tipo": "ECOGRAFÍA", "estudio": "TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA",
             "texto": "Engrosamiento cutáneo\nÁreas líquidas de bordes irregulares, sin tabiques, de 12 x 8 mm.\n"
                      "No se observan colecciones organizadas.\n"
                      "OPINION: Hallazgos compatibles con proceso inflamatorio de tejidos blandos."},
            {"numero": "22807104", "fecha_grilla": "17/10/2026 09:12:45", "fecha_texto": "17 de octubre de 2026",
             "tipo": "TOMOGRAFÍA", "estudio": "ABDOMEN SIMPLE",
             "texto": "CONCLUSIÓN: -Hallazgos compatibles con proceso infeccioso de la vesícula biliar.\n"
                      "-Líquido libre en pelvis en mínima cantidad."}]
        # el panel es el del informe (título con su N°); «DESCRIPCIÓN DEL EXAMEN» viene vacía y EXAMEN tiene la
        # textarea del informe sin etiqueta (aquí queda con la etiqueta de la tira de pestañas, la de su fila vacía)
        assert s._abrir_informe("22807105", 0)
        assert s._titulo_detalle() == ("22807105", "INFORME DE IMAGENOLOGIA")
        f = s._leer_formato()
        assert list(f) == ["EXAMEN", "DESCRIPCION DEL EXAMEN"] and f["DESCRIPCION DEL EXAMEN"] == {"_texto": ""}
        ex = f["EXAMEN"]
        assert ex["FECHA DE REALIZACION DEL ESTUDIO"] == "19 DE OCTUBRE DEL 2026" and ex["TIPO ESTUDIO"] == "ECOGRAFÍA"
        assert ex["ESTUDIO"] == "TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA"
        assert [k for k, _ in ex["_areas"]][:2] == ["FECHA DE REALIZACION DEL ESTUDIO", "ESTUDIO"] and len(ex["_areas"]) == 3
        # leer solo EXAMEN (sin la pestaña vacía) da lo mismo
        assert s._datos_informe(s._leer_formato(omitir=("DESCRIPCION DEL EXAMEN",))) == s._datos_informe(f)


@pytest.mark.parametrize("filtro, pag_cliente", [
    ("contiene", True), ("contiene", False), ("empieza", True), ("ninguno", True), ("ninguno", False)])
def test_leer_imagenes_recorre_todas_las_paginas_de_formatos(sis, filtro, pag_cliente):
    # BENAVIDES: 18 formatos (2 páginas sin filtrar) y un informe en cada página; con «empieza con» el filtro
    # «IMAGENOLOG» no halla nada y se prueba «INFORME DE IMAGENOLOG»; con «ninguno» el filtro no hace nada y se
    # recorren las 2 páginas quedándose con las filas de imagenología
    with Simulador(filtro_formatos=filtro, pag_cliente=pag_cliente) as sim:
        s = sis(sim)
        _historia(s, 2)
        res = s._leer_imagenes()
        assert s._filtro_img == ("INFORME DE IMAGENOLOG" if filtro == "empieza" else "IMAGENOLOG")
    assert [(r["numero"], r["fecha_grilla"], r["tipo"], r["estudio"]) for r in res] == [
        ("22807213", "19/10/2026 05:50:00", "ECOGRAFÍA", "ECO RENAL Y DE VIAS URINARIAS"),       # página 2 sin filtrar
        ("22807206", "18/10/2026 11:05:10", "RADIOGRAFÍA", "TORAX PA Y LATERAL")]
    assert res[0]["fecha_texto"] == "19/10/2026" and res[1]["fecha_texto"] == ""                  # fecha del estudio en blanco
    assert res[0]["texto"].splitlines() == [
        "Con transductor convex de 3.5 Mhz se realiza barrido sonográfico observando:",
        "Riñón derecho de tamaño normal, sin dilatación de la vía urinaria.", "",
        "Riñón izquierdo con quiste cortical de 14 mm.", "OPINION: Quiste renal simple izquierdo."]


def test_grilla_de_formatos_con_pager_de_diez_en_diez(sis):
    with Simulador() as sim:
        s = sis(sim)
        _historia(s, 2)
        assert len(s._filas_formatos()) == 10 and s._fr().inner_text("body").count("Page 1 of 2 (18 items)") == 1
        assert [f["nombre"] for f in s._leer_todo(sistema.GRID_FORM, 5, s._filas_formatos)].count("INFORME DE IMAGENOLOGIA") == 2
        s._ir_pagina_formatos(1)
        assert len(s._filas_formatos()) == 8 and "Page 2 of 2 (18 items)" in s._fr().inner_text("body")
        # las pruebas de siempre siguen viendo la hoja y la orden (los formatos nuevos van al final de la lista)
        s._recargar_historia()
        assert s._ultimo_formato("HOJA DE EVOLUCION", ["FABIAN"])["fecha"] == "19/10/2026 07:20"


def test_filtrado_con_dos_paginas_y_tope_de_informes(sis):
    # BELTRAN OCHOA: 12 informes = 2 páginas incluso con el filtro; el tope se aplica a los más recientes
    with Simulador() as sim:
        s = sis(sim)
        _historia(s, 101)
        filas = s._filas_imagenologia()
        assert len(filas) == 12 and [f["pagina"] for f in filas] == [0] * 10 + [1] * 2
        s.MAX_IMAGENES = 3
        res = s._leer_imagenes()
        # el 12 y el 11 están en la página 2 del filtro y el 10 en la 1: se pasa de una a otra
        assert [r["texto"].splitlines()[0] for r in res] == ["Informe inventado 12.", "Informe inventado 11.",
                                                             "Informe inventado 10."]
        assert [r["fecha_texto"] for r in res] == ["18 DE OCTUBRE DEL 2026", "17 DE OCTUBRE DEL 2026", "16 DE OCTUBRE DEL 2026"]


def test_sin_informes_de_imagenologia_da_lista_vacia(sis):
    with Simulador() as sim:
        s = sis(sim)
        _historia(s, 3)                 # CORREA: solo una hoja de evolución
        assert s._leer_imagenes() == []
        assert s._filtro_img is None    # sin informes no se sabe aún qué filtro sirve: se prueban los dos cada vez


def test_un_error_en_un_informe_se_anota_y_se_sigue(sis):
    with Simulador() as sim:
        s = sis(sim)
        registro = []
        s.log = registro.append
        _historia(s, 1)
        real, llamadas = s._leer_formato, []

        def falla(**kw):
            llamadas.append(1)
            if len(llamadas) == 1:
                raise RuntimeError("se cayó la pestaña")
            return real(**kw)
        s._leer_formato = falla
        res = s._leer_imagenes()
    assert [r["numero"] for r in res] == ["22807104"]                  # el más reciente (22807105) falló; el otro se leyó
    fallos = [r for r in registro if "no pude" in r]
    assert len(fallos) == 1 and fallos[0].startswith("  no pude leer el informe de imagenología 22807105")
    assert "se cayó la pestaña" in fallos[0]


def test_datos_del_informe_segun_las_etiquetas_que_haya():
    leer = sistema.Sistema._datos_informe
    informe = "Engrosamiento cutáneo\nÁreas líquidas que se extienden al plano muscular"
    fecha, estudio = ("FECHA DE REALIZACION DEL ESTUDIO", "19 DE OCTUBRE DEL 2026"), ("ESTUDIO", "TEJIDOS BLANDOS")
    esperado = {"fecha_texto": "19 DE OCTUBRE DEL 2026", "tipo": "ECOGRAFÍA", "estudio": "TEJIDOS BLANDOS", "texto": informe}

    def examen(areas, extra=None):
        campos = {**dict(areas), "TIPO ESTUDIO": "ECOGRAFÍA", **(extra or {})}
        return {"EXAMEN": {**campos, "_texto": "\n".join(v for _, v in areas), "_areas": areas},
                "DESCRIPCION DEL EXAMEN": {"_texto": ""}}
    # a) la textarea del informe no tiene etiqueta: «CAMPO n»
    assert leer(examen([fecha, estudio, ("CAMPO 4", informe)])) == esperado
    # b) su "etiqueta" es el texto de otra celda (la tira de pestañas): la textarea más larga que no es fecha ni estudio
    assert leer(examen([fecha, estudio, ("EXAMEN DESCRIPCION DEL EXAMEN", informe)])) == esperado
    # c) con una textarea corta sin etiqueta y otra larga con etiqueta, gana la que no tiene etiqueta
    assert leer(examen([fecha, estudio, ("CAMPO 4", informe), ("OTRA COSA", informe + " y más texto")]))["texto"] == informe
    # d) sin la textarea del informe: texto vacío; el tipo es un combo (no cuenta como textarea)
    assert leer(examen([fecha, estudio])) == {**esperado, "texto": ""}
    # e) pestaña con otro nombre, o formato sin pestañas: se usa lo que haya
    assert leer({"EXAMEN RADIOLOGICO": examen([fecha, estudio, ("CAMPO 4", informe)])["EXAMEN"]}) == esperado
    assert leer({"FORMATO": examen([fecha, estudio, ("CAMPO 4", informe)])["EXAMEN"]}) == esperado
    assert leer({}) == {"fecha_texto": "", "tipo": "", "estudio": "", "texto": ""}


def test_detalle_lee_las_imagenes_del_paciente(sis):
    import notas
    if not hasattr(notas, "EstudioImagen"):
        pytest.skip("notas.EstudioImagen aún no existe")
    with Simulador() as sim:
        s = sis(sim)
        registro = []
        s.log = registro.append
        a = s.detalle(s.buscar("PEDRO ALVARADO", "1020304051", "CC", ["Hospitalización"]))
        assert a.encontrado_detalle and not a.aviso and a.dx == "1. COLECISTITIS AGUDA\n2. HTA"
        assert [(e.fecha, e.tipo, e.estudio, e.numero) for e in a.imagenes] == [
            ("19/10/26", "ECOGRAFÍA", "TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA", "22807105"),
            ("17/10/26", "TOMOGRAFÍA", "ABDOMEN SIMPLE", "22807104")]
        assert a.imagenes[0].texto.startswith("Engrosamiento cutáneo\nÁreas líquidas") and a.imagenes[1].texto.endswith("mínima cantidad.")
        # BENAVIDES: la fecha del estudio está en blanco en uno de los informes -> la «Fecha Hora» de la grilla
        b = s.detalle(s.buscar("SOFIA BENAVIDES LUNA", "1020304052", "CC", ["Hospitalización"]))
        assert [(e.fecha, e.numero) for e in b.imagenes] == [("19/10/26", "22807213"), ("18/10/26", "22807206")]
        # sin informes: lista vacía
        assert s.detalle(s.buscar("TOMAS CORREA MEJIA", "1020304053", "CC", ["Urgencias"])).imagenes == []
        assert not [r for r in registro if "no pude" in r]


def test_un_fallo_al_leer_las_imagenes_no_tumba_al_paciente(sis):
    with Simulador() as sim:
        s = sis(sim)
        registro = []
        s.log = registro.append

        def falla():
            raise RuntimeError("la grilla no responde")
        s._leer_imagenes = falla
        a = s.detalle(s.buscar("PEDRO ALVARADO", "1020304051", "CC", ["Hospitalización"]))
    assert a.encontrado_detalle and not a.aviso and a.dx == "1. COLECISTITIS AGUDA\n2. HTA"
    assert a.tratamiento.startswith("PLAN\n1. DIETA LIQUIDA") and not getattr(a, "imagenes", [])
    assert [r for r in registro if "no pude leer las imágenes" in r] == [
        "  PEDRO PABLO ALVARADO RUIZ: no pude leer las imágenes (la grilla no responde)"] \
        or any("no pude leer las imágenes" in r and "PEDRO PABLO ALVARADO RUIZ" in r for r in registro)


def test_el_simulador_sirve_los_documentos_de_entregas():
    import urllib.error
    import urllib.request

    import kardex_doc
    import notas

    def bajar(sim, n):
        with urllib.request.urlopen(sim.url_entregas(n), timeout=10) as r:
            return r.read().decode("utf-8")
    nombres = ["PISO 6", "URGENCIAS CARRERA 47", "PISO 4C (401-421)"]
    with Simulador(entregas_fallan=[2]) as sim:
        assert [e["nombre"] for e in sim.entregas] == nombres
        assert sim.entregas[0]["url"] == sim.url_entregas(1) == f"http://localhost:{sim.puerto}/entregas/1"
        for n in (2, 4, 0):                                                  # caído a propósito / no existe
            with pytest.raises(urllib.error.HTTPError) as e:
                bajar(sim, n)
            assert e.value.code == 404
        assert "PISO 6 ( 3 PACIENTES)" in bajar(sim, 1)
    with Simulador() as sim:
        docs = [bajar(sim, n) for n in (1, 2, 3)]
    # misma estructura que el kardex: título combinado, encabezado DATOS | DX | …, una fila por paciente y filas vacías
    assert "PENDIENTES" in docs[0] and "IMAGENES / NOTAS" in docs[0] and "PISO 4C ( 2 PACIENTES) 401 - 421" in docs[2]
    filas = kardex_doc.parsear_kardex_html(docs[0])
    assert [f.servicio for f in filas] == ["PISO 6"] * 3
    assert [f.datos.splitlines()[1:3] for f in filas] == [["PEDRO PABLO", "ALVARADO RUIZ"], ["PEDRO NEL", "SIERRA CANO"],
                                                           ["GLORIA INES", "HERRERA VARGAS"]]
    assert "VALORACION POR CIRUGIA GENERAL" in filas[0].evolucion and "VAL X CX GENERAL" in docs[0]
    assert [f.servicio for f in kardex_doc.parsear_kardex_html(docs[1])] == ["URGENCIAS 47"] * 2
    assert [f.servicio for f in kardex_doc.parsear_kardex_html(docs[2])] == ["PISO 4C"] * 2
    assert "A CARGO DE CIRUGIA GENERAL" in docs[1] and "SS VAL CX GENERAL" in docs[2]
    # con el lector de entregas y el detector de cirugía general: unos sí y otros no; ALVARADO y CORREA están en el
    # kardex simulado, SIERRA CANO y ROJAS DIAZ (Urgencias) solo en el sistema simulado
    if hasattr(kardex_doc, "parsear_entregas_html") and hasattr(notas, "menciona_cirugia"):
        todos = [e for d, nombre in zip(docs, nombres) for e in kardex_doc.parsear_entregas_html(d, nombre)]
        assert {e.nombre: notas.menciona_cirugia(e.texto) for e in todos} == {
            "PEDRO PABLO ALVARADO RUIZ": True, "PEDRO NEL SIERRA CANO": True, "GLORIA INES HERRERA VARGAS": False,
            "TOMAS CORREA MEJIA": False, "ELSA MARINA ROJAS DIAZ": True, "LAURA GUTIERREZ OSORIO": True,
            "HUMBERTO FORERO LEAL": False}


@pytest.fixture
def pagina():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        yield b.new_page()
        b.close()


def test_detecta_el_login_por_password_o_por_texto_ehc_con_entrar(pagina):
    def pide(html):
        pagina.set_content(html)
        return sistema.pagina_pide_login(pagina)
    assert pide('<input type="text" value="Usuario"><input type="password">')
    # sin campo password, pero con el texto de eHC y el botón ENTRAR (imagen, o con «entrar» en id/alt)
    pie = "<p>Software Asistencial eHC - Desarrollado por el Departamento de Sistemas</p>"
    assert pide(f'<input type="text">{pie}<input type="image" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="40" height="20">')
    assert pide(f'<input type="text">{pie}<div id="btnEntrar" style="width:40px;height:20px"></div>')
    assert pide(f'<input type="text">{pie}<a href="#"><img alt="ENTRAR" width="40" height="20"></a>')
    # el mismo pie en otra página (sin botón ENTRAR) no es un login; un password oculto tampoco
    assert not pide(f"<h2>DashBoard del Usuario</h2>{pie}")
    assert not pide('<input type="password" style="display:none"><p>hola</p>')
