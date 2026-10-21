"""kardex_doc.aplicar contra el documento FALSO de la API de Docs (tests/docs_falso.py): ediciones de celda
(DX/EVOLUCIÓN/TRATAMIENTO, IMÁGENES / NOTAS, HABITACIÓN), AGREGAR, MOVER, estilos, índices UTF-16, conteo del título.
Todos los datos son inventados."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

from comparar import Accion, PacienteSistema, comparar
from docs_falso import DocumentoFalso, ENC6, P, a_html, celda, tabla_kardex
from kardex_doc import VERDE, aplicar, parsear_kardex_html, tablas_kardex
from notas import EstudioImagen, bloque_imagen, unir_bloques

URL = "https://docs.google.com/document/d/ABC/edit"
LETRA = {"weightedFontFamily": {"fontFamily": "Calibri", "weight": 400}, "fontSize": {"magnitude": 9, "unit": "PT"}}
AZUL = {"color": {"rgbColor": {"red": 0.0, "green": 0.0, "blue": 1.0}}}
NEGRITA = dict(LETRA, bold=True)
DATOS_EST = dict(NEGRITA, foregroundColor=AZUL)           # DATOS: negrita y azul
VERDE_NEGRITA = dict(NEGRITA, backgroundColor=VERDE)

# T0 = PISO 4A (422-430), T1 = PISO 6, T2 = UCI 1 (sin TRATAMIENTO)
ROSA = "425\nROSA ELENA PRADO LUNA\n59 AÑOS\nCC 1000234567"
MARTA = "428\nMARTA OSORIO\n35 AÑOS\nCC 7000123"
LUIS = "607\nLUIS ANDRES SOTO\n70 AÑOS\nCC 8000555"
ANA = "UCI\nANA MARIA VILLARREAL\n40 AÑOS\nCC 9000777"


def _fila_pac(datos, dx="", ev="", tr="", img="", n=7, estilo=LETRA):
    cs = [celda(datos, DATOS_EST), celda(dx, estilo), celda(ev, estilo), celda(tr, estilo), celda("", estilo),
          celda(img, estilo), celda("", estilo)]
    return cs if n == 7 else [cs[0], cs[1], cs[2], cs[4], cs[5], cs[6]]


def kardex(**kw):
    t0 = tabla_kardex("PISO 4A ( 2 PACIENTES) 422 - 430", [
        _fila_pac(ROSA, "DX:\n1. HTA", "viejo", "PLAN\n1. DIETA", "TAC DE ABDOMEN 10/10/26\nCONCLUSIÓN: algo"),
        _fila_pac(MARTA, "DX\nNEUMONIA", "otra evolución")], vacias=1)
    t1 = tabla_kardex("PISO 6 (5 PACIENTES)", [_fila_pac(LUIS, "DX:\n1. COLELITIASIS", "ev", "PLAN\nX")], vacias=2)
    t2 = tabla_kardex("UCI 1 ( PACIENTES)", [_fila_pac(ANA, "DX:\n1. SEPSIS", "ev", n=6)], vacias=0, encabezado=ENC6)
    return DocumentoFalso([P("KARDEX MIS PX"), t0, P(""), t1, P(""), t2, P("")], **kw)


def filas(doc):
    return parsear_kardex_html(a_html(doc))


def fila_de(doc, nombre):
    return next(f for f in filas(doc) if f.nombre == nombre)


def ac(doc, nombre, campo, nuevo="", **kw):
    f = fila_de(doc, nombre)
    return Accion("ACTUALIZAR", nombre, campo, "", nuevo, f, servicio=f.servicio, **kw)


def escribir(doc, acciones):
    return aplicar(doc.servicio(), URL, acciones)


# ------------------------------------------------------------------ DX / EVOLUCIÓN / TRATAMIENTO
def test_reemplazo_de_dx_evolucion_tratamiento_y_negrita():
    doc = kardex()
    a1 = ac(doc, "ROSA ELENA PRADO LUNA", "DX", "DX:\n1. HTA\n2. DM2")
    a2 = ac(doc, "ROSA ELENA PRADO LUNA", "EVOLUCIÓN", "19/10/2026 - DR. A B (CX GENERAL)\nTEXTO DE LA NOTA")
    a3 = ac(doc, "ROSA ELENA PRADO LUNA", "TRATAMIENTO", "PLAN\n1. DIETA\n2. LOSARTAN")
    a4 = ac(doc, "LUIS ANDRES SOTO", "EVOLUCIÓN", "19/10/2026 - DR. C D\nOTRO")
    escritas, omitidas = escribir(doc, [a1, a2, a3, a4])
    assert escritas == [a1, a2, a3, a4] and omitidas == []
    assert doc.texto(0, 2, 1) == "DX:\n1. HTA\n2. DM2"
    assert doc.texto(0, 2, 2) == "19/10/2026 - DR. A B (CX GENERAL)\nTEXTO DE LA NOTA"
    assert doc.texto(0, 2, 3) == "PLAN\n1. DIETA\n2. LOSARTAN"
    assert doc.texto(1, 2, 2) == "19/10/2026 - DR. C D\nOTRO"
    # solo la primera línea de EVOLUCIÓN en negrita; la letra (fuente, tamaño) se hereda de la celda
    assert doc.estilo_de(0, 2, 2, "19/10/2026 - DR. A B (CX GENERAL)") == NEGRITA
    assert doc.estilo_de(0, 2, 2, "TEXTO DE LA NOTA") == dict(LETRA, bold=False)
    assert doc.estilo_de(0, 2, 3, "PLAN") == LETRA and doc.estilo_de(0, 2, 1, "1. HTA") == LETRA     # sin tocar el estilo
    assert doc.texto(0, 3, 2) == "otra evolución"                          # la otra fila no se tocó
    assert [len(t.filas) for t in doc.tablas()] == [5, 5, 3]


def test_indices_utf16_con_emoji_antes_de_la_celda():
    doc = kardex()
    # un emoji (2 unidades UTF-16, 1 carácter) en una celda ANTERIOR desplaza los índices de la API
    doc.tablas()[0].filas[2].celdas[5].parrafos[0].chars[0:0] = [["🙂", {}], [" ", {}]]
    a = ac(doc, "MARTA OSORIO", "DX", "DX:\nNUEVO")
    escribir(doc, [a])
    assert doc.texto(0, 3, 1) == "DX:\nNUEVO" and doc.texto(0, 2, 5).startswith("🙂 TAC")


def test_fila_se_vuelve_a_buscar_por_paciente():
    doc = kardex()
    a = ac(doc, "MARTA OSORIO", "DX", "DX:\nNUEVO")                     # fila 3 al leer
    # alguien agregó una fila arriba mientras tanto: MARTA queda en la fila 4
    t0 = doc.tablas()[0]
    t0.filas.insert(2, type(t0.filas[0])([celda(""), celda(""), celda(""), celda(""), celda(""), celda(""), celda("")]))
    escritas, omitidas = escribir(doc, [a])
    assert escritas == [a] and doc.texto(0, 4, 1) == "DX:\nNUEVO" and doc.texto(0, 3, 1) == "DX:\n1. HTA"


def test_fila_ocupada_por_otro_paciente_se_omite():
    doc = kardex()
    a = ac(doc, "MARTA OSORIO", "DX", "DX:\nNUEVO")
    doc.tablas()[0].filas[3].celdas[0] = celda("430\nOTRA PERSONA DISTINTA\n20 AÑOS")
    escritas, omitidas = escribir(doc, [a])
    assert escritas == [] and "La fila cambió (ahora dice «OTRA PERSONA DISTINTA»)" in omitidas[0][1]
    assert doc.lotes == []


def test_columna_inexistente_y_acciones_que_no_se_escriben():
    doc = kardex()
    a = ac(doc, "ANA MARIA VILLARREAL", "TRATAMIENTO", "PLAN\nZ")          # UCI 1 no tiene TRATAMIENTO
    r = Accion("REVISAR", "X", detalle="mirar")
    e, o = escribir(doc, [a, r])
    assert e == [] and {m for _, m in o} == {"La tabla no tiene la columna TRATAMIENTO", "No es una acción que se escriba sola"}


# ------------------------------------------------------------------ IMÁGENES / NOTAS
E1 = EstudioImagen("19/10/26", "ECOGRAFÍA", "TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA",
                   "Engrosamiento cutáneo\nÁreas líquidas que sugieren colección", "101")
E2 = EstudioImagen("17/10/26", "TAC", "TAC DE ABDOMEN SIMPLE", "CONCLUSIÓN: sin hallazgos", "100")


def _ins(*estudios):
    return unir_bloques(estudios)


def test_imagenes_en_celda_vacia_titulos_en_verde_y_negrita():
    doc = kardex()
    ins = _ins(E1, E2)
    a = ac(doc, "MARTA OSORIO", "IMÁGENES / NOTAS", insertar=ins)
    a.nuevo = ins
    escritas, omitidas = escribir(doc, [a])
    assert escritas == [a] and omitidas == []
    assert doc.texto(0, 3, 5) == ins
    t1, t2 = bloque_imagen(E1).split("\n")[0], bloque_imagen(E2).split("\n")[0]
    for t in (t1, t2):
        assert doc.estilo_de(0, 3, 5, t) == dict(NEGRITA, backgroundColor=VERDE)
    # el informe va sin negrita y sin resaltado
    est = doc.estilo_de(0, 3, 5, "Engrosamiento cutáneo")
    assert not est.get("bold") and "backgroundColor" not in est
    assert est["fontSize"] == LETRA["fontSize"]


def test_imagenes_arriba_sin_heredar_el_verde_ni_borrar_nada():
    doc = kardex()
    # la celda de ROSA ya tiene un estudio con título en verde y negrita
    cel = doc.tablas()[0].filas[2].celdas[5]
    cel.parrafos[0] = P(("TAC DE ABDOMEN 10/10/26", VERDE_NEGRITA))
    antes = doc.texto(0, 2, 5)
    ins = _ins(E1)
    a = ac(doc, "ROSA ELENA PRADO LUNA", "IMÁGENES / NOTAS", insertar=ins)
    escribir(doc, [a])
    assert doc.texto(0, 2, 5) == ins + "\n\n" + antes                       # arriba, separado por un renglón vacío
    # lo viejo conserva su verde; lo insertado (informe, renglón vacío) NO lo hereda
    assert doc.estilo_de(0, 2, 5, "TAC DE ABDOMEN 10/10/26") == VERDE_NEGRITA
    est = doc.estilo_de(0, 2, 5, "Engrosamiento cutáneo")
    assert not est.get("bold") and "backgroundColor" not in est
    assert doc.estilo_de(0, 2, 5, bloque_imagen(E1).split("\n")[0])["backgroundColor"] == VERDE
    vacio = doc.parrafos(0, 2, 5)[len(ins.split("\n"))]
    assert vacio.texto == "" and "backgroundColor" not in vacio.chars[0][1] and not vacio.chars[0][1].get("bold")


def test_imagenes_bajo_el_subtitulo():
    doc = kardex()
    cel = doc.tablas()[0].filas[2].celdas[5]
    cel.parrafos = [P(("IMÁGENES", dict(LETRA, underline=True)), alineacion="CENTER"),
                    P(("TAC DE ABDOMEN 10/10/26", VERDE_NEGRITA)), P("CONCLUSIÓN: algo", estilo=LETRA)]
    ins = _ins(E1)
    escribir(doc, [ac(doc, "ROSA ELENA PRADO LUNA", "IMÁGENES / NOTAS", insertar=ins)])
    assert doc.texto(0, 2, 5) == "IMÁGENES\n" + ins + "\n\nTAC DE ABDOMEN 10/10/26\nCONCLUSIÓN: algo"
    assert doc.alineaciones(0, 2, 5)[0] == "CENTER"
    assert doc.estilo_de(0, 2, 5, "IMÁGENES").get("underline") is True
    assert doc.estilo_de(0, 2, 5, "TAC DE ABDOMEN 10/10/26") == VERDE_NEGRITA
    assert "backgroundColor" not in doc.estilo_de(0, 2, 5, "Engrosamiento cutáneo")
    assert not doc.estilo_de(0, 2, 5, "Engrosamiento cutáneo").get("underline")


def test_imagenes_subtitulo_es_el_ultimo_renglon():
    doc = kardex()
    cel = doc.tablas()[0].filas[3].celdas[5]
    cel.parrafos = [P(("IMÁGENES Y PROCEDIMIENTO", dict(LETRA, underline=True)), alineacion="CENTER")]
    ins = _ins(E2)
    escribir(doc, [ac(doc, "MARTA OSORIO", "IMÁGENES / NOTAS", insertar=ins)])
    assert doc.texto(0, 3, 5) == "IMÁGENES Y PROCEDIMIENTO\n" + ins
    assert doc.alineaciones(0, 3, 5) == ["CENTER"] + ["START"] * len(ins.split("\n"))   # lo nuevo no queda centrado
    assert not doc.estilo_de(0, 3, 5, "CONCLUSIÓN: sin hallazgos").get("underline")
    assert doc.estilo_de(0, 3, 5, "IMÁGENES Y PROCEDIMIENTO").get("underline") is True


# ------------------------------------------------------------------ HABITACIÓN
def test_habitacion_cambia_solo_ese_renglon_y_conserva_el_estilo():
    doc = kardex()
    a = ac(doc, "ROSA ELENA PRADO LUNA", "HABITACIÓN", "426", habitacion_nueva="426")
    escritas, _ = escribir(doc, [a])
    assert escritas == [a] and doc.texto(0, 2, 0) == "426\nROSA ELENA PRADO LUNA\n59 AÑOS\nCC 1000234567"
    assert doc.estilo_de(0, 2, 0, "426") == DATOS_EST


def test_habitacion_sin_renglon_se_agrega_al_inicio():
    doc = kardex()
    doc.tablas()[0].filas[3].celdas[0] = celda("MARTA OSORIO\n35 AÑOS\nCC 7000123", DATOS_EST)
    a = ac(doc, "MARTA OSORIO", "HABITACIÓN", "429A", habitacion_nueva="429A")
    escribir(doc, [a])
    assert doc.texto(0, 3, 0) == "429A\nMARTA OSORIO\n35 AÑOS\nCC 7000123"


def test_habitacion_que_ya_es_esa_se_omite():
    doc = kardex()
    e, o = escribir(doc, [ac(doc, "ROSA ELENA PRADO LUNA", "HABITACIÓN", "425", habitacion_nueva="425")])
    assert e == [] and "ya dice" in o[0][1] and doc.lotes == []


# ------------------------------------------------------------------ AGREGAR
def _agregar(doc, tabla, nombre="JOSE MIGUEL TORRES RUIZ", **kw):
    fila = {"DATOS": f"430\n{nombre}\n44 AÑOS\nCC 1020304050", "DX": "1. COLECISTITIS AGUDA",
            "EVOLUCIÓN": "19/10/2026 - DR. A B (CX GENERAL)\nPACIENTE ESTABLE",
            "TRATAMIENTO": "PLAN\n1. DIETA ZERO", "IMÁGENES / NOTAS": _ins(E1, E2)}
    fila.update(kw)
    return Accion("AGREGAR", nombre, nuevo="x", servicio="PISO 4A", destino="PISO 4A", tabla_destino=tabla,
                  fila_nueva=fila)


def test_agregar_usa_la_primera_fila_vacia_y_copia_el_estilo():
    doc = kardex()
    a = _agregar(doc, 0)
    escritas, omitidas = escribir(doc, [a])
    assert escritas == [a] and omitidas == []
    assert [len(t.filas) for t in doc.tablas()] == [5, 5, 3]                # no se insertó fila: había una vacía
    assert doc.fila(0, 4)[:4] == [a.fila_nueva["DATOS"], a.fila_nueva["DX"], a.fila_nueva["EVOLUCIÓN"],
                                  a.fila_nueva["TRATAMIENTO"]]
    assert doc.texto(0, 4, 5) == a.fila_nueva["IMÁGENES / NOTAS"] and doc.texto(0, 4, 4) == ""
    # estilo copiado de la fila con paciente más cercana (la anterior): DATOS en negrita y azul, el resto con la letra
    assert doc.estilo_de(0, 4, 0, "430") == DATOS_EST
    assert doc.estilo_de(0, 4, 0, "JOSE MIGUEL TORRES RUIZ") == DATOS_EST
    assert doc.estilo_de(0, 4, 1, "1. COLECISTITIS AGUDA") == LETRA
    assert doc.estilo_de(0, 4, 3, "PLAN") == LETRA
    # EVOLUCIÓN: 1.ª línea en negrita, el resto no; IMÁGENES: títulos negrita + verde, informe sin resaltado
    assert doc.estilo_de(0, 4, 2, "19/10/2026 - DR. A B (CX GENERAL)") == NEGRITA
    assert not doc.estilo_de(0, 4, 2, "PACIENTE ESTABLE").get("bold")
    titulo = bloque_imagen(E1).split("\n")[0]
    assert doc.estilo_de(0, 4, 5, titulo) == dict(NEGRITA, backgroundColor=VERDE)
    est = doc.estilo_de(0, 4, 5, "Engrosamiento cutáneo")
    assert not est.get("bold") and "backgroundColor" not in est
    # el título de la tabla sube de 2 a 3
    assert doc.titulo(0) == "PISO 4A ( 3 PACIENTES) 422 - 430"
    assert doc.titulo(1) == "PISO 6 (5 PACIENTES)"


def test_agregar_inserta_fila_si_no_hay_vacia_y_pone_el_conteo_si_no_tiene_numero():
    doc = kardex()
    a = _agregar(doc, 2)                                                    # UCI 1: sin filas vacías y sin TRATAMIENTO
    a.destino = "UCI 1"
    escritas, omitidas = escribir(doc, [a])
    assert escritas == [a] and [len(t.filas) for t in doc.tablas()] == [5, 5, 4]
    assert doc.fila(2, 3) == [a.fila_nueva["DATOS"], a.fila_nueva["DX"], a.fila_nueva["EVOLUCIÓN"], "",
                              a.fila_nueva["IMÁGENES / NOTAS"], ""]       # TRATAMIENTO no existe en esa tabla
    assert doc.titulo(2) == "UCI 1 ( 2 PACIENTES)"                          # no tenía número: cantidad de filas con paciente
    # el estilo salió de la fila anterior de ESA tabla
    assert doc.estilo_de(2, 3, 0, "430") == DATOS_EST


def test_agregar_se_escribe_aunque_la_fila_nueva_herede_estilos_de_la_referencia():
    doc = kardex(herencia_fila_nueva=True)
    for c in doc.tablas()[2].filas[2].celdas:                               # la fila de referencia tiene resaltado y cursiva
        for p in c.parrafos:
            for ch in p.chars:
                ch[1] = dict(ch[1], backgroundColor=VERDE, italic=True)
    a = _agregar(doc, 2)
    escribir(doc, [a])
    est = doc.estilo_de(2, 3, 1, "1. COLECISTITIS AGUDA")
    assert "backgroundColor" not in est and "italic" not in est


def test_agregar_dos_pacientes_en_la_misma_tabla():
    doc = kardex()
    a1, a2 = _agregar(doc, 0, "PRIMERO UNO PEREZ", DATOS="430\nPRIMERO UNO PEREZ\nCC 1"), \
        _agregar(doc, 0, "SEGUNDO DOS GOMEZ", DATOS="431\nSEGUNDO DOS GOMEZ\nCC 2")
    escritas, _ = escribir(doc, [a1, a2])
    assert escritas == [a1, a2] and [len(t.filas) for t in doc.tablas()] == [6, 5, 3]      # una reutiliza la vacía, otra inserta
    assert doc.texto(0, 4, 0).splitlines()[1] == "PRIMERO UNO PEREZ" and doc.texto(0, 5, 0).splitlines()[1] == "SEGUNDO DOS GOMEZ"
    assert doc.titulo(0) == "PISO 4A ( 4 PACIENTES) 422 - 430"


def test_agregar_omite_si_ya_esta_o_no_hay_destino():
    doc = kardex()
    ya = _agregar(doc, 0, "MARTA OSORIO", DATOS="428\nMARTA OSORIO\nCC 7000123")
    sin = Accion("AGREGAR", "X Y", fila_nueva={"DATOS": "X Y"}, tabla_destino=None)
    raro = _agregar(doc, 9)
    e, o = escribir(doc, [ya, sin, raro])
    assert e == [] and {m for _, m in o} == {"Ya está en el kardex", "No se sabe en qué tabla va; agrégalo a mano",
                                              "No se encontró la tabla destino"}
    assert doc.lotes == []


# ------------------------------------------------------------------ MOVER
def _mover(doc, nombre, destino, hab):
    f = fila_de(doc, nombre)
    return Accion("MOVER", nombre, "HABITACIÓN", "", "", f, servicio=f.servicio, destino="PISO 6",
                  tabla_destino=destino, habitacion_nueva=hab)


def _fila_con_formato(doc):
    """Da a la fila de ROSA formato variado: run en verde+negrita, un enlace, un párrafo centrado."""
    t = doc.tablas()[0].filas[2]
    t.celdas[5].parrafos = [P(("TAC DE ABDOMEN 10/10/26", VERDE_NEGRITA)), P(("CONCLUSIÓN: ", NEGRITA), ("algo", LETRA)),
                            P(("nota centrada", dict(LETRA, italic=True)), alineacion="CENTER")]
    t.celdas[1].parrafos = [P(("DX:", NEGRITA)), P(("1. HTA", LETRA))]


def test_mover_copia_la_fila_con_su_formato_y_borra_el_origen():
    doc = kardex()
    _fila_con_formato(doc)
    copia = [doc.fila(0, 2), [doc.estilos(0, 2, c) for c in range(7)], doc.alineaciones(0, 2, 5)]
    a = _mover(doc, "ROSA ELENA PRADO LUNA", 1, "605")
    escritas, omitidas = escribir(doc, [a])
    assert escritas == [a] and omitidas == []
    assert [len(t.filas) for t in doc.tablas()] == [4, 5, 3]               # salió de T0; T1 usó una fila vacía
    nombres_t0 = [doc.texto(0, i, 0).splitlines()[1] for i in (2, 3) if doc.texto(0, i, 0)]
    assert nombres_t0 == ["MARTA OSORIO"]
    dest = doc.fila(1, 3)
    assert dest[0] == "605\nROSA ELENA PRADO LUNA\n59 AÑOS\nCC 1000234567"       # habitación nueva, lo demás igual
    assert dest[1:] == copia[0][1:]
    assert doc.estilos(1, 3, 5) == copia[1][5] and doc.estilos(1, 3, 1) == copia[1][1]    # estilo por textRun
    assert doc.alineaciones(1, 3, 5) == copia[2] == [None, None, "CENTER"]
    assert doc.estilo_de(1, 3, 5, "TAC DE ABDOMEN 10/10/26") == VERDE_NEGRITA
    assert doc.estilo_de(1, 3, 0, "605") == DATOS_EST                            # la habitación nueva conserva el estilo
    assert doc.titulo(0) == "PISO 4A ( 1 PACIENTES) 422 - 430" and doc.titulo(1) == "PISO 6 (6 PACIENTES)"


def test_mover_inserta_fila_en_el_destino_si_no_hay_vacias():
    doc = kardex()
    a = _mover(doc, "LUIS ANDRES SOTO", 0, "429")
    a.destino = "PISO 4A"
    t0 = doc.tablas()[0]
    t0.filas.pop()                                                          # T0 sin filas vacías
    escritas, _ = escribir(doc, [a])
    assert escritas == [a] and [len(t.filas) for t in doc.tablas()] == [5, 4, 3]
    assert doc.texto(0, 4, 0).splitlines()[:2] == ["429", "LUIS ANDRES SOTO"] and doc.texto(1, 2, 0) == ""
    assert doc.titulo(1) == "PISO 6 (4 PACIENTES)" and doc.titulo(0) == "PISO 4A ( 3 PACIENTES) 422 - 430"


def test_mover_sin_habitacion_en_datos_la_agrega_al_inicio():
    doc = kardex()
    doc.tablas()[0].filas[3].celdas[0] = celda("MARTA OSORIO\n35 AÑOS\nCC 7000123", DATOS_EST)
    escribir(doc, [_mover(doc, "MARTA OSORIO", 1, "610")])
    assert doc.texto(1, 3, 0) == "610\nMARTA OSORIO\n35 AÑOS\nCC 7000123"


def test_mover_sin_habitacion_nueva_deja_datos_como_estan():
    doc = kardex()
    escribir(doc, [_mover(doc, "LUIS ANDRES SOTO", 0, "")])
    assert doc.texto(0, 4, 0) == LUIS


def test_mover_a_tabla_sin_una_columna_con_contenido_no_toca_nada():
    doc = kardex()
    a = _mover(doc, "LUIS ANDRES SOTO", 2, "UCI")                           # UCI 1 no tiene TRATAMIENTO y la fila sí
    antes = [[doc.fila(t, f) for f in range(len(tb.filas))] for t, tb in enumerate(doc.tablas())]
    e, o = escribir(doc, [a])
    assert e == [] and "no tiene la columna TRATAMIENTO" in o[0][1]
    assert [[doc.fila(t, f) for f in range(len(tb.filas))] for t, tb in enumerate(doc.tablas())] == antes
    assert doc.lotes == []


def test_mover_no_borra_si_el_paciente_ya_esta_en_el_destino_o_cambio_la_fila():
    doc = kardex()
    doc.tablas()[1].filas[3].celdas[0] = celda("610\nMARTA OSORIO\nCC 7000123")      # ya está en PISO 6
    e, o = escribir(doc, [_mover(doc, "MARTA OSORIO", 1, "611")])
    assert e == [] and "ya está en la tabla destino" in o[0][1] and doc.lotes == []
    doc = kardex()
    a = _mover(doc, "MARTA OSORIO", 1, "611")
    doc.tablas()[0].filas[3].celdas[0] = celda("430\nOTRO PACIENTE ASI\nCC 5")
    e, o = escribir(doc, [a])
    assert e == [] and "La fila cambió" in o[0][1]


def test_contenido_con_objetos_que_no_se_pueden_copiar():
    from kardex_doc import _contenido, _Omitida
    celda_api = {"content": [{"paragraph": {"elements": [{"textRun": {"content": "x\n", "textStyle": {}}},
                                                          {"inlineObjectElement": {"inlineObjectId": "k"}}]}}]}
    with pytest.raises(_Omitida):
        _contenido(celda_api)


# ------------------------------------------------------------------ todo junto
def test_ediciones_agregar_y_mover_en_la_misma_escritura():
    doc = kardex()
    e1 = ac(doc, "ROSA ELENA PRADO LUNA", "DX", "DX:\n1. HTA\n2. DM2")
    e2 = ac(doc, "LUIS ANDRES SOTO", "IMÁGENES / NOTAS", insertar=_ins(E1))
    e3 = ac(doc, "MARTA OSORIO", "HABITACIÓN", "427", habitacion_nueva="427")
    nuevo = _agregar(doc, 1, "JOSE MIGUEL TORRES RUIZ")
    nuevo.destino = "PISO 6"
    mov = _mover(doc, "MARTA OSORIO", 1, "612")                              # MARTA: cambia la habitación y se mueve
    mov2 = _mover(doc, "ANA MARIA VILLARREAL", 0, "423")
    mov2.destino = "PISO 4A"
    ev = ac(doc, "ANA MARIA VILLARREAL", "EVOLUCIÓN", "19/10/2026 - DR. A B\nUCI")
    escritas, omitidas = escribir(doc, [mov, nuevo, e1, e2, mov2, ev])      # fuera de orden a propósito
    assert omitidas == [], omitidas
    assert set(map(id, escritas)) == set(map(id, [mov, nuevo, e1, e2, mov2, ev]))
    nombres = lambda t: [doc.texto(t, i, 0).splitlines()[1] for i in range(2, len(doc.tablas()[t].filas)) if doc.texto(t, i, 0)]
    assert nombres(0) == ["ROSA ELENA PRADO LUNA", "ANA MARIA VILLARREAL"]
    assert nombres(1) == ["LUIS ANDRES SOTO", "JOSE MIGUEL TORRES RUIZ", "MARTA OSORIO"]
    assert nombres(2) == []
    assert doc.texto(0, 2, 1) == "DX:\n1. HTA\n2. DM2"
    fila_luis = next(i for i in range(2, 6) if doc.texto(1, i, 0).startswith("607"))
    assert doc.texto(1, fila_luis, 5).startswith(bloque_imagen(E1).split("\n")[0])
    fila_ana = next(i for i in range(2, 6) if "ANA MARIA" in doc.texto(0, i, 0))
    assert doc.texto(0, fila_ana, 0).startswith("423\n") and doc.texto(0, fila_ana, 2) == "19/10/2026 - DR. A B\nUCI"
    assert doc.titulo(0) == "PISO 4A ( 2 PACIENTES) 422 - 430"         # +1 (ANA) -1 (MARTA) = igual
    assert doc.titulo(1) == "PISO 6 (7 PACIENTES)"                       # +1 (JOSE) +1 (MARTA)
    assert doc.titulo(2) == "UCI 1 ( 0 PACIENTES)"                       # sin número: la cantidad de filas con paciente


# ------------------------------------------------------------------ de punta a punta: HTML -> comparar -> aplicar
def test_de_punta_a_punta():
    doc = kardex()
    html = a_html(doc)
    kard, tablas = parsear_kardex_html(html), tablas_kardex(html)
    assert [(t.servicio, t.rango, t.filas_pacientes) for t in tablas] == [
        ("PISO 4A", (422, 430), 2), ("PISO 6", None, 1), ("UCI 1", None, 1)]
    rosa = PacienteSistema("PRADO LUNA ROSA ELENA", "4PISO-425", "Hospitalización", "DAZA", "19/10/2026 06:30",
                           dx="1. HTA\n2. DM2", evolucion="19/10/2026 - DR. DAZA (CX GENERAL)\nBIEN", tratamiento="PLAN\n1. DIETA",
                           encontrado_detalle=True, documento="1000234567", imagenes=[E1])
    marta = PacienteSistema("OSORIO MARTA", "6PISO-612", "Hospitalización", encontrado_detalle=True, documento="7000123")
    nuevo = PacienteSistema("TORRES RUIZ JOSE MIGUEL", "6PISO-610", "Hospitalización", dx="1. COLECISTITIS",
                            encontrado_detalle=True, documento="1020304050", edad="44 AÑOS", imagenes=[E2])
    from comparar import PacienteEntrega
    ent = PacienteEntrega("JOSE MIGUEL TORRES RUIZ", "1020304050", "CC", "44 AÑOS", "610", doc="PISO 6")
    acciones = comparar([rosa, marta], kard, nuevos=[(nuevo, ent)], tablas=tablas)
    assert {(a.tipo, a.campo) for a in acciones if a.automatica} == {
        ("ACTUALIZAR", "DX"), ("ACTUALIZAR", "EVOLUCIÓN"), ("ACTUALIZAR", "IMÁGENES / NOTAS"), ("MOVER", "HABITACIÓN"),
        ("AGREGAR", "")}
    escritas, omitidas = escribir(doc, [a for a in acciones if a.automatica])
    assert omitidas == [] and len(escritas) == 5
    assert doc.texto(0, 2, 1) == "DX:\n1. HTA\n2. DM2"
    assert doc.texto(0, 2, 5).startswith(bloque_imagen(E1)) and "TAC DE ABDOMEN 10/10/26" in doc.texto(0, 2, 5)
    nombres_p6 = [doc.texto(1, i, 0).splitlines()[1] for i in range(2, len(doc.tablas()[1].filas)) if doc.texto(1, i, 0)]
    assert nombres_p6 == ["LUIS ANDRES SOTO", "JOSE MIGUEL TORRES RUIZ", "MARTA OSORIO"]
    assert doc.titulo(0) == "PISO 4A ( 1 PACIENTES) 422 - 430" and doc.titulo(1) == "PISO 6 (7 PACIENTES)"
    # releyendo el documento ya escrito no queda nada por hacer (salvo lo que el sistema no trae)
    html2 = a_html(doc)
    de_nuevo = comparar([rosa, marta, nuevo], parsear_kardex_html(html2), tablas=tablas_kardex(html2))
    assert [(a.tipo, a.campo) for a in de_nuevo if a.tipo in ("ACTUALIZAR", "MOVER", "AGREGAR")] == []


def test_titulo_fuera_de_la_tabla_y_tabla_sin_fila_de_titulo():
    t = tabla_kardex("x", [_fila_pac(LUIS, "DX", "ev", "PLAN")], vacias=1)
    del t.filas[0]                                            # sin fila de título: el encabezado es la fila 0
    doc = DocumentoFalso([P("KARDEX"), P("PISO 6 (1 PACIENTES)"), t, P("")])
    assert [(x.servicio, x.filas_pacientes) for x in tablas_kardex(a_html(doc))] == [("PISO 6", 1)]
    a = _agregar(doc, 0)
    escritas, omitidas = escribir(doc, [a])
    assert escritas == [a] and omitidas == []
    assert doc.texto(0, 2, 0) == a.fila_nueva["DATOS"]
    assert doc.parrafos_cuerpo()[1].texto == "PISO 6 (2 PACIENTES)"
