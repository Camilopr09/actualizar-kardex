"""Documentos de ENTREGAS (solo lectura), pacientes con valoración por cirugía general, tablas del kardex,
habitación -> servicio destino y las acciones nuevas de comparar() (MOVER, HABITACIÓN, IMÁGENES, AGREGAR).
Todos los datos son inventados."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from comparar import (Accion, FilaKardex, PacienteEntrega, PacienteSistema, TablaKardex, buscar_paciente,
                      candidatos_cirugia, codigo_kardex, comparar, servicio_destino)
from kardex_doc import parsear_entregas_html, parsear_kardex_html, tablas_kardex
from notas import EstudioImagen, bloque_imagen, menciona_cirugia, unir_bloques


# ------------------------------------------------------------------ menciona_cirugia
@pytest.mark.parametrize("texto", [
    "VALORACION POR CIRUGIA", "val x cx", "Pendiente valoración por Cirugía General", "CX GENERAL 16/10/26 sin hallazgos",
    "SS CX", "S/S CIRUGIA", "IC CIRUGIA GRAL", "interconsulta a cirugía", "SGTO POR CX", "seguimiento cirugía",
    "A CARGO DE CIRUGIA", "CARGO DE CX", "VALORADO POR CIRUGIA ayer", "paciente x CX", "POR CIRUGIA",
    "VALORACIÓN CIRUGÍA GENERAL: DESCARTA ABDOMEN AGUDO", "Cx. General", "IC. CX", "VAL: CX", "CX GRAL",
    "VALORADA POR CX, REQUIERE LAPAROTOMIA", "SS A CIRUGIA", "VALORACION POR CIRUGIA PLASTICA Y CIRUGIA GENERAL",
    "SGTO POR CIRUGIA VASCULAR Y POR CX", "DX: COLECISTITIS\nVAL X CX\nPLAN", "VALORACION   POR\nCIRUGIA"])
def test_menciona_cirugia_si(texto):
    assert menciona_cirugia(texto), texto


@pytest.mark.parametrize("texto", [
    "VALORACION POR CIRUGIA PLASTICA", "VAL X CX VASCULAR", "SS CIRUGIA DE TORAX", "IC CX TORACICA",
    "SGTO POR CIRUGIA PEDIATRICA", "VAL POR CX DE MANO", "VALORACION POR CIRUGIA MAXILOFACIAL", "SS CIRUGIA CARDIOVASCULAR",
    "VALORACION POR NEUROCIRUGIA", "SS NEUROCX", "PRE QX", "PREQUIRURGICO", "VALORACION PRE QX",
    "QUIRURGICOS: APENDICECTOMIA 2010, CX POR HERNIA UMBILICAL", "ANTECEDENTES: COLECISTECTOMIA, CX DE RODILLA",
    "CX PREVIA", "CIRUGIA PROGRAMADA PARA MAÑANA", "pendiente cx", "VALORACION POR ORTOPEDIA", "VAL POR MED INTERNA",
    "ANTECEDENTE DE CIRUGIA", "", None])
def test_menciona_cirugia_no(texto):
    assert not menciona_cirugia(texto), texto


# ------------------------------------------------------------------ documentos de entregas
def _td(*lineas):
    return "<td>" + "".join(f"<p>{l}</p>" for l in lineas) + "</td>"


ENTREGAS = ("<html><body><p>ENTREGAS PISO 6</p>"
            '<table><tr><td colspan="4"><p>PISO 6 (3 PACIENTES)</p></td></tr>'
            "<tr><td>DATOS</td><td>DX</td><td>PENDIENTES</td><td>OBS</td></tr>"
            "<tr>" + _td("607", "ROSA ELENA PRADO LUNA", "59 AÑOS", "CC 1000234567") + _td("COLECISTITIS") + _td("VALORACION POR CIRUGIA")
            + _td("") + "</tr>"
            "<tr>" + _td("608", "MARTA OSORIO", "35 AÑOS", "CC 7000123") + _td("NEUMONIA") + _td("val x cx plastica") + _td("") + "</tr>"
            "<tr>" + _td("", "", "") + _td("") + _td("") + _td("") + "</tr>"
            "<tr>" + _td("610", "LUIS ANDRES SOTO", "TI 1090000111") + _td("HERNIA") + _td("CX GENERAL 16/10/26") + _td("") + "</tr>"
            "</table></body></html>")


def test_parsear_entregas():
    e = parsear_entregas_html(ENTREGAS, "PISO 6")
    assert [x.nombre for x in e] == ["ROSA ELENA PRADO LUNA", "MARTA OSORIO", "LUIS ANDRES SOTO"]
    a = e[0]
    assert (a.documento, a.tipo_documento, a.edad, a.habitacion, a.doc, a.servicio) == (
        "1000234567", "CC", "59 AÑOS", "607", "PISO 6", "PISO 6")
    assert a.datos == "607\nROSA ELENA PRADO LUNA\n59 AÑOS\nCC 1000234567"
    assert "VALORACION POR CIRUGIA" in a.texto and "COLECISTITIS" in a.texto
    assert (e[2].tipo_documento, e[2].documento) == ("TI", "1090000111")
    assert [x.nombre for x in candidatos_cirugia(e)] == ["ROSA ELENA PRADO LUNA", "LUIS ANDRES SOTO"]   # MARTA: plástica


def test_parsear_entregas_tolerante_sin_encabezado_ni_titulo():
    html = ("<html><body><h2>URGENCIAS CARRERA 47</h2><table>"
            "<tr>" + _td("CUB 12", "ELSA MORA", "CC 12345678") + _td("DOLOR ABDOMINAL") + _td("IC CX") + "</tr>"
            "<tr>" + _td("PASILLO") + _td("sin nombre") + "</tr>"
            "</table><table><tr><td>PISO 3 (1 PACIENTES)</td></tr>"
            "<tr>" + _td("305", "ANA MARIA VILLARREAL") + _td("x") + "</tr></table></body></html>")
    e = parsear_entregas_html(html, "URGENCIAS CARRERA 47")
    assert [(x.nombre, x.habitacion, x.documento, x.servicio) for x in e] == [
        ("ELSA MORA", "CUB 12", "12345678", "URGENCIAS CARRERA 47"), ("ANA MARIA VILLARREAL", "305", "", "PISO 3")]
    assert menciona_cirugia(e[0].texto) and not menciona_cirugia(e[1].texto)
    assert parsear_entregas_html("<html><body><p>nada</p></body></html>", "X") == []


def test_candidatos_sin_repetidos():
    mk = lambda nombre, doc, texto: PacienteEntrega(nombre, doc, texto=texto)
    e = [mk("ANA RUIZ PEREZ", "123", "VAL X CX"), mk("ANA RUIZ PEREZ", "123", "SS CIRUGIA"), mk("OTRA PERSONA UNO", "123", "IC CX"),
         mk("JUAN PEREZ GOMEZ", "", "CX GENERAL"), mk("juan perez gomez", "", "CX GRAL"), mk("NO VA ASI", "9", "VAL X NEURO")]
    assert [x.nombre for x in candidatos_cirugia(e)] == ["ANA RUIZ PEREZ", "JUAN PEREZ GOMEZ"]


def test_buscar_paciente_sirve_con_entregas():
    e = [PacienteEntrega("ROSA ELENA PRADO LUNA", "1000234567"), PacienteEntrega("MARTA OSORIO", "7000123")]
    assert buscar_paciente("PRADO LUNA ROSA ELENA", "", e) is e[0] and buscar_paciente("X Y", "7000123", e) is e[1]


# ------------------------------------------------------------------ tablas del kardex
def _tabla_html(titulo, n=7):
    return f'<table><tr><td colspan="{n}"><p>{titulo}</p></td></tr><tr><td>DATOS</td><td>DX</td></tr><tr>' \
           + _td("A B") + _td("x") + "</tr><tr><td></td><td></td></tr></table>"


def test_tablas_kardex_servicio_titulo_rango_y_pacientes():
    html = ("<html><body><p>KARDEX</p>" + _tabla_html("PISO 4A ( 4 PACIENTES) 422 - 430") + "<table><tr><td>otra</td></tr></table>"
            + _tabla_html("PISO 4B ( 3 PACIENTES) 430 EN ADELANTE") + _tabla_html("PISO 4C ( 6 PACIENTES) 401 - 421")
            + _tabla_html("PISO 5 (  PACIENTES)") + _tabla_html("UCI 1  (2 PACIENTES)") + "</body></html>")
    t = tablas_kardex(html)
    assert [(x.indice, x.servicio, x.rango, x.filas_pacientes) for x in t] == [
        (0, "PISO 4A", (422, 430), 1), (2, "PISO 4B", (430, None), 1), (3, "PISO 4C", (401, 421), 1),
        (4, "PISO 5", None, 1), (5, "UCI 1", None, 1)]
    assert t[0].titulo == "PISO 4A ( 4 PACIENTES) 422 - 430" and isinstance(t[0], TablaKardex)
    # los índices son los mismos de FilaKardex.tabla
    assert [f.tabla for f in parsear_kardex_html(html)] == [x.indice for x in t]
    assert tablas_kardex("<p>sin tablas</p>") == []


def test_tabla_sin_pacientes_tambien_se_incluye():
    html = '<table><tr><td colspan="2">PISO 11 (  PACIENTES)</td></tr><tr><td>DATOS</td><td>DX</td></tr><tr><td></td><td></td></tr></table>'
    (t,) = tablas_kardex(html)
    assert (t.servicio, t.filas_pacientes) == ("PISO 11", 0) and parsear_kardex_html(html) == []


# ------------------------------------------------------------------ habitación -> tabla
def test_codigo_kardex():
    for hab, cod in (("6PISO-607", "607"), ("3PISO-305B", "305B"), ("10PISO-1001A", "1001A"), ("4PISO-430", "430"),
                     ("607", "607"), ("6 PISO - 607", "607"), ("6piso-607", "607")):
        assert codigo_kardex(hab) == cod, hab
    for hab in ("HOS82-09", "UCI5-09", "H4CAM-09", "PEDIA-07", "PASILLO", "", None, "6PISO-PASILLO", "9", "CUB 12", "U-03"):
        assert codigo_kardex(hab) == "", hab


TABLAS = [TablaKardex(0, "PISO 4A", rango=(422, 430)), TablaKardex(1, "PISO 4B", rango=(430, None)),
          TablaKardex(2, "PISO 4C", rango=(401, 421)), TablaKardex(3, "PISO 5"), TablaKardex(4, "UCI 5"),
          TablaKardex(5, "PISO 6"), TablaKardex(6, "PISO 10"), TablaKardex(7, "PISO 11"), TablaKardex(8, "URGENCIAS 47"),
          TablaKardex(9, "URGENCIAS 82"), TablaKardex(10, "UCI 1"), TablaKardex(11, "PISO 3")]


def _d(hab, doc=""):
    t = servicio_destino(hab, TABLAS, doc)
    return t.servicio if t else None


def test_servicio_destino_por_habitacion():
    assert _d("6PISO-607") == "PISO 6" and _d("3PISO-305B") == "PISO 3" and _d("5PISO-512") == "PISO 5"
    assert _d("10PISO-1001A") == "PISO 10" and _d("11PISO-1105") == "PISO 11"
    # piso 4: varias tablas, la del rango
    assert _d("4PISO-425") == "PISO 4A" and _d("4PISO-410") == "PISO 4C" and _d("4PISO-440") == "PISO 4B"
    assert _d("4PISO-430") == "PISO 4A"                     # lo contienen 4A y 4B: la primera
    assert _d("4PISO-421") == "PISO 4C" and _d("4PISO-401") == "PISO 4C"
    assert _d("4PISO-300") == "PISO 3"                      # el piso sale del número (300 // 100), no del prefijo
    assert _d("4PISO-100") is None                          # no hay tabla del piso 1
    tablas4 = [TablaKardex(0, "PISO 4A", rango=(422, 430)), TablaKardex(1, "PISO 4C", rango=(401, 421))]
    assert servicio_destino("4PISO-450", tablas4) is None            # ninguna contiene 450: ambiguo
    assert servicio_destino("4PISO-410", [TablaKardex(0, "PISO 4A")]).servicio == "PISO 4A"     # una sola candidata


def test_servicio_destino_por_documento_de_entregas():
    assert _d("HOS82-09", "URGENCIAS CARRERA 47") == "URGENCIAS 47" and _d("HOS82-09", "URGENCIAS CALLE 82") == "URGENCIAS 82"
    assert _d("UCI5-09", "UCI 1") == "UCI 1" and _d("UCI7-02", "PISO 5") == "PISO 5"
    assert _d("PASILLO", "PISO 4C (401-421)") == "PISO 4C" and _d("", "PISO 4B (430 EN ADELANTE)") == "PISO 4B"
    assert _d("", "PISO 3 GINECO") == "PISO 3" and _d("", "PISO 6") == "PISO 6"
    assert _d("UCI5-09", "PISOS 10 Y 11") is None                    # coinciden dos tablas
    assert _d("UCI5-09", "") is None and _d("", "OTRO DOCUMENTO") is None
    assert _d("PASILLO") is None
    # con número y sin tabla de ese piso se prueba con el documento
    assert _d("8PISO-801", "PISO 5") == "PISO 5" and _d("8PISO-801") is None


# ------------------------------------------------------------------ comparar: MOVER / HABITACIÓN / REVISAR
def _fila(nombre="ROSA ELENA PRADO LUNA", hab="425", servicio="PISO 4A", tabla=0, **kw):
    return FilaKardex(tabla=tabla, fila=2, servicio=servicio, datos=f"{hab}\n{nombre}\n59 AÑOS\nCC 1000234567", **kw)


def _sis(hab, **kw):
    base = dict(nombre="PRADO LUNA ROSA ELENA", habitacion=hab, modo="Hospitalización", encontrado_detalle=True,
                documento="1000234567")
    base.update(kw)
    return PacienteSistema(**base)


def test_cambio_de_piso_genera_mover():
    (a,) = comparar([_sis("6PISO-607")], [_fila()], tablas=TABLAS)
    assert a.tipo == "MOVER" and a.automatica and a.marcada
    assert (a.destino, a.tabla_destino, a.habitacion_nueva) == ("PISO 6", 5, "607")
    assert (a.servicio, a.habitacion) == ("PISO 4A", "425") and a.fila.nombre == "ROSA ELENA PRADO LUNA"
    assert a.detalle == "Cambió de piso: estaba en PISO 4A, el sistema dice 6PISO-607 → va a PISO 6"
    assert "PISO 4A" in a.actual and "PISO 6" in a.nuevo and "607" in a.nuevo


def test_mover_junto_con_las_demas_actualizaciones():
    p = _sis("6PISO-607", dx="1. HTA", fecha="19/10/2026 06:30", medico="DAZA")
    acc = comparar([p], [_fila(dx="viejo")], tablas=TABLAS)
    assert [(a.tipo, a.campo) for a in acc] == [("MOVER", "HABITACIÓN"), ("ACTUALIZAR", "DX")]
    assert acc[1].fila is acc[0].fila


def test_misma_tabla_otra_habitacion_actualiza_solo_la_habitacion():
    (a,) = comparar([_sis("4PISO-427")], [_fila()], tablas=TABLAS)
    assert (a.tipo, a.campo, a.actual, a.nuevo, a.habitacion_nueva) == ("ACTUALIZAR", "HABITACIÓN", "425", "427", "427")
    assert a.automatica and a.tabla_destino is None and a.destino == ""
    # 4A (422-430) y 4C (401-421) son tablas distintas: de 425 a 410 se mueve
    (m,) = comparar([_sis("4PISO-410")], [_fila()], tablas=TABLAS)
    assert (m.tipo, m.destino, m.tabla_destino) == ("MOVER", "PISO 4C", 2)


def test_habitacion_igual_o_sin_datos_no_hace_nada():
    assert comparar([_sis("4PISO-425")], [_fila()], tablas=TABLAS) == []
    assert comparar([_sis("6PISO-607")], [_fila(hab="PASILLO", servicio="PISO 6", tabla=5)], tablas=TABLAS) == []
    assert comparar([_sis("")], [_fila()], tablas=TABLAS) == []


def test_sin_numero_en_el_kardex_pero_otro_piso_en_el_sistema_se_mueve():
    (a,) = comparar([_sis("6PISO-607")], [_fila(hab="PASILLO")], tablas=TABLAS)
    assert (a.tipo, a.destino, a.habitacion_nueva, a.habitacion) == ("MOVER", "PISO 6", "607", "PASILLO")
    (b,) = comparar([_sis("6PISO-607")], [_fila(hab="")], tablas=TABLAS)
    assert (b.tipo, b.destino) == ("MOVER", "PISO 6")
    assert comparar([_sis("UCI5-09")], [_fila(hab="PASILLO")], tablas=TABLAS) == []    # sin código de piso: nada


def test_sin_tablas_o_destino_ambiguo_queda_en_revisar():
    (r,) = comparar([_sis("6PISO-607")], [_fila()])                              # sin tablas: como antes
    assert (r.tipo, r.campo, r.actual, r.nuevo, r.marcada, r.automatica) == ("REVISAR", "HABITACIÓN", "425", "6PISO-607", False, False)
    (r2,) = comparar([_sis("8PISO-801")], [_fila()], tablas=TABLAS)              # no hay tabla del piso 8
    assert r2.tipo == "REVISAR" and not r2.automatica
    (r3,) = comparar([_sis("UCI5-09")], [_fila(hab="UCI5-02")], tablas=TABLAS)   # no es código de piso
    assert (r3.tipo, r3.actual, r3.nuevo) == ("REVISAR", "UCI5-02", "UCI5-09")


def test_el_documento_de_entregas_ayuda_a_decidir():
    # código de piso sin tabla de ese piso, pero el paciente está en el documento de entregas «PISO 5»
    ent = [PacienteEntrega("ROSA ELENA PRADO LUNA", "1000234567", doc="PISO 5")]
    (a,) = comparar([_sis("8PISO-801")], [_fila()], tablas=TABLAS, entregas=ent)
    assert (a.tipo, a.destino) == ("MOVER", "PISO 5")


# ------------------------------------------------------------------ comparar: IMÁGENES
E1 = EstudioImagen("19/10/26", "ECOGRAFÍA", "TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA", "Engrosamiento cutáneo\nÁreas líquidas", "9")
E2 = EstudioImagen("16/10/26", "TAC", "TAC DE ABDOMEN SIMPLE", "CONCLUSIÓN: sin hallazgos", "8")


def test_imagenes_nuevas_se_insertan_arriba():
    f = _fila(imagenes="TAC DE ABDOMEN SIMPLE 16/10/26\nCONCLUSIÓN: sin hallazgos\nnota a mano", col_imagenes=5)
    acc = comparar([_sis("4PISO-425", imagenes=[E1, E2])], [f])
    (a,) = acc
    assert (a.tipo, a.campo, a.automatica, a.marcada) == ("ACTUALIZAR", "IMÁGENES / NOTAS", True, True)
    assert a.insertar == bloque_imagen(E1) and a.actual == f.imagenes          # E2 ya estaba
    assert a.nuevo == bloque_imagen(E1) + "\n\n" + f.imagenes and a.detalle == "1 estudio(s) nuevo(s) de imágenes"
    # los dos nuevos, el más reciente arriba
    (b,) = comparar([_sis("4PISO-425", imagenes=[E2, E1])], [_fila(imagenes="", col_imagenes=5)])
    assert b.insertar == unir_bloques([E1, E2]) and b.nuevo == b.insertar and b.detalle == "2 estudio(s) nuevo(s) de imágenes"


def test_imagenes_bajo_el_subtitulo_y_sin_columna():
    f = _fila(imagenes="IMÁGENES\nTAC DE ABDOMEN SIMPLE 16/10/26\nx", col_imagenes=5)
    (a,) = comparar([_sis("4PISO-425", imagenes=[E1, E2])], [f])
    assert a.nuevo == "IMÁGENES\n" + bloque_imagen(E1) + "\n\nTAC DE ABDOMEN SIMPLE 16/10/26\nx"
    assert comparar([_sis("4PISO-425", imagenes=[E1])], [_fila(col_imagenes=None)]) == []        # la tabla no tiene la columna
    assert comparar([_sis("4PISO-425", imagenes=[E1], encontrado_detalle=False)], [_fila(col_imagenes=5)]) == []
    assert comparar([_sis("4PISO-425", imagenes=[E1])], [_fila(imagenes=unir_bloques([E1]), col_imagenes=5)]) == []


# ------------------------------------------------------------------ comparar: AGREGAR
def _nuevo(hab="6PISO-610", **kw):
    p = _sis(hab, nombre="TORRES RUIZ JOSE MIGUEL", documento="1020304050", dx="1. COLECISTITIS AGUDA",
             evolucion="19/10/2026 - DR. DAZA (CX GENERAL)\nESTABLE", tratamiento="PLAN\n1. DIETA ZERO",
             imagenes=[E2, E1], edad="44 AÑOS", **kw)
    e = PacienteEntrega("Jose Miguel Torres Ruiz", "1020304050", "CC", "44 AÑOS", "610", doc="PISO 6", servicio="PISO 6")
    return p, e


def test_agregar_a_la_tabla_segun_la_habitacion():
    (a,) = comparar([], [], nuevos=[_nuevo()], tablas=TABLAS)
    assert (a.tipo, a.marcada, a.automatica, a.destino, a.tabla_destino, a.servicio) == ("AGREGAR", True, True, "PISO 6", 5, "PISO 6")
    assert a.paciente == "JOSE MIGUEL TORRES RUIZ" and a.fila is None and a.sis.nombre == "TORRES RUIZ JOSE MIGUEL"
    assert a.fila_nueva == {"DATOS": "610\nJOSE MIGUEL TORRES RUIZ\n44 AÑOS\nCC 1020304050",
                            "DX": "1. COLECISTITIS AGUDA", "EVOLUCIÓN": "19/10/2026 - DR. DAZA (CX GENERAL)\nESTABLE",
                            "TRATAMIENTO": "PLAN\n1. DIETA ZERO", "IMÁGENES / NOTAS": unir_bloques([E1, E2])}
    assert a.habitacion == "610" and a.habitacion_nueva == "610"
    assert a.nuevo.startswith("DATOS\n610\nJOSE MIGUEL TORRES RUIZ") and "IMÁGENES / NOTAS\n" in a.nuevo and "PISO 6" in a.detalle


def test_agregar_urgencias_por_el_documento_de_entregas():
    p = _sis("HOS82-09", nombre="MORA ELSA", documento="12345678", edad="", dx="DOLOR ABDOMINAL")
    e = PacienteEntrega("ELSA MORA", "12345678", "CC", "62 AÑOS", "CUB 9", doc="URGENCIAS CALLE 82")
    (a,) = comparar([], [], nuevos=[(p, e)], tablas=TABLAS)
    assert (a.destino, a.tabla_destino) == ("URGENCIAS 82", 9)
    assert a.fila_nueva == {"DATOS": "CUB 9\nELSA MORA\n62 AÑOS\nCC 12345678", "DX": "DOLOR ABDOMINAL"}      # solo lo que tiene texto


def test_agregar_sin_destino_no_es_automatica():
    p, e = _nuevo("8PISO-801")
    e.doc = ""
    (a,) = comparar([], [], nuevos=[(p, e)], tablas=TABLAS)
    assert a.tipo == "AGREGAR" and not a.marcada and not a.automatica and a.tabla_destino is None
    assert a.detalle.startswith("No sé en qué tabla va (habitación 8PISO-801): agrégalo a mano")
    assert a.fila_nueva["DATOS"].startswith("801\nJOSE MIGUEL TORRES RUIZ")
    (b,) = comparar([], [], nuevos=[_nuevo()])                                   # sin tablas tampoco se sabe
    assert not b.automatica and b.marcada is False


def test_ya_no_se_proponen_pacientes_del_sistema():
    p = PacienteSistema("MORA QUINTERO ESPERANZA", "UCI5-09", "Urgencias", dx="CHOQUE")
    assert comparar([p], [], tablas=TABLAS) == []
    assert comparar([p], [_fila()], tablas=TABLAS)[0].tipo == "RETIRAR"


def test_automatica():
    assert Accion("ACTUALIZAR", "x", fila=object()).automatica and not Accion("ACTUALIZAR", "x").automatica
    assert Accion("MOVER", "x", fila=object(), tabla_destino=0).automatica
    assert not Accion("MOVER", "x", fila=object()).automatica and not Accion("MOVER", "x", tabla_destino=3).automatica
    assert Accion("AGREGAR", "x", tabla_destino=0).automatica and not Accion("AGREGAR", "x").automatica
    assert not Accion("RETIRAR", "x", fila=object()).automatica and not Accion("REVISAR", "x", fila=object()).automatica
