"""Ejecuta flujo.analizar de verdad (Playwright + Chromium sin ventana) contra el simulador de
Hospital Office y del kardex (tests/simulador). Se salta si no hay playwright o Chromium."""
import time

import pytest

import flujo
import sistema
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
            pg.click("input[type=text]")
            pg.keyboard.press("Control+A")
            pg.keyboard.type(USUARIO)
            pg.fill("input[type=password]", CLAVE)
            pg.click("input[type=image]")
        return False
    registro, avance, esperas = [], [], []
    with Simulador() as sim:
        (pacientes, _, _) = flujo.analizar(
            _cfg(sim), registro.append, lambda i, n, nombre: (esperas if i == 0 else avance).append((i, n, nombre)),
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
