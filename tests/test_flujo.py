"""flujo._analizar con objetos falsos (sin navegador): kardex + documentos de entregas + pacientes nuevos de las
entregas (AGREGAR). Todos los datos son inventados."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import flujo
import kardex_doc
import sistema
from comparar import PacienteSistema
from errores import Cancelado, ErrorApp
from notas import EstudioImagen

URL_KARDEX = "https://docs.google.com/document/d/KARDEX0000000000/edit"
URL_PISO6 = "https://docs.google.com/document/d/PISO60000000000/edit"
URL_PISO5 = "https://docs.google.com/document/d/PISO50000000000/edit?tab=t.0"
URL_URG47 = "https://docs.google.com/document/d/URGENCIAS47000/edit"


def _td(*lineas):
    return "<td>" + "".join(f"<p>{x}</p>" for x in lineas) + "</td>"


def _tabla(titulo, *filas):
    enc = "".join(f"<td>{c}</td>" for c in ("DATOS", "DX", "EVOLUCIÓN", "TRATAMIENTO", "LABORATORIOS",
                                           "IMÁGENES / NOTAS", "PENDIENTES"))
    return (f'<table><tr><td colspan="7"><p>{titulo}</p></td></tr><tr>{enc}</tr>'
            + "".join("<tr>" + "".join(_td(*c) for c in f) + "</tr>" for f in filas) + "</table>")


KARDEX = ("<html><body>"
          + _tabla("PISO 6 ( 1 PACIENTES)",
                   [("607", "ROSA ELENA PRADO LUNA", "59 AÑOS", "CC 1000234567"), ("COLECISTITIS",), ("viejo",),
                    ("PLAN", "DIETA LIQUIDA"), (), (), ()], [(), (), (), (), (), (), ()])
          + _tabla("PISO 5 (  PACIENTES)", [(), (), (), (), (), (), ()])
          + _tabla("URGENCIAS 47 ( 0 PACIENTES)", [(), (), (), (), (), (), ()])
          + "</body></html>")


def _entregas(titulo, *filas):
    """Documento de entregas: título combinado, encabezado DATOS | DX | PENDIENTES y una fila por paciente."""
    cuerpo = "".join("<tr>" + _td(*datos) + _td(dx) + _td(pend) + "</tr>" for datos, dx, pend in filas)
    return (f'<html><body><table><tr><td colspan="3"><p>{titulo}</p></td></tr>'
            f"<tr><td>DATOS</td><td>DX</td><td>PENDIENTES</td></tr>{cuerpo}</table></body></html>")


ENTREGAS_PISO6 = _entregas(
    "PISO 6 ( 3 PACIENTES)",
    (("607", "ROSA ELENA PRADO LUNA", "59 AÑOS", "CC 1000234567"), "COLECISTITIS", "VALORACION POR CIRUGIA"),
    (("610", "LUIS ANDRES SOTO", "52 AÑOS", "CC 1090000111"), "HERNIA", "CX GENERAL 16/10/26"),
    (("608", "MARTA OSORIO", "35 AÑOS", "CC 7000123"), "NEUMONIA", "val x cx plastica"))
ENTREGAS_URG47 = _entregas(
    "URGENCIAS 47 ( 1 PACIENTES)",
    (("CUB 12", "ELSA MORA", "44 AÑOS", "CC 12345678"), "DOLOR ABDOMINAL", "IC CX"))


class Pagina:
    url = "about:blank"

    def is_closed(self):
        return False

    def close(self):
        pass


class Ctx:
    def __init__(self):
        self.pages = []

    def new_page(self):
        pg = Pagina()
        self.pages.append(pg)
        return pg


class Nav:
    """Como NavegadorVivo: ejecutar(func, *args) llama func(contexto, *args)."""
    def __init__(self):
        self.ctx = Ctx()

    def ejecutar(self, func, *args):
        return func(self.ctx, *args)


# pacientes que «existen» en Hospital Office (documento -> PacienteSistema base)
def _sistema_falso():
    estudio = EstudioImagen("18/10/26", "ECOGRAFÍA", "ABDOMEN TOTAL", "Vesícula con litos y paredes engrosadas.", "1")
    return {
        "1000234567": PacienteSistema("PRADO LUNA ROSA ELENA", "6PISO-607", "Hospitalización", documento="1000234567",
                                      tipo_documento="CC"),
        "1090000111": PacienteSistema("SOTO ANDRES LUIS", "6PISO-610", "Hospitalización", documento="1090000111",
                                      tipo_documento="CC", imagenes=[estudio]),
    }


ELSA = PacienteSistema("MORA ELSA", "HOS47-12", "Urgencias", documento="12345678", tipo_documento="CC")


class SistemaFalso:
    """Reemplaza sistema.Sistema: sin navegador. Anota qué se le pidió."""
    MSG_LOGIN_MALO = "Usuario o contraseña de Hospital Office no válidos"
    existentes = {}
    buscados, detallados, diagnosticos = [], [], []
    falla_buscar = {}           # documento -> excepción que se lanza al buscarlo

    def __init__(self, contexto, cfg, log, carpeta_diag, credenciales=None, progreso=None, cancelado=None,
                 pagina=None):
        self.log = log

    def ir_agenda(self):
        pass

    def buscar(self, nombre, documento="", tipo="", modos=()):
        self.buscados.append((nombre, documento, tuple(modos)))
        if documento in self.falla_buscar:
            raise self.falla_buscar[documento]
        p = self.existentes.get(documento)
        if p is None:
            return None
        return PacienteSistema(**{**p.__dict__, "modo": modos[0] if p.modo not in modos else p.modo})

    def detalle(self, p):
        self.detallados.append((p.nombre, p.tratamiento, p.edad))
        p.dx = "1. COLECISTITIS AGUDA" if "PRADO" in p.nombre else "1. HERNIA INCISIONAL"
        p.evolucion = "19/10/2026 - DR. FABIAN (CIRUGIA GENERAL)\nBUENA EVOLUCION"
        p.tratamiento = p.tratamiento or "PLAN\nDIETA LIQUIDA"
        p.fecha, p.medico = "19/10/2026 06:40", "FABIAN"
        p.encontrado_detalle = True
        return p

    def diagnostico(self, etiqueta):
        self.diagnosticos.append(etiqueta)


@pytest.fixture
def entorno(monkeypatch):
    """Descarga de documentos y Hospital Office falsos. `docs` mapea cada URL a su HTML (o a una excepción)."""
    docs = {URL_KARDEX: KARDEX, URL_PISO6: ENTREGAS_PISO6, URL_URG47: ENTREGAS_URG47}
    descargados = []

    def descargar(ctx, url):
        descargados.append(url)
        r = docs[url]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(kardex_doc, "descargar_html", descargar)
    SistemaFalso.existentes = _sistema_falso()
    SistemaFalso.buscados, SistemaFalso.detallados, SistemaFalso.diagnosticos = [], [], []
    SistemaFalso.falla_buscar = {}
    monkeypatch.setattr(sistema, "Sistema", SistemaFalso)
    return type("Entorno", (), {"docs": docs, "descargados": descargados})()


def cfg(*entregas):
    return {"url_kardex": URL_KARDEX, "url_agenda": "http://agenda/", "especialistas": ["FABIAN"],
            "navegador": "chrome", "entregas": [{"nombre": n, "url": u} for n, u in entregas]}


def correr(config, cancelado=lambda: False):
    registro, avance = [], []
    res = flujo.analizar(Nav(), config, registro.append, lambda i, n, nombre: avance.append((i, n, nombre)), cancelado)
    return res, registro, avance


def tipos(acciones):
    return [(a.tipo, a.paciente, a.campo) for a in acciones]


# ------------------------------------------------------------------ kardex + entregas
def test_kardex_y_entregas_agrega_al_candidato_con_cirugia(entorno):
    (pacientes, kardex, acciones), registro, avance = correr(cfg(("PISO 6", URL_PISO6), ("URGENCIAS CARRERA 47", URL_URG47)))
    # solo se LEEN: el kardex y cada documento de entregas, en ese orden
    assert entorno.descargados == [URL_KARDEX, URL_PISO6, URL_URG47]
    # se busca a la del kardex y luego a los candidatos con cirugía que NO están en el kardex (LUIS y ELSA);
    # MARTA (cirugía plástica) no se busca; el modo preferido sale del nombre del documento de entregas
    assert SistemaFalso.buscados == [
        ("ROSA ELENA PRADO LUNA", "1000234567", ("Hospitalización", "Urgencias")),
        ("LUIS ANDRES SOTO", "1090000111", ("Hospitalización", "Urgencias")),
        ("ELSA MORA", "12345678", ("Urgencias", "Hospitalización"))]
    # el avance cuenta el kardex y los candidatos nuevos
    assert avance == [(1, 3, "ROSA ELENA PRADO LUNA"), (2, 3, "LUIS ANDRES SOTO"), (3, 3, "ELSA MORA")]
    assert len(kardex) == 1
    # ELSA no está en el sistema: solo queda en el registro; los demás sí
    assert [p.nombre for p in pacientes] == ["PRADO LUNA ROSA ELENA", "SOTO ANDRES LUIS"]
    assert registro.count("  no aparece en el sistema") == 1
    # los nuevos se detallan con tratamiento base vacío y la edad de la entrega
    assert SistemaFalso.detallados == [("PRADO LUNA ROSA ELENA", "PLAN\nDIETA LIQUIDA", ""),
                                       ("SOTO ANDRES LUIS", "", "52 AÑOS")]
    assert any(l.startswith("Entregas: 3 pacientes con valoración por cirugía general, 2 que no están en el kardex") for l in registro)
    assert "Sistema: 2 pacientes" in registro

    # ROSA (ya en el kardex): se actualiza como siempre y NO se agrega; LUIS: fila nueva en PISO 6
    agregar = [a for a in acciones if a.tipo == "AGREGAR"]
    assert [a.paciente for a in agregar] == ["LUIS ANDRES SOTO"]
    a = agregar[0]
    assert a.destino == "PISO 6" and a.tabla_destino == 0 and a.automatica and a.marcada
    assert a.sis is pacientes[1] and a.habitacion_nueva == "610"
    assert a.fila_nueva["DATOS"].splitlines() == ["610", "LUIS ANDRES SOTO", "52 AÑOS", "CC 1090000111"]
    assert a.fila_nueva["DX"] == "1. HERNIA INCISIONAL" and "ECOGRAFÍA ABDOMEN TOTAL 18/10/26" in a.fila_nueva["IMÁGENES / NOTAS"]
    assert ("ACTUALIZAR", "ROSA ELENA PRADO LUNA", "DX") in tipos(acciones)
    assert {a.tipo for a in acciones} == {"ACTUALIZAR", "AGREGAR"}      # nada por ELSA ni por MARTA


def test_candidato_de_urgencias_va_a_la_tabla_que_dice_el_documento_de_entregas(entorno):
    SistemaFalso.existentes["12345678"] = ELSA          # la habitación del sistema no dice el piso: decide el documento
    (pacientes, kardex, acciones), registro, avance = correr(cfg(("URGENCIAS CARRERA 47", URL_URG47)))
    (a,) = [a for a in acciones if a.tipo == "AGREGAR"]
    assert a.paciente == "ELSA MORA" and a.destino == "URGENCIAS 47" and a.tabla_destino == 2 and a.automatica
    assert a.fila_nueva["DATOS"].splitlines() == ["CUB 12", "ELSA MORA", "44 AÑOS", "CC 12345678"]
    assert SistemaFalso.buscados[-1] == ("ELSA MORA", "12345678", ("Urgencias", "Hospitalización"))
    assert [p.nombre for p in pacientes] == ["PRADO LUNA ROSA ELENA", "MORA ELSA"]


def test_sin_entregas_configuradas_solo_lee_el_kardex(entorno):
    config = cfg()
    del config["entregas"]               # configuración antigua: sin la clave
    (pacientes, kardex, acciones), registro, avance = correr(config)
    assert entorno.descargados == [URL_KARDEX]
    assert [p.nombre for p in pacientes] == ["PRADO LUNA ROSA ELENA"] and avance == [(1, 1, "ROSA ELENA PRADO LUNA")]
    assert not any(a.tipo == "AGREGAR" for a in acciones)
    assert not any(l.startswith("Entregas:") for l in registro)


def test_candidato_sin_cirugia_general_no_se_busca_ni_se_agrega(entorno):
    entorno.docs[URL_PISO6] = _entregas(
        "PISO 6 ( 3 PACIENTES)",
        (("608", "MARTA OSORIO", "35 AÑOS", "CC 7000123"), "NEUMONIA", "val x cx plastica"),
        (("609", "JOSE LUIS RIOS", "70 AÑOS", "CC 8000999"), "EPOC", "PRE QX"),
        (("610", "LUIS ANDRES SOTO", "52 AÑOS", "CC 1090000111"), "HERNIA", "PENDIENTE ECOGRAFIA"))
    (pacientes, kardex, acciones), registro, avance = correr(cfg(("PISO 6", URL_PISO6)))
    assert [b[0] for b in SistemaFalso.buscados] == ["ROSA ELENA PRADO LUNA"]       # solo la del kardex
    assert avance == [(1, 1, "ROSA ELENA PRADO LUNA")]
    assert not any(a.tipo == "AGREGAR" for a in acciones) and len(pacientes) == 1


def test_candidato_que_no_aparece_en_el_sistema_solo_queda_en_el_registro(entorno):
    entorno.docs[URL_PISO6] = ENTREGAS_PISO6.replace("1090000111", "1090009999")        # LUIS no existe en el sistema
    (pacientes, kardex, acciones), registro, avance = correr(cfg(("PISO 6", URL_PISO6)))
    assert [b[0] for b in SistemaFalso.buscados] == ["ROSA ELENA PRADO LUNA", "LUIS ANDRES SOTO"]
    assert avance[-1] == (2, 2, "LUIS ANDRES SOTO")
    assert registro.count("  no aparece en el sistema") == 1
    assert not any(a.tipo in ("AGREGAR", "REVISAR") for a in acciones) and len(pacientes) == 1


def test_candidato_ya_en_el_kardex_no_se_busca_dos_veces(entorno):
    # ROSA está en el kardex y en las entregas con cirugía: se actualiza con su fila, sin AGREGAR ni segunda búsqueda
    entorno.docs[URL_PISO6] = _entregas(
        "PISO 6 ( 1 PACIENTES)", (("607", "PRADO LUNA ROSA ELENA", "59 AÑOS", "CC 1000234567"), "COLECISTITIS", "VAL X CX"))
    (pacientes, kardex, acciones), registro, avance = correr(cfg(("PISO 6", URL_PISO6)))
    assert [b[0] for b in SistemaFalso.buscados] == ["ROSA ELENA PRADO LUNA"] and avance == [(1, 1, "ROSA ELENA PRADO LUNA")]
    assert not any(a.tipo == "AGREGAR" for a in acciones)


# ------------------------------------------------------------------ documentos de entregas que fallan
def test_documento_de_entregas_que_falla_da_revisar_y_se_sigue(entorno):
    entorno.docs[URL_PISO5] = ErrorApp("kardex", "No se pudo leer el Google Doc (respuesta 404). Revisa el enlace del KARDEX.")
    entorno.docs[URL_URG47] = RuntimeError("se cayó la red\nsegundo renglón")
    (pacientes, kardex, acciones), registro, avance = correr(
        cfg(("PISO 5", URL_PISO5), ("PISO 6", URL_PISO6), ("URGENCIAS CARRERA 47", URL_URG47)))
    revisar = [a for a in acciones if a.tipo == "REVISAR"]
    assert [(a.paciente, a.detalle) for a in revisar] == [
        ("PISO 5", "No pude leer el documento de entregas PISO 5: No se pudo leer el Google Doc (respuesta 404)"),
        ("URGENCIAS CARRERA 47", "No pude leer el documento de entregas URGENCIAS CARRERA 47: se cayó la red")]
    assert all(not a.marcada and not a.automatica and a.fila is None and a.sis is None for a in revisar)
    assert "  No pude leer las entregas PISO 5: No se pudo leer el Google Doc (respuesta 404)" in registro
    # el documento bueno sí se usó: LUIS se agregó
    assert [a.paciente for a in acciones if a.tipo == "AGREGAR"] == ["LUIS ANDRES SOTO"]
    assert entorno.descargados == [URL_KARDEX, URL_PISO5, URL_PISO6, URL_URG47]


def test_error_de_sesion_de_google_en_las_entregas_corta_el_analisis(entorno):
    entorno.docs[URL_PISO6] = ErrorApp("sesion", "Google pide iniciar sesión.")
    with pytest.raises(ErrorApp) as e:
        correr(cfg(("PISO 6", URL_PISO6), ("URGENCIAS CARRERA 47", URL_URG47)))
    assert e.value.codigo == "sesion"
    assert entorno.descargados == [URL_KARDEX, URL_PISO6]          # no siguió con los demás
    assert SistemaFalso.buscados == []


def test_kardex_sin_tablas_sigue_siendo_error(entorno):
    entorno.docs[URL_KARDEX] = "<html><body><p>nada</p></body></html>"
    with pytest.raises(ErrorApp) as e:
        correr(cfg(("PISO 6", URL_PISO6)))
    assert e.value.codigo == "kardex" and entorno.descargados == [URL_KARDEX]


def test_entradas_de_entregas_mal_formadas_se_ignoran(entorno):
    config = cfg(("PISO 6", URL_PISO6))
    config["entregas"] += ["texto", {"nombre": "SIN URL"}, {"nombre": "", "url": URL_URG47}, {"nombre": 5, "url": "x"}, None]
    correr(config)
    assert entorno.descargados == [URL_KARDEX, URL_PISO6]


# ------------------------------------------------------------------ errores al buscar y cancelación
def test_error_al_buscar_a_un_candidato_da_revisar_con_su_nombre(entorno):
    SistemaFalso.falla_buscar = {"1090000111": RuntimeError("la grilla no responde")}
    (pacientes, kardex, acciones), registro, avance = correr(cfg(("PISO 6", URL_PISO6)))
    r = [a for a in acciones if a.tipo == "REVISAR"]
    assert [a.paciente for a in r] == ["LUIS ANDRES SOTO"] and not r[0].marcada and not r[0].automatica
    assert "no pude buscarlo en el sistema: la grilla no responde" in r[0].detalle and "PISO 6" in r[0].detalle
    assert SistemaFalso.diagnosticos == ["buscar"]
    assert not any(a.tipo == "AGREGAR" for a in acciones)
    assert [p.nombre for p in pacientes] == ["PRADO LUNA ROSA ELENA"]          # lo del kardex siguió normal


def test_error_de_sesion_al_buscar_a_un_candidato_corta(entorno):
    SistemaFalso.falla_buscar = {"1090000111": ErrorApp("sesion", "Hospital Office pide iniciar sesión.")}
    with pytest.raises(ErrorApp) as e:
        correr(cfg(("PISO 6", URL_PISO6)))
    assert e.value.codigo == "sesion"


def test_cancelar_durante_los_candidatos(entorno):
    llamadas = []

    def cancelado():
        llamadas.append(1)
        return len(llamadas) > 2            # 1.ª: el documento de entregas; 2.ª: la del kardex; 3.ª: el candidato nuevo
    with pytest.raises(Cancelado):
        correr(cfg(("PISO 6", URL_PISO6)), cancelado)
    assert [b[0] for b in SistemaFalso.buscados] == ["ROSA ELENA PRADO LUNA"]


def test_la_clave_mala_borra_el_usuario_guardado(entorno, monkeypatch):
    flujo.hospital_guardar("medico.prueba", "Clave-Inventada-1")

    class Malo(SistemaFalso):
        def ir_agenda(self):
            raise ErrorApp("sesion", SistemaFalso.MSG_LOGIN_MALO)
    monkeypatch.setattr(sistema, "Sistema", Malo)
    with pytest.raises(ErrorApp) as e:
        correr(cfg())
    assert "Borré el usuario guardado" in e.value.mensaje and flujo.hospital_credenciales() is None


# ------------------------------------------------------------------ configuración
def test_config_base_trae_los_11_documentos_de_entregas():
    docs = flujo.CONFIG_BASE["entregas"]
    assert [d["nombre"] for d in docs] == [
        "PISO 3 GINECO", "PISO 4C (401-421)", "PISO 4A (422-430)", "PISO 4B (430 EN ADELANTE)", "PISO 5", "PISO 6",
        "PISOS 10 Y 11", "URGENCIAS CARRERA 47", "URGENCIAS CALLE 82", "UCI 1", "UCI 7"]
    for d in docs:
        assert set(d) == {"nombre", "url"} and d["url"].startswith("https://docs.google.com/document/d/")
        assert kardex_doc.id_documento(d["url"]) and len(kardex_doc.id_documento(d["url"])) > 20
    assert kardex_doc._pestana(docs[4]["url"]) == "t.0" and kardex_doc._pestana(docs[0]["url"]) == ""


def test_cargar_config_entregas(datos_temporales):
    assert flujo.cargar_config()["entregas"] == flujo.CONFIG_BASE["entregas"]
    flujo.cargar_config()["entregas"].append({"nombre": "X", "url": "y"})          # no contamina la configuración base
    assert len(flujo.CONFIG_BASE["entregas"]) == 11
    # config.json de una versión anterior (sin entregas): quedan las de fábrica
    (datos_temporales / "config.json").write_text('{"navegador": "brave"}', encoding="utf-8")
    c = flujo.cargar_config()
    assert c["navegador"] == "brave" and len(c["entregas"]) == 11
    # guardadas por la persona
    c["entregas"] = [{"nombre": "PISO 6", "url": URL_PISO6}]
    flujo.guardar_config(c)
    assert flujo.cargar_config()["entregas"] == [{"nombre": "PISO 6", "url": URL_PISO6}]
    (datos_temporales / "config.json").write_text('{"entregas": "mal"}', encoding="utf-8")      # forma inválida: de fábrica
    assert len(flujo.cargar_config()["entregas"]) == 11
