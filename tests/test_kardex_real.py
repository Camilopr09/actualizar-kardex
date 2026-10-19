"""Estructura real del kardex (datos inventados): título combinado, encabezado en la fila 1,
tablas de 6 columnas, filas vacías, DATOS con variantes, emparejado difuso, formato de escritura
y kardex_doc.aplicar contra un documento falso de la API."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from comparar import FilaKardex, PacienteSistema, comparar, emparejar, interpretar_datos
from kardex_doc import aplicar, parsear_kardex_html
from notas import construir_tratamiento, interpretar_evolucion


def _p(lineas):
    return "".join(f"<p>{l}</p>" if l else "<p></p>" for l in lineas)


def _td(*lineas):
    return f"<td>{_p(lineas)}</td>"


ENC7 = ("<tr><td>DATOS</td><td>DX</td><td>EVOLUCIÓN</td><td>TRATAMIENTO</td><td>LABORATORIOS</td>"
        "<td>IMÁGENES / NOTAS</td><td>PENDIENTES</td></tr>")
ENC6 = ("<tr><td>DATOS</td><td>DX</td><td>EVOLUCIÓN</td><td>LABORATORIOS</td>"
        "<td>IMÁGENES / NOTAS</td><td>PENDIENTES</td></tr>")
VACIA7 = "<tr>" + "<td></td>" * 7 + "</tr>"

HTML = ("<html><body><h1>KARDEX</h1>"
        '<table><tr><td colspan="7"><p>PISO 4A ( 4 PACIENTES) 422 - 430</p></td></tr>' + ENC7
        + "<tr>" + _td("CUB 12", "ROSA ELENA", "PRADO LUNA", "", "59 AÑOS", "", "CC 1000234567")
        + _td("DX:", "1. HTA", "2. DM2") + _td("viejo") + _td("PLAN", "1. DIETA", "2. LOSARTAN") + "<td></td>" * 3 + "</tr>"
        + VACIA7
        + "<tr>" + _td("H4CAM-06", "MARTA", "OSORIO", "35años", "CC - 7000123", "FIP: 16/10/2026", "STT")
        + _td("DX", "NEUMONIA") + "<td></td>" * 5 + "</tr>"
        + "<tr>" + _td("418A", "LUIS ANDRES SOTO") + "<td></td>" * 6 + "</tr>"
        + "<tr>" + _td("JOENIS LUCIA", "MOSQUERA BERMUDEZ", "", "CC  1140895163 17/10/26", "NO LO VIMOS DECIRLE AL DR")
        + "<td></td>" * 6 + "</tr></table>"
        '<table><tr><td colspan="6"><p>UCI 1  (2 PACIENTES)</p></td></tr>' + ENC6
        + "<tr>" + _td("PASILLO", "ANA MARIA", "VILLARRE", "AL", "40 AÑOS") + _td("DX:", "1. SEPSIS")
        + _td("ev") + "<td></td>" * 3 + "</tr></table></body></html>")


def test_tablas_titulo_columnas_y_filas():
    f = parsear_kardex_html(HTML)
    assert [x.servicio for x in f] == ["PISO 4A"] * 4 + ["UCI 1"]
    assert [x.fila for x in f[:4]] == [2, 4, 5, 6]          # absolutas (título + encabezado + vacía)
    a = f[0]
    assert (a.nombre, a.habitacion, a.edad, a.documento) == ("ROSA ELENA PRADO LUNA", "CUB 12", "59 AÑOS", "1000234567")
    assert (a.col_dx, a.col_evolucion, a.col_tratamiento) == (1, 2, 3)
    assert a.dx == "DX:\n1. HTA\n2. DM2" and a.tratamiento.startswith("PLAN\n")
    b = f[1]
    assert (b.nombre, b.habitacion, b.documento, b.edad) == ("MARTA OSORIO", "H4CAM-06", "7000123", "35años")
    assert (f[2].nombre, f[2].habitacion) == ("LUIS ANDRES SOTO", "418A")      # fila con solo el nombre
    c = f[3]                                                                   # sin habitación, nombre primero
    assert (c.nombre, c.habitacion, c.documento) == ("JOENIS LUCIA MOSQUERA BERMUDEZ", "", "1140895163")
    u = f[4]                                                                   # 6 columnas, sin TRATAMIENTO
    assert (u.col_dx, u.col_evolucion, u.col_tratamiento) == (1, 2, None) and u.tratamiento == ""
    assert (u.nombre, u.habitacion) == ("ANA MARIA VILLARRE AL", "PASILLO")


def test_titulos():
    from kardex_doc import _limpiar_titulo as t
    assert t("PISO 5 (  PACIENTES)") == "PISO 5"
    assert t("URGENCIAS 47 ( 5 PACIENTES)") == "URGENCIAS 47"
    assert t("UCI 1  (2 PACIENTES)") == "UCI 1"


def test_variantes_de_datos():
    d = interpretar_datos
    assert d("332A\nPEDRO RIOS\n20 AÑOS")["habitacion"] == "332A"
    assert d("601\nA B")["habitacion"] == "601"
    assert d("EX TORAX 327A\nELSA MORA\nCC 12345678")["habitacion"] == "EX TORAX 327A"
    assert d("ASL\nELSA MORA\nSTT")["habitacion"] == "ASL" and d("ASL\nELSA MORA\nSTT")["nombre"] == "ELSA MORA"
    assert d("JUAN PEREZ\nH-1")["habitacion"] == "H-1"          # formato antiguo
    assert d("HOS82-11\nUNO DOS TRES CUATRO")["nombre"] == "UNO DOS TRES CUATRO"


def test_emparejar_difuso():
    assert emparejar("ALCIRA OCHO GANBOSA", ["OCHOA GAMBOA ALCIRA", "OTRA PERSONA LEJOS"]) == "OCHOA GAMBOA ALCIRA"
    assert emparejar("MARIA LOPEZ", ["MARIA PEREZ RUIZ"]) is None
    assert emparejar("MARIA GOMEZ", ["MARIA GOMEZ PEREZ", "MARIA GOMEZ RUIZ"]) is None      # empate
    assert emparejar("ANA MARIA VILLARRE AL", ["VILLARREAL SOTO ANA MARIA"]) == "VILLARREAL SOTO ANA MARIA"
    assert emparejar("X Y", ["NOMBRE DISTINTO 1000234567 OTRO"], "1000234567") == "NOMBRE DISTINTO 1000234567 OTRO"


def _fila(**kw):
    base = dict(tabla=0, fila=2, servicio="PISO 4A", datos="CUB 12\nROSA ELENA\nPRADO LUNA\n59 AÑOS\nCC 1000234567",
                dx="DX:\n1. HTA", evolucion="viejo", tratamiento="PLAN\n1. DIETA")
    base.update(kw)
    return FilaKardex(**base)


def _sis(**kw):
    base = dict(nombre="PRADO LUNA ROSA ELENA", habitacion="CUB 12", modo="Hospitalización",
                medico="DAZA PEREZ JUAN", fecha="19/10/2026 06:30", encontrado_detalle=True)
    base.update(kw)
    return PacienteSistema(**base)


def test_flujo_completo_formato_de_escritura():
    nota = ("-CX GENERAL-\nPTE CON DX: 1. HTA 2. DM2\nEXAMEN FISICO: ALERTA\nPLAN 1. DIETA 2. LOSARTAN 50 MG")
    info = interpretar_evolucion(nota, "19/10/2026", "DAZA PEREZ JUAN")
    s = _sis(dx=info["dx"], evolucion=info["evolucion"],
             tratamiento=construir_tratamiento(info["plan"], [], "PLAN\n1. DIETA", "DAZA PEREZ JUAN", "19/10/2026"))
    acc = {a.campo: a for a in comparar([s], [_fila()]) if a.tipo == "ACTUALIZAR"}
    assert set(acc) == {"DX", "EVOLUCIÓN", "TRATAMIENTO"}
    assert acc["DX"].nuevo == "DX:\n1. HTA\n2. DM2"
    assert acc["EVOLUCIÓN"].nuevo == "19/10/2026 - DR. DAZA PEREZ JUAN (CX GENERAL)\nEXAMEN FISICO: ALERTA"
    assert acc["TRATAMIENTO"].nuevo == "PLAN\n1. DIETA\n2. LOSARTAN 50 MG"


def test_sin_cambios_ignora_prefijos_y_mayusculas():
    s = _sis(dx="1. hta", tratamiento="IGUAL MANEJO (DR. X 19/10/2026)\n1. dieta")
    f = _fila(dx="DX 1. HTA", tratamiento="PLAN:\n1. DIETA", evolucion="")
    assert [a for a in comparar([s], [f]) if a.tipo == "ACTUALIZAR"] == []


def test_igual_manejo_formato():
    t = construir_tratamiento("IGUAL MANEJO", ["CEFAZOLINA 1G — 1 g IV c/8h"],
                              "IGUAL MANEJO (DR. VIEJO 01/01/2026)\n1. DIETA", "dra. lopez ruiz", "19/10/2026 07:00")
    assert t.splitlines() == ["IGUAL MANEJO (DRA. LOPEZ RUIZ 19/10/2026)", "1. DIETA", "CEFAZOLINA 1G — 1 G IV C/8H"]


def test_sin_columna_no_genera_actualizar():
    f = _fila(tratamiento="", col_tratamiento=None)
    acc = comparar([_sis(dx="1. HTA", tratamiento="PLAN\nX", evolucion="e")], [f])
    assert "TRATAMIENTO" not in {a.campo for a in acc}


# ------------------------------------------------------------------ aplicar con API falsa
def _celda(texto, ini):
    fin = ini + len(texto) + 1
    return {"content": [{"startIndex": ini, "endIndex": fin,
                         "paragraph": {"elements": [{"textRun": {"content": texto + "\n"}}]}}]}, fin


def _tabla(filas, ini=1):
    rows = []
    for textos in filas:
        celdas = []
        for t in textos:
            c, ini = _celda(t, ini + 1)
            celdas.append(c)
        rows.append({"tableCells": celdas})
    return {"table": {"tableRows": rows}}


class _Docs:
    def __init__(self, doc):
        self.doc, self.lotes = doc, []

    def documents(self):
        return self

    def get(self, documentId):
        return type("R", (), {"execute": lambda _s: self.doc})()

    def batchUpdate(self, documentId, body):
        self.lotes.append(body["requests"])
        return type("R", (), {"execute": lambda _s: {}})()


def test_aplicar_columna_correcta_fila_absoluta_negrita_y_orden():
    t7 = _tabla([["PISO 4A ( 1 PACIENTES)", "", "", "", "", "", ""],
                 ["DATOS", "DX", "EVOLUCIÓN", "TRATAMIENTO", "LAB", "IMG", "PEND"],
                 ["CUB 12\nROSA ELENA\nPRADO LUNA\n\n59 AÑOS", "DX:\n1. HTA", "viejo", "PLAN\n1. DIETA", "", "", ""]])
    t6 = _tabla([["UCI 1 (1 PACIENTES)", "", "", "", "", ""],
                 ["DATOS", "DX", "EVOLUCIÓN", "LAB", "IMG", "PEND"],
                 ["PASILLO\nANA MARIA\nVILLARREAL", "DX:\n1. X", "ev", "", "", ""]], ini=500)
    api = _Docs({"body": {"content": [{"paragraph": {}}, t7, t6]}})
    f1 = _fila(tabla=0, fila=2)
    f2 = FilaKardex(tabla=1, fila=2, servicio="UCI 1", datos="PASILLO\nANA MARIA\nVILLARREAL",
                    col_dx=1, col_evolucion=2, col_tratamiento=None)
    from comparar import Accion
    a_ev = Accion("ACTUALIZAR", "x", "EVOLUCIÓN", "viejo", "19/10/2026 - DR. A B (CX)\nTEXTO", f1)
    a_tr = Accion("ACTUALIZAR", "x", "TRATAMIENTO", "", "PLAN\n1. DIETA 2. X", f1)
    a_ev2 = Accion("ACTUALIZAR", "x", "EVOLUCIÓN", "ev", "19/10/2026 - DR. C D\nOTRO", f2)
    a_no = Accion("ACTUALIZAR", "x", "TRATAMIENTO", "", "PLAN\nZ", f2)          # la tabla de 6 columnas no la tiene
    escritas, omitidas = aplicar(api, "https://docs.google.com/document/d/ABC/edit", [a_ev, a_tr, a_ev2, a_no])
    assert escritas == [a_ev, a_tr, a_ev2]
    assert [o[0] for o in omitidas] == [a_no] and "no tiene la columna" in omitidas[0][1]
    reqs = api.lotes[0]
    inserts = [r["insertText"] for r in reqs if "insertText" in r]
    assert [i["text"] for i in inserts][-2:] != []
    idx = [i["location"]["index"] for i in inserts]
    assert idx == sorted(idx, reverse=True)                                    # de abajo hacia arriba
    # columna EVOLUCIÓN de t7 (3.ª celda de la fila 2) y TRATAMIENTO (4.ª)
    ev_ini = t7["table"]["tableRows"][2]["tableCells"][2]["content"][0]["startIndex"]
    tr_ini = t7["table"]["tableRows"][2]["tableCells"][3]["content"][0]["startIndex"]
    assert {ev_ini, tr_ini} <= set(idx)
    estilos = [r["updateTextStyle"] for r in reqs if "updateTextStyle" in r]
    negritas = [n for n in estilos if n["textStyle"] == {"bold": True}]
    assert len(negritas) == 2                                                  # solo EVOLUCIÓN, nunca TRATAMIENTO
    # el resto de la nota queda sin negrita, empezando justo después de la primera línea
    assert any(n["textStyle"] == {"bold": False} and n["range"]["startIndex"] == ev_ini + len("19/10/2026 - DR. A B (CX)")
               for n in estilos)
    assert {"startIndex": ev_ini, "endIndex": ev_ini + len("19/10/2026 - DR. A B (CX)")} in [n["range"] for n in negritas]
    assert all(n["textStyle"] == {"bold": True} for n in negritas)
