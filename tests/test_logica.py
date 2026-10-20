import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from notas import extraer_dx, interpretar_evolucion, interpretar_ordenes, construir_tratamiento, es_igual_manejo
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


DX_B = ("EVOLUCION UCI/ AM\n\n- SHOCK DISTRIBUTIVO/ HIPOVOLÉMICO\nEN VMI\n- SEPSIS FOCO BILIAR\n"
        "- INJURIA REAN AGUDA EN TERAPIA DE HEMODIAFILTRACION (INICIO 18/10/26)\n- TUMOR DE AMPOLLA DE VATTER CON\n"
        "MTS HEPATICA DE RECIENTE\nDIAGNÓSTICO\n- SINDROME COLEDOCIANO\n/COLESTASIS SEVERA\n"
        "- POST DE DRENAJE BILIAR INTERNO -\nEXTERNO + DILATACIÓN PERCUTÁNEA\nDE LA AMPOLLA Y DEL CONDUCTO\n"
        "BILIAR (13/10/26)\n- FALLA RENAL CRONICA AGUDIZADA")


def test_extraer_dx_sin_titulos_y_vacio():
    assert extraer_dx("1. colecistopatia a descartar\n2. NEFROLITIASIS IZQUIERDA\n3. COLITIS") == (
        "1. COLECISTOPATIA A DESCARTAR\n2. NEFROLITIASIS IZQUIERDA\n3. COLITIS")
    assert extraer_dx("HTA\n\nDM2\n") == "HTA\nDM2"            # sin marcadores: un renglón por diagnóstico
    assert extraer_dx("") == "" and extraer_dx(None) == "" and extraer_dx("  \n \n") == ""


def test_extraer_dx_caso_b_solo_despues_del_encabezado():
    assert extraer_dx(DX_B).splitlines() == [
        "- SINDROME COLEDOCIANO /COLESTASIS SEVERA",
        "- POST DE DRENAJE BILIAR INTERNO - EXTERNO + DILATACIÓN PERCUTÁNEA DE LA AMPOLLA Y DEL CONDUCTO BILIAR (13/10/26)",
        "- FALLA RENAL CRONICA AGUDIZADA"]


def test_extraer_dx_titulo_de_otra_cosa_sin_encabezado():
    assert extraer_dx("NOTA MEDICA\n1. HTA\n2. DM2") == "1. HTA\n2. DM2"
    assert extraer_dx("RONDA AM\n- A\n- B\nPLAN: X") == "- A\n- B"      # sección de otro tipo al final se quita
    assert extraer_dx("EVOLUCION UCI/ AM\n\n- A\nEN VMI\n- B") == "- A EN VMI\n- B"


def test_extraer_dx_encabezado_toma_solo_su_seccion():
    assert extraer_dx("IDX:\n1. HTA\n2. DM2\nEVOLUCION:\nPACIENTE BIEN\nPLAN: X") == "1. HTA\n2. DM2"
    assert extraer_dx("IDX: 1. HTA 2. DM2\nEVOLUCION: BIEN") == "1. HTA\n2. DM2"
    assert extraer_dx("DX: 1. HTA\nANALISIS: X") == "1. HTA"                  # «DX: …» en la misma línea
    assert extraer_dx("EVOLUCION: BIEN\nDIAGNOSTICOS\n- A\n- B\nPLAN\n- C") == "- A\n- B"
    assert extraer_dx("S: DOLOR\n\nDIAGNÓSTICO:\n1. A\nEXAMEN FISICO: x") == "1. A"
    assert extraer_dx("DX:") == ""


def test_extraer_dx_encabezado_siempre_es_encabezado_y_gana_el_ultimo():
    assert extraer_dx("- TUMOR DE RECIENTE\nDIAGNOSTICO\n- FALLA") == "- FALLA"
    assert extraer_dx("DX: 1. A\nPLAN: X\nIDX:\n1. B") == "1. B"
    assert extraer_dx("impresion diagnostica\n- A") == "- A"
