"""El documento falso de la API de Docs tiene que ser fiel: estas pruebas fijan las reglas de la API real que
las pruebas de escritura (test_escritura.py) dan por hechas."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

from docs_falso import DocumentoFalso, ErrorFalso, P, celda, tabla


def _doc():
    return DocumentoFalso([P("Hola"), tabla([["A\nB", "C"], ["", "D 🙂 E"]]), P("fin")])


def _ins(i, t):
    return {"insertText": {"location": {"index": i}, "text": t}}


def _borrar(a, b):
    return {"deleteContentRange": {"range": {"startIndex": a, "endIndex": b}}}


def test_indices_utf16_y_marcadores_de_tabla():
    c = _doc().a_json()["body"]["content"]
    assert c[0]["sectionBreak"] is not None and (c[1]["startIndex"], c[1]["endIndex"]) == (1, 6)      # «Hola\n»
    t = c[2]
    assert t["startIndex"] == 6
    f0, f1 = t["table"]["tableRows"]
    assert f0["startIndex"] == 7 and f0["tableCells"][0]["startIndex"] == 8
    assert f0["tableCells"][0]["content"][0]["startIndex"] == 9                  # tabla, fila y celda: 1 marcador cada uno
    assert [x["startIndex"] for x in f0["tableCells"][0]["content"]] == [9, 11]  # «A\n» y «B\n»
    assert f0["tableCells"][1]["startIndex"] == 13 and f0["endIndex"] == 16 and f1["startIndex"] == 16
    celda_emoji = f1["tableCells"][1]
    par = celda_emoji["content"][0]
    assert par["endIndex"] - par["startIndex"] == len("D 🙂 E") + 1 + 1               # el emoji ocupa 2 unidades
    assert t["endIndex"] == c[3]["startIndex"] == f1["endIndex"]
    assert c[3]["paragraph"]["elements"][0]["textRun"]["content"] == "fin\n"


def test_cada_celda_termina_en_salto_y_las_nuevas_filas_traen_un_parrafo_vacio():
    d = _doc()
    assert d.texto(0, 0, 0) == "A\nB" and d.parrafos(0, 1, 0)[0].chars == [["\n", {}]]
    t = d.a_json()["body"]["content"][2]["startIndex"]
    d.batch_update([{"insertTableRow": {"tableCellLocation": {"tableStartLocation": {"index": t}, "rowIndex": 1,
                                                                "columnIndex": 0}, "insertBelow": True}}])
    assert len(d.tablas()[0].filas) == 3 and d.fila(0, 2) == ["", ""]
    d.batch_update([{"deleteTableRow": {"tableCellLocation": {"tableStartLocation": {"index": t}, "rowIndex": 0,
                                                                "columnIndex": 0}}}])
    assert len(d.tablas()[0].filas) == 2 and d.fila(0, 0) == ["", "D 🙂 E"]


@pytest.mark.parametrize("pedido", [
    _ins(6, "x"), _ins(7, "x"), _ins(8, "x"),                    # marcadores de tabla, fila y celda
    _ins(500, "x"), _ins(9, ""),
    _borrar(9, 9), _borrar(10, 9),                               # rango vacío / invertido
])
def test_pedidos_invalidos_se_rechazan(pedido):
    d = _doc()
    with pytest.raises(ErrorFalso):
        d.batch_update([pedido])


def test_borrar_un_salto_une_los_parrafos_de_la_celda():
    d = _doc()
    d.batch_update([_borrar(9, 12)])                             # «A\n» y la «B» de «B\n»: queda un solo párrafo
    assert d.texto(0, 0, 0) == "" and len(d.parrafos(0, 0, 0)) == 1
    d = _doc()
    d.batch_update([_borrar(10, 11)])                            # solo el «\n» de «A\n»: «AB»
    assert d.texto(0, 0, 0) == "AB"


def test_borrados_que_la_api_no_permite():
    d = _doc()
    with pytest.raises(ErrorFalso):
        d.batch_update([_borrar(11, 13)])                        # el último «\n» de la celda
    with pytest.raises(ErrorFalso):
        d.batch_update([_borrar(10, 15)])                        # cruza de celda
    with pytest.raises(ErrorFalso):
        d.batch_update([_borrar(3, 8)])                          # cruza la tabla
    with pytest.raises(ErrorFalso):
        d.batch_update([_borrar(1, 6)])                          # el «\n» justo antes de una tabla
    # el emoji no se puede partir por la mitad
    inicio = d.a_json()["body"]["content"][2]["table"]["tableRows"][1]["tableCells"][1]["content"][0]["startIndex"]
    with pytest.raises(ErrorFalso):
        d.batch_update([_ins(inicio + 3, "x")])
    d.batch_update([_ins(inicio + 4, "x")])                      # después del emoji sí
    assert d.texto(0, 1, 1) == "D 🙂x E"


def test_el_lote_es_atomico_y_se_aplica_en_orden():
    d = _doc()
    with pytest.raises(ErrorFalso):
        d.batch_update([_ins(9, "uno"), _ins(9999, "no")])
    assert d.texto(0, 0, 0) == "A\nB" and d.lotes == []           # no quedó el primero
    d.batch_update([_ins(9, "uno"), _ins(9 + 3, "dos")])           # el segundo ve el efecto del primero
    assert d.texto(0, 0, 0) == "unodosA\nB"


def test_estilo_del_texto_insertado():
    d = DocumentoFalso([P("x"), tabla([[celda("", parrafos=[P(("AB", {"bold": True}), ("CD", {"italic": True}))])]])])
    ini = d.a_json()["body"]["content"][2]["table"]["tableRows"][0]["tableCells"][0]["content"][0]["startIndex"]
    d.batch_update([_ins(ini + 2, "_")])                          # entre AB y CD: hereda del anterior
    assert d.estilo_de(0, 0, 0, "_") == {"bold": True}
    d.batch_update([_ins(ini, "!")])                               # al inicio del párrafo: del siguiente
    assert d.estilo_de(0, 0, 0, "!") == {"bold": True}
    d.batch_update([_ins(ini + 1, "\n")])                          # un «\n» parte el párrafo
    assert d.texto(0, 0, 0) == "!\nAB_CD"


def test_update_text_style_con_fields():
    d = DocumentoFalso([P("x"), tabla([[celda("", parrafos=[P(("ABCD", {"bold": True, "italic": True,
                                                                  "backgroundColor": {"color": {}}}))])]])])
    ini = d.a_json()["body"]["content"][2]["table"]["tableRows"][0]["tableCells"][0]["content"][0]["startIndex"]
    estilo = lambda a, b, ts, f: {"updateTextStyle": {"range": {"startIndex": a, "endIndex": b}, "textStyle": ts, "fields": f}}
    d.batch_update([estilo(ini, ini + 2, {"bold": False}, "bold,backgroundColor")])    # lo que está en fields y no en el estilo se borra
    assert d.estilo_de(0, 0, 0, "AB") == {"bold": False, "italic": True}
    assert d.estilo_de(0, 0, 0, "CD") == {"bold": True, "italic": True, "backgroundColor": {"color": {}}}
    d.batch_update([estilo(ini + 2, ini + 4, {"fontSize": {"magnitude": 8, "unit": "PT"}}, "*")])    # «*» reemplaza todo
    assert d.estilo_de(0, 0, 0, "CD") == {"fontSize": {"magnitude": 8, "unit": "PT"}}
    with pytest.raises(ErrorFalso):
        d.batch_update([estilo(ini, ini + 1, {}, "inventado")])
    with pytest.raises(ErrorFalso):
        d.batch_update([estilo(ini, ini + 1, {}, "")])
    d.batch_update([{"updateParagraphStyle": {"range": {"startIndex": ini, "endIndex": ini + 1},
                                                "paragraphStyle": {"alignment": "CENTER"}, "fields": "alignment"}}])
    assert d.alineaciones(0, 0, 0) == ["CENTER"]
    with pytest.raises(ErrorFalso):
        d.batch_update([{"replaceAllText": {}}])                 # lo que kardex_doc no usa no existe en el falso
