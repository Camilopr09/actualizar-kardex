"""Columna IMAGENES / NOTAS: fechas, títulos, bloques, detección de lo que ya está e inserción en la celda.
Datos inventados."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from notas import (EstudioImagen, bloque_imagen, es_subtitulo_imagenes, fecha_corta, imagen_ya_esta, imagenes_nuevas,
                   insertar_imagenes, lineas_titulo_imagen, punto_insercion_imagenes, titulo_imagen, unir_bloques)

DORSAL = EstudioImagen("19/10/26", "ECOGRAFÍA", "TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA",
                       "Engrosamiento cutáneo\nÁreas líquidas que sugieren colección", "7")


def test_fecha_corta():
    for t in ("19 DE OCTUBRE DEL 2026", "19 de octubre de 2026", "19/10/2026", "19/10/26", "2026-10-19",
              "19/10/2026 16:38:38", "19 Oct 2026", "  19-10-2026  ", "19.10.2026", "2026-10-19 16:38", "9/10/26 hora"):
        esperado = "09/10/26" if t.startswith("9/") else "19/10/26"
        assert fecha_corta(t) == esperado, t
    assert fecha_corta("1 de enero de 2027") == "01/01/27" and fecha_corta("31 DE DICIEMBRE DEL 2026") == "31/12/26"
    assert fecha_corta("", "19/10/2026 16:38:38") == "19/10/26"                  # respaldo: la Fecha Hora de la grilla
    assert fecha_corta("sin fecha", "19/10/2026") == "19/10/26" and fecha_corta("nada", "tampoco") == ""
    assert fecha_corta("32/13/2026") == "" and fecha_corta(None) == ""


def test_titulo_con_tipo_y_abreviaturas():
    assert titulo_imagen(DORSAL) == "ECOGRAFÍA TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA 19/10/26"
    e = lambda tipo, estudio: titulo_imagen(EstudioImagen("16/10/26", tipo, estudio))
    assert e("ECOGRAFÍA", "ECOGRAFIA DE ABDOMEN") == "ECOGRAFIA DE ABDOMEN 16/10/26"           # ya empieza por el tipo
    assert e("ECOGRAFÍA", "eco tejidos blandos fosa iliaca derecha") == "ECO TEJIDOS BLANDOS FOSA ILIACA DERECHA 16/10/26"
    assert e("TOMOGRAFÍA", "TAC DE ABDOMEN SIMPLE") == "TAC DE ABDOMEN SIMPLE 16/10/26"
    assert e("TAC", "TOMOGRAFIA DE TORAX") == "TOMOGRAFIA DE TORAX 16/10/26"
    assert e("RADIOGRAFÍA", "RX DE TORAX") == "RX DE TORAX 16/10/26" and e("RX", "radiografia de mano") == "RADIOGRAFIA DE MANO 16/10/26"
    assert e("RESONANCIA", "RMN DE COLUMNA") == "RMN DE COLUMNA 16/10/26"
    assert e("ECOGRAFÍA", "DOPPLER VENOSO DE MIEMBROS INFERIORES") == "ECOGRAFÍA DOPPLER VENOSO DE MIEMBROS INFERIORES 16/10/26"
    assert e("ECOGRAFÍA", "ABDOMEN TOTAL:  ") == "ECOGRAFÍA ABDOMEN TOTAL 16/10/26"           # sin «:» y sin «DE»
    assert e("", "ABDOMEN") == "ABDOMEN 16/10/26" and e("ECOGRAFÍA", "") == "ECOGRAFÍA 16/10/26"
    assert titulo_imagen(EstudioImagen("", "ECOGRAFÍA", "RENAL")) == "ECOGRAFÍA RENAL"       # sin fecha no se agrega nada
    assert e("TAC", "  ecografia   renal  ") == "TAC ECOGRAFIA RENAL 16/10/26"                 # otro tipo: se antepone


def test_bloque_deja_el_informe_tal_cual():
    b = bloque_imagen(DORSAL)
    assert b == ("ECOGRAFÍA TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA 19/10/26\n"
                 "Engrosamiento cutáneo\nÁreas líquidas que sugieren colección")
    sucio = EstudioImagen("19/10/26", "ECOGRAFÍA", "RENAL", "\n\nHallazgo uno   \r\n\n\n\nOPINION: normal  \n\n")
    assert bloque_imagen(sucio) == "ECOGRAFÍA RENAL 19/10/26\nHallazgo uno\n\nOPINION: normal"
    assert bloque_imagen(EstudioImagen("19/10/26", "ECOGRAFÍA", "RENAL", "  \n ")) == "ECOGRAFÍA RENAL 19/10/26"
    assert unir_bloques([DORSAL, sucio]) == b + "\n\n" + bloque_imagen(sucio)


def test_imagen_ya_esta_por_titulo_texto_o_fecha_y_palabras():
    # (a) el título está (sin importar tildes, mayúsculas ni espacios)
    assert imagen_ya_esta(DORSAL, "ecografia tejidos  blandos en la region dorsal linea media 19/10/26\nlo que sea")
    # (b) los primeros ~60 caracteres del informe
    celda = "NOTA\nEngrosamiento cutáneo Áreas líquidas que sugieren colección\nmás"
    assert imagen_ya_esta(DORSAL, celda)
    # (c) un renglón con la fecha y 2 palabras del estudio
    for fecha in ("19/10/26", "19/10/2026", "19-10-2026", "19-10-26", "19/10", "19.10.26"):
        assert imagen_ya_esta(DORSAL, f"ECO TEJIDOS BLANDOS DORSAL {fecha}"), fecha
    # no está: otra fecha, otro año, una sola palabra, palabras en otro renglón, celda vacía
    assert not imagen_ya_esta(DORSAL, "ECO TEJIDOS BLANDOS DORSAL 18/10/26")
    assert not imagen_ya_esta(DORSAL, "ECO TEJIDOS BLANDOS DORSAL 19/10/25")
    assert not imagen_ya_esta(DORSAL, "ECO DORSAL 19/10/26")
    assert not imagen_ya_esta(DORSAL, "TEJIDOS BLANDOS DORSAL\n19/10/26")
    assert not imagen_ya_esta(DORSAL, "") and not imagen_ya_esta(DORSAL, None)
    corto = EstudioImagen("19/10/26", "ECOGRAFÍA", "ABDOMEN", "ok")                  # un informe corto no cuenta como (b)
    assert not imagen_ya_esta(corto, "ok") and imagen_ya_esta(corto, "ECO ABDOMEN 19/10/26")
    assert not imagen_ya_esta(corto, "ECO ABDOMEN 5/10/26")
    dia1 = EstudioImagen("05/10/26", "ECOGRAFÍA", "TEJIDOS BLANDOS DORSAL", "")
    assert imagen_ya_esta(dia1, "ECO TEJIDOS BLANDOS DORSAL 5/10/2026") and not imagen_ya_esta(dia1, "ECO TEJIDOS BLANDOS DORSAL 15/10/26")


def test_imagenes_nuevas_sin_repetidos_y_de_la_mas_reciente_a_la_mas_antigua():
    a = EstudioImagen("13/10/26", "ECOGRAFÍA", "ABDOMEN TOTAL", "informe a", "3")
    b = EstudioImagen("16/10/26", "TAC", "TAC DE ABDOMEN SIMPLE", "informe b", "5")
    c = EstudioImagen("16/10/26", "RADIOGRAFÍA", "RX DE TORAX", "informe c", "6")
    repetido = EstudioImagen("16/10/26", "TAC", "TAC DE ABDOMEN SIMPLE", "otra copia del mismo", "4")
    sin_fecha = EstudioImagen("", "ECOGRAFÍA", "PELVICA", "x", "1")
    nuevos = imagenes_nuevas([a, b, c, repetido, sin_fecha], "")
    assert nuevos == [c, b, a, sin_fecha]                       # por fecha y, el mismo día, por N° de formato
    assert imagenes_nuevas([a, b, c], "TAC DE ABDOMEN SIMPLE 16/10/26\nCONCLUSIÓN: algo\n\nECOGRAFIA ABDOMEN TOTAL 13/10/2026") == [c]
    assert imagenes_nuevas([], "x") == [] and imagenes_nuevas(None, "x") == []
    assert imagenes_nuevas([a, b, c], unir_bloques([a, b, c])) == []


def test_subtitulo_y_punto_de_insercion():
    for t in ("IMÁGENES", "imagenes", "IMÁGENES Y PROCEDIMIENTO", "IMAGENES:", "Imágenes y procedimientos"):
        assert es_subtitulo_imagenes(t), t
    for t in ("IMAGENES DE ABDOMEN 10/10/26", "TAC DE ABDOMEN 10/10/26", "IMÁGENES ESTUDIADAS EN LA CLINICA DEL PACIENTE HOY", ""):
        assert not es_subtitulo_imagenes(t), t
    assert punto_insercion_imagenes(["IMÁGENES", "TAC 10/10/26", "x"]) == 1
    assert punto_insercion_imagenes(["nota", "IMÁGENES Y PROCEDIMIENTO", "x"]) == 2
    assert punto_insercion_imagenes(["TAC 10/10/26", "x"]) == 0 and punto_insercion_imagenes([""]) == 0


def test_insertar_arriba_o_bajo_el_subtitulo():
    ins = unir_bloques([DORSAL])
    assert insertar_imagenes("", ins) == ins
    assert insertar_imagenes("TAC DE ABDOMEN 10/10/26\nCONCLUSIÓN: x", ins) == ins + "\n\nTAC DE ABDOMEN 10/10/26\nCONCLUSIÓN: x"
    assert insertar_imagenes("IMÁGENES\nTAC 10/10/26", ins) == "IMÁGENES\n" + ins + "\n\nTAC 10/10/26"
    assert insertar_imagenes("IMÁGENES", ins) == "IMÁGENES\n" + ins                  # nada debajo: sin renglón vacío
    assert insertar_imagenes("nota a mano\nIMÁGENES\n", ins) == "nota a mano\nIMÁGENES\n" + ins


def test_lineas_titulo():
    dos = unir_bloques([DORSAL, EstudioImagen("17/10/26", "TAC", "TAC DE ABDOMEN SIMPLE", "CONCLUSIÓN: sin hallazgos\n\nOtro párrafo")])
    lineas = dos.split("\n")
    assert lineas_titulo_imagen(dos) == {0, lineas.index("TAC DE ABDOMEN SIMPLE 17/10/26")}
    # un párrafo del informe en MAYÚSCULAS que no termina en fecha no se confunde con un título
    otro = unir_bloques([EstudioImagen("17/10/26", "TAC", "TAC DE ABDOMEN", "HALLAZGOS\n\nSIN COMPLICACIONES")])
    assert lineas_titulo_imagen(otro) == {0}
