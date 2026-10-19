import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notas import interpretar_evolucion, interpretar_ordenes, construir_tratamiento, es_igual_manejo
from comparar import PacienteSistema, comparar, emparejar
from kardex_doc import parsear_kardex_html

NOTA = """-CX GENERAL-
PTE JUAN PEREZ CON DX: 1. COLECISTITIS AGUDA 2. HTA
EXAMEN FISICO: ALERTA, ABDOMEN BLANDO
ANALISIS: BUENA EVOLUCION
PLAN 1. DIETA LIQUIDA 2. CEFAZOLINA 1 G IV"""

def test_evolucion():
    r = interpretar_evolucion(NOTA, "16/10/2026", "CARLOS DAZA")
    assert "COLECISTITIS" in r["dx"] and "EXAMEN" not in r["dx"]
    assert r["evolucion"].startswith("16/10/2026 - DR. CARLOS DAZA (CX GENERAL)\n")
    assert r["plan"].startswith("1. DIETA LIQUIDA")
    # el texto de la evolución arranca justo después del DX (sin restos de él)
    assert r["evolucion"] == ("16/10/2026 - DR. CARLOS DAZA (CX GENERAL)\n"
                              "EXAMEN FISICO: ALERTA, ABDOMEN BLANDO ANALISIS: BUENA EVOLUCION")

def test_ordenes_y_tratamiento():
    o = interpretar_ordenes("DIETA LIQUIDA\nFórmula #1\n1) CEFAZOLINA 1G Cantidad: 3 Dosis: 1 g IV c/8h\n")
    assert o == ["DIETA LIQUIDA", "CEFAZOLINA 1G — 1 g IV c/8h"]
    assert es_igual_manejo("IGUAL MANEJO")
    t = construir_tratamiento("IGUAL MANEJO", o, "PLAN\nDIETA LIQUIDA\nOMEPRAZOL 20 MG", "DAZA PEREZ JUAN", "16/10/2026 06:30")
    assert t.splitlines() == ["IGUAL MANEJO (DR. DAZA PEREZ JUAN 16/10/2026)", "DIETA LIQUIDA", "OMEPRAZOL 20 MG",
                              "CEFAZOLINA 1G — 1 G IV C/8H"]
    assert construir_tratamiento("1. x", o, "viejo") == "PLAN\n1. X"

def test_emparejar():
    assert emparejar("Juan  Pérez", ["PEREZ GOMEZ JUAN CARLOS", "OTRO NOMBRE"]) == "PEREZ GOMEZ JUAN CARLOS"
    assert emparejar("Ana Liñán", ["LOPEZ RUIZ MARIA"]) is None

HTML = """<html><body><p>URGENCIAS 47</p>
<table><tr><td><p>DATOS</p></td><td>DX</td><td>EVOLUCIÓN</td><td>TRATAMIENTO</td><td>LAB</td><td>IMG</td><td>PEND</td></tr>
<tr><td><p>JUAN PEREZ</p><p>H-1</p></td><td>HTA</td><td>viejo</td><td>nada</td><td></td><td></td><td></td></tr></table>
<h2>PISO 3</h2><table><tr><td>DATOS</td></tr><tr><td>X Y</td></tr></table></body></html>"""

def test_html_y_comparar():
    filas = parsear_kardex_html(HTML)
    assert len(filas) == 2 and filas[0].servicio == "URGENCIAS 47"
    assert filas[0].nombre == "JUAN PEREZ" and filas[0].habitacion == "H-1"
    assert filas[1].servicio == "PISO 3"
    p = PacienteSistema("PEREZ GOMEZ JUAN", "H-2", "Hospitalización", dx="COLECISTITIS",
                        evolucion="e", tratamiento="t", encontrado_detalle=True)
    q = PacienteSistema("NUEVA PACIENTE UNO", "H-9", "Urgencias")
    acc = comparar([p, q], filas)
    tipos = [(a.tipo, a.campo) for a in acc]
    assert ("ACTUALIZAR", "DX") in tipos and ("REVISAR", "HABITACIÓN") in tipos
    assert any(a.tipo == "AGREGAR" for a in acc) and any(a.tipo == "RETIRAR" for a in acc)
