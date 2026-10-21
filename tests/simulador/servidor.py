"""Simulador de Hospital Office (eHC «Historias Clínicas.Net», ASP.NET + DevExpress) y del kardex exportado
(solo librería estándar, datos inventados). Imita lo que describen las capturas de la clínica:
  * /Login.aspx: logo eHC, campo de usuario con texto guía «Usuario» (watermark en el value), contraseña vacía y
    botón ENTRAR que es una IMAGEN sin texto (`input[type=image]`; variantes: imagen dentro de un enlace, o sin
    botón y solo Enter). Pone una cookie de sesión (sin expires) y lleva a /Dashboard.aspx.
  * /Dashboard.aspx: «DashBoard del Usuario», «NOMBRE DEL MEDICO(Salir)» y menú lateral ACORDEÓN (Menu Principal,
    Consultas, Historia Externa, Parametros, Unidades Funcionales, Pacientes, Ayuda), plegado. «Menu Principal»
    despliega «Inicio» y «Atencion de Pacientes» (pulsarlo de nuevo lo pliega).
  * «Atencion de Pacientes» -> /AtencionPacientes.aspx (= /Agenda.aspx una vez pasado por el menú): radios
    Urgencias / Hospitalización, casilla «Últimas 24 horas.», botón «Actualizar» (SIN pulsarlo la grilla no cambia),
    grilla «Pacientes Por Atender» (Paciente | Identificacion | Admision | Convenio | Habitacion | Estado | Acción)
    con fila de filtros, paginación de 10 filas y TODO el hospital. Opcionalmente (con_atendidos) una grilla de
    atendidos más abajo (en el sistema real NO existe; sirve para probar el respaldo).
  * Stub de ASPxClientControl.GetControlCollection().elements[id]: InCallback, AutoFilterByColumn («empieza con»),
    GetColumnsCount/GetColumn, GetPageCount/GotoPage y el pager con ASPx.GVPagerOnClick(..., 'PBN').
  * /HistoriaClinica.aspx: grilla de formatos (paginada de 10 en 10, con el resumen «Page 1 of 2 (18 items)»);
    «Ver» llena los textareas tras un pequeño retardo. Los «INFORME DE IMAGENOLOGIA» tienen las pestañas EXAMEN
    (fecha, tipo de estudio, estudio y el informe en un textarea SIN etiqueta) y «DESCRIPCIÓN DEL EXAMEN» (vacía).
  * /kardex: kardex exportado (HTML de Google Docs, simplificado).
  * /entregas/<n>: documentos de «ENTREGAS» exportados (n = 1, 2…; `Simulador.entregas` da nombre y URL de cada uno).
La sesión puede «vencer» tras N peticiones protegidas.
Variantes (parámetros de Simulador): login_realista (usuario con texto guía, contraseña type=text que pasa a password
al enfocar, botón input[type=image] src=/img/entrar.png sin alt ni value, URL de login SIN la palabra «login»),
iframe (menú y contenido dentro de un iframe del Dashboard), sin_titulo (grilla sin el título «Pacientes Por
Atender» y con otro id: solo encabezados), icono_en_cabecera (texto de la cabecera en un span con un <img> al lado) y
agenda_redirige (url_agenda redirige al Dashboard aunque haya sesión). Grilla de formatos: filtro_formatos
(«contiene», «empieza» con o «ninguno» = AutoFilterByColumn no hace nada) y tam_formatos (filas por página).
"""
import base64
import html
import json
import threading
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USUARIO = "medico.prueba"
CLAVE = "Clave-Inventada-123"

GRID_PEND = "ctl00_cph1_cbpPanel1_grdPendientes"
GRID_ATEN = "ctl00_cph1_cbpPanel1_grdAtendidos"
GRID_FORM = "ctl00_cph1_ASPxRoundPanel2_grdFormatos"

# --------------------------------------------------------------------------- datos inventados
# (id, nombre «NOMBRES APELLIDOS», tipo, documento, habitación del sistema, modo, pendiente, visible con «Últimas 24 h»)
PRINCIPALES = [
    (1, "PEDRO PABLO ALVARADO RUIZ", "CC", "1020304051", "6PISO-607", "Hospitalización", True, True),
    (2, "SOFIA BENAVIDES LUNA", "CC", "1020304052", "4PISO-426", "Hospitalización", True, True),
    (3, "TOMAS CORREA MEJIA", "CC", "1020304053", "HOS82-12", "Urgencias", True, True),
    (4, "MARIA ELENA DUQUE SALAS", "CC", "1020304054", "3PISO-305B", "Hospitalización", True, True),
    (5, "IVAN ESCOBAR TRUJILLO", "CC", "1020304055", "H4CAM-09", "Urgencias", True, False),   # solo sin el filtro de 24 h
    (6, "LAURA GUTIERREZ OSORIO", "TI", "1020304056", "4PISO-408", "Hospitalización", True, True),
    (7, "JAIRO ANDRES MONTENEGRO VEGA", "CC", "1020304057", "PEDIA-07", "Hospitalización", True, True),
    (8, "ROSARIO QUIJANO LOPEZ", "RC", "1020304058", "3PISO-311", "Hospitalización", False, True),  # solo en atendidos
    (9, "ELSA MARINA ROJAS DIAZ", "CC", "1020304059", "H4CAM-03", "Urgencias", True, True),      # tocaya de una del kardex
    (10, "PEDRO NEL SIERRA CANO", "CC", "1020304060", "6PISO-612", "Hospitalización", True, True),   # tocayo
]
_NOM = ["ANA LUCIA", "BEATRIZ HELENA", "CAMILO ANDRES", "DIEGO FERNANDO", "EDGAR MAURICIO", "FABIOLA", "GLORIA INES",
        "HUMBERTO", "ISABEL CRISTINA", "JULIAN DAVID", "KATERINE", "LUIS ALBERTO", "MONICA PATRICIA", "NESTOR RAUL",
        "OLGA LUCIA", "PABLO EMILIO", "RAQUEL", "SANDRA MILENA", "TERESA", "VICTOR MANUEL", "WILSON", "YOLANDA",
        "ZULMA", "ADRIANA", "BRAYAN STIVEN", "CLARA ROSA", "DANIELA", "ERNESTO", "FLOR ALBA", "GUSTAVO ADOLFO",
        "HILDA", "IGNACIO"]
_APE = ["ARIAS PINEDA", "BELTRAN OCHOA", "CARRILLO MORA", "DELGADO PAEZ", "ESPINOSA RIOS", "FORERO LEAL",
        "GALINDO SOTO", "HERRERA VARGAS", "JARAMILLO CRUZ", "LONDOÑO PRADA", "MARTELO SILVA", "NAVARRO TELLO",
        "OREJUELA RUA", "PARRA CUESTA", "QUESADA BRAVO", "ROMERO LUGO"]
_HAB = ["6PISO-60%d", "4PISO-42%d", "3PISO-30%dB", "HOS82-0%d", "H4CAM-0%d", "PEDIA-0%d", "5PISO-51%d"]
_TIPOS = ["CC", "CC", "CC", "RC", "TI"]


def _rellenos():
    out = []
    for k in range(32):
        nombre = f"{_NOM[k]} {_APE[k % len(_APE)]}"
        hab = _HAB[k % len(_HAB)] % (k % 9 + 1)
        modo = "Urgencias" if k % 3 == 0 else "Hospitalización"
        out.append((100 + k, nombre, _TIPOS[k % len(_TIPOS)], f"10{70000000 + k * 7919:08d}", hab, modo, True, k % 4 != 3))
    return out


PACIENTES = PRINCIPALES + _rellenos()

EVOL = "HOJA DE EVOLUCION"
ORDEN = "ORDEN MEDICA"


def _nota(dx, plan, analisis="-MEDICINA INTERNA-\nEVOLUCION FAVORABLE", sintomas="", examen="ALERTA, SIN DOLOR"):
    """Hoja de evolución estructurada: el texto de cada pestaña del «Detalle del Formato»."""
    return {"dx": dx, "plan": plan, "analisis": analisis, "sintomas": sintomas, "examen": examen}


# DX tipo (b): evolución primero y, tras el renglón «DIAGNÓSTICO», los diagnósticos partidos en varios renglones
DX_UCI = ("EVOLUCION UCI/ AM\n\n- SHOCK DISTRIBUTIVO/ HIPOVOLÉMICO\nEN VMI\n- SEPSIS FOCO BILIAR\n"
          "- INSUFICIENCIA HEPATICA GRAVE/\nCHILD-PUGH C\n- TUMOR DE AMPOLLA DE VATTER CON\nMTS HEPATICA DE RECIENTE\n"
          "DIAGNÓSTICO\n- SINDROME COLEDOCIANO\n/COLESTASIS SEVERA\n- POST DE DRENAJE BILIAR INTERNO -\n"
          "EXTERNO + DILATACIÓN PERCUTÁNEA\nDE LA AMPOLLA Y DEL CONDUCTO\nBILIAR (13/10/26)\n- FALLA RENAL CRONICA AGUDIZADA")

# id paciente -> lista de formatos (formato, fecha hora, estado, usuario, detalle: dict de pestañas o texto de la orden)
FORMATOS = {
    1: [(EVOL, "18/10/2026 07:00", "Finalizado", "DAZA PEREZ JUAN",
         _nota("1. COLECISTITIS AGUDA", "1. NVO 2. CEFAZOLINA 1 G IV C/8H")),
        (EVOL, "19/10/2026 09:10", "Finalizado", "LOPEZ RUIZ ANA (ENFERMERIA)",
         _nota("1. OTRO DX NO ESPECIALISTA", "1. NO DEBE LEERSE")),
        (EVOL, "19/10/2026 06:30", "Finalizado", "DAZA PEREZ JUAN",
         _nota("1. COLECISTITIS AGUDA\n2. HTA", "1. DIETA LIQUIDA 2. CEFAZOLINA 1 G IV C/8H 3. OMEPRAZOL 40 MG IV C/24H")),
        (ORDEN, "19/10/2026 06:35", "Finalizado", "DAZA PEREZ JUAN",
         "DIETA LIQUIDA\nFórmula #1\n1) CEFAZOLINA 1G Cantidad: 3 Dosis: 1 g IV c/8h\n")],
    2: [(EVOL, "19/10/2026 07:20", "Finalizado", "FABIAN GOMEZ LUIS",
         _nota("NEUMONIA ADQUIRIDA EN LA COMUNIDAD", "IGUAL MANEJO")),
        (ORDEN, "19/10/2026 07:25", "Finalizado", "FABIAN GOMEZ LUIS",
         "DIETA BLANDA\n1) CEFTRIAXONA 2 G Cantidad: 2 Dosis: 2 g IV c/24h\n2) ENOXAPARINA 40 MG Cantidad: 1 Dosis: 40 mg SC c/24h\n")],
    3: [(EVOL, "19/10/2026 08:00", "Finalizado", "EMILIANI RUEDA CARLOS",
         _nota("PIELONEFRITIS AGUDA", "1. DIETA BLANDA 2. CIPROFLOXACINO 400 MG IV C/12H"))],
    4: [(EVOL, "19/10/2026 05:40", "Finalizado", "TORRES NIETO ROSA (AUXILIAR)",
         _nota("1. CELULITIS DE MIEMBRO INFERIOR", "1. DIETA NORMAL"))],
    5: [(EVOL, "19/10/2026 06:50", "Finalizado", "DAZA PEREZ JUAN",
         _nota("1. PANCREATITIS AGUDA\n2. COLELITIASIS\n3. DM2", "1. NVO",
               analisis="", sintomas="DOLOR ABDOMINAL", examen="ABDOMEN BLANDO"))],      # ANALISIS vacío
    7: [(EVOL, "19/10/2026 07:45", "Finalizado", "DAZA PEREZ JUAN", _nota(DX_UCI, "1. DIETA NORMAL 2. CEFTRIAXONA 2 G IV C/24H"))],
    6: [(EVOL, "19/10/2026 08:30", "Finalizado", "FABIAN GOMEZ LUIS",
         _nota("IDX:\n1. APENDICITIS AGUDA COMPLICADA\nEVOLUCION:\nPACIENTE CON DOLOR, SIN FIEBRE",
               "1. DIETA LIQUIDA 2. CEFAZOLINA 1 G IV C/8H"))],
}

# ---- informes de imagenología (pestañas EXAMEN y «DESCRIPCIÓN DEL EXAMEN», esta vacía) y formatos de relleno
IMG = "INFORME DE IMAGENOLOGIA"
USUARIO_IMG = "VARGAS LEAL PAULA"


def _informe(fecha, tipo, estudio, texto):
    """Detalle de un «INFORME DE IMAGENOLOGIA». EXAMEN: fecha del estudio (textarea), tipo (combo de solo lectura),
    estudio (textarea) y el informe (textarea SIN etiqueta, en la celda de la derecha de una celda vacía)."""
    return {"informe": {"fecha": fecha, "tipo": tipo, "estudio": estudio, "texto": texto}}


_RELLENOS = ["NOTA DE ENFERMERIA", "CONTROL DE SIGNOS VITALES", "ESCALA DE BRADEN", "BALANCE DE LIQUIDOS"]


def _relleno(desde, n):
    """n formatos que no son evolución, órdenes ni imágenes (para que la grilla de formatos tenga varias páginas)."""
    return [(_RELLENOS[k % len(_RELLENOS)], f"18/10/2026 {(desde + k) % 24:02d}:15", "Finalizado",
             "TORRES NIETO ROSA (AUXILIAR)", "SIN NOVEDADES") for k in range(n)]


# ALVARADO (en el kardex): 2 informes; el más antiguo va primero en la grilla
FORMATOS[1] += [
    (IMG, "17/10/2026 09:12:45", "Finalizado", USUARIO_IMG,
     _informe("17 de octubre de 2026", "TOMOGRAFÍA", "ABDOMEN SIMPLE",
              "CONCLUSIÓN: -Hallazgos compatibles con proceso infeccioso de la vesícula biliar.\n"
              "-Líquido libre en pelvis en mínima cantidad.")),
    (IMG, "19/10/2026 16:38:38", "Finalizado", USUARIO_IMG,
     _informe("19 DE OCTUBRE DEL 2026", "ECOGRAFÍA", "TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA",
              "Engrosamiento cutáneo\nÁreas líquidas de bordes irregulares, sin tabiques, de 12 x 8 mm.\n"
              "No se observan colecciones organizadas.\nOPINION: Hallazgos compatibles con proceso inflamatorio "
              "de tejidos blandos.")),
]
# BENAVIDES (en el kardex): 18 formatos = 2 páginas de la grilla sin filtrar; un informe en cada página
# (el de la página 1 con la fecha del estudio en blanco: se usa la «Fecha Hora» de la grilla)
FORMATOS[2] += (
    _relleno(6, 4)                                                                                 # 2-5
    + [(IMG, "18/10/2026 11:05:10", "Finalizado", USUARIO_IMG,
        _informe("", "RADIOGRAFÍA", "TORAX PA Y LATERAL",
                 "Infiltrado alveolar en la base derecha.\nSin derrame pleural.\nSilueta cardiaca normal."))]   # 6 (pág. 1)
    + _relleno(8, 6)                                                                               # 7-12
    + [(IMG, "19/10/2026 05:50:00", "Finalizado", USUARIO_IMG,
        _informe("19/10/2026", "ECOGRAFÍA", "ECO RENAL Y DE VIAS URINARIAS",
                 "Con transductor convex de 3.5 Mhz se realiza barrido sonográfico observando:\n"
                 "Riñón derecho de tamaño normal, sin dilatación de la vía urinaria.\n\n"
                 "Riñón izquierdo con quiste cortical de 14 mm.\nOPINION: Quiste renal simple izquierdo."))]   # 13 (pág. 2)
    + _relleno(14, 4))                                                                             # 14-17
assert len(FORMATOS[2]) == 18
# ROJAS DIAZ (Urgencias) y SIERRA CANO (piso 6): están en el sistema y NO en el kardex (las entregas los mencionan)
FORMATOS[9] = [
    (EVOL, "19/10/2026 08:40", "Finalizado", "EMILIANI RUEDA CARLOS",
     _nota("1. ABDOMEN AGUDO EN ESTUDIO\n2. HTA", "1. NADA VIA ORAL 2. LEV SSN 0.9% 100 CC/H")),
    (ORDEN, "19/10/2026 08:45", "Finalizado", "EMILIANI RUEDA CARLOS",
     "NADA VIA ORAL\n1) SOLUCION SALINA 0.9% 1000 CC Cantidad: 4 Dosis: 100 cc/h IV\n"),
    (IMG, "19/10/2026 14:02:11", "Finalizado", USUARIO_IMG,
     _informe("19 de octubre del 2026", "TOMOGRAFÍA", "TAC DE ABDOMEN CON CONTRASTE",
              "CONCLUSIÓN: -Engrosamiento de la pared del apéndice cecal con líquido libre periapendicular.\n"
              "-Hallazgos sugestivos de apendicitis aguda.")),
]
FORMATOS[10] = [
    (EVOL, "19/10/2026 07:10", "Finalizado", "DAZA PEREZ JUAN",
     _nota("1. COLECISTITIS AGUDA LITIASICA\n2. DM2", "1. DIETA CORRIENTE 2. CEFTRIAXONA 2 G IV C/24H")),
    (ORDEN, "19/10/2026 07:15", "Finalizado", "DAZA PEREZ JUAN",
     "DIETA CORRIENTE\n1) CEFTRIAXONA 2G Cantidad: 1 Dosis: 2 g IV c/24h\n"),
    (IMG, "19/10/2026 12:20:31", "Finalizado", USUARIO_IMG,
     _informe("19 DE OCTUBRE DEL 2026", "ECOGRAFÍA", "ABDOMEN TOTAL",
              "Vesícula biliar de paredes engrosadas con litiasis múltiple.\nVía biliar de calibre normal.\n"
              "OPINION: Colecistitis aguda litiásica.")),
]
# BELTRAN OCHOA (relleno 101): 12 informes = 2 páginas incluso con el filtro «IMAGENOLOG» (el más antiguo primero)
_TIPOS_IMG = [("ECOGRAFÍA", "ABDOMEN TOTAL"), ("RADIOGRAFÍA", "TORAX PA"), ("TOMOGRAFÍA", "CRANEO SIMPLE"),
              ("RESONANCIA", "RODILLA DERECHA")]
FORMATOS[101] = [(EVOL, "19/10/2026 06:00", "Finalizado", "DAZA PEREZ JUAN", _nota("1. POLITRAUMA", "1. NVO"))] + [
    (IMG, f"{7 + k:02d}/10/2026 {8 + k:02d}:00:00", "Finalizado", USUARIO_IMG,
     _informe(f"{7 + k} DE OCTUBRE DEL 2026", *_TIPOS_IMG[k % 4], f"Informe inventado {k + 1}.\nSin hallazgos de importancia."))
    for k in range(12)]


# Kardex exportado: (servicio, [(nombre, habitación, dx, evolución, tratamiento, tipo, documento)])
KARDEX = [
    ("PISO 6", [
        ("PEDRO ALVARADO", "607", "COLECISTITIS AGUDA", "17/10/2026 DAZA: EVOLUCION VIEJA", "DIETA LIQUIDA",
         "CC", "1020304051"),                                  # «607» ≡ «6PISO-607»: sin REVISAR de habitación
    ]),
    ("PISO 4", [
        ("SOFIA BENAVIDES LUNA", "426", "NEUMONIA ADQUIRIDA EN LA COMUNIDAD", "ev",
         "NVO\nCEFTRIAXONA 2 G — 2 g IV c/24h", "CC", "1020304052"),
        ("LAURA GUTIERREZ OSORIO", "405", "APENDICITIS AGUDA COMPLICADA", "ev", "x", "TI", "1020304056"),  # sistema: 408
    ]),
    ("URGENCIAS", [
        ("TOMAS CORREA MEJIA", "CUB 12", "PIELONEFRITIS AGUDA",
         "19/10/2026 - DR. EMILIANI RUEDA CARLOS (MEDICINA INTERNA)\nEVOLUCION FAVORABLE",
         "1. DIETA BLANDA 2. CIPROFLOXACINO 400 MG IV C/12H", "CC", "1020304053"),   # igual al sistema: sin acciones
        ("ELSA FIGUEROA PARDO", "CUB 3", "HERNIA INGUINAL", "ev", "DIETA", "CC", "1020309999"),  # no está en el sistema
    ]),
    ("PISO 3", [
        ("MARIA DUQUE SALAS", "305B", "CELULITIS DE MIEMBRO INFERIOR", "ev", "DIETA NORMAL", "CC", "1020304054"),
    ]),
    ("PISO 5", [
        ("IVAN ESCOBAR TRUJILLO", "CUB 9", "PANCREATITIS AGUDA", "ev", "NVO", "CC", "1020304055"),   # está en Urgencias
        ("HERNAN PALACIOS", "PASILLO", "ITU", "ev", "DIETA", "CC", "1020304057"),       # nombre mal: solo el documento coincide
    ]),
]


# Documentos de «ENTREGAS» (solo lectura): (nombre del documento, [(título de la tabla, [fila])]) con
# fila = (habitación, nombre, edad, tipo, documento, DX, EVOLUCIÓN, TRATAMIENTO, LABORATORIOS, IMAGENES / NOTAS,
# PENDIENTES) y None = fila vacía. Cirugía general se menciona en unas filas (de varias maneras) y en otras no.
#   PISO 6:  ALVARADO (está en el kardex; menciona en EVOLUCIÓN), SIERRA CANO (NUEVO: está en el sistema y no en el
#            kardex; menciona en PENDIENTES) y HERRERA (cirugía plástica: no cuenta).
#   URGENCIAS CARRERA 47: CORREA (kardex, sin mención) y ROJAS DIAZ (NUEVA: Urgencias del sistema, no está en el kardex;
#            su habitación del sistema no es de piso, así que el servicio sale del documento).
#   PISO 4C: GUTIERREZ (kardex; menciona) y FORERO (no está en el sistema; cirugía vascular: no cuenta).
ENTREGAS = [
    ("PISO 6", [
        ("PISO 6 ( 3 PACIENTES)", [
            ("607", "PEDRO PABLO ALVARADO RUIZ", "59", "CC", "1020304051", "COLECISTITIS AGUDA",
             "19/10/26 VALORACION POR CIRUGIA GENERAL: PROGRAMAR COLECISTECTOMIA", "DIETA LIQUIDA\nCEFAZOLINA 1 G IV C/8H",
             "", "", "CONTROL DE LABORATORIOS"),
            ("612", "PEDRO NEL SIERRA CANO", "47", "CC", "1020304060", "COLECISTITIS AGUDA LITIASICA\nDM2",
             "ESTABLE, SIN FIEBRE", "DIETA CORRIENTE\nCEFTRIAXONA 2 G IV C/24H", "", "ECO ABDOMEN 19/10/26",
             "VAL X CX GENERAL"),
            ("615", "GLORIA INES HERRERA VARGAS", "71", "CC", "1020309002", "CELULITIS FACIAL",
             "VALORACION POR CIRUGIA PLASTICA 18/10/26", "DIETA BLANDA", "", "", "PRE QUIRURGICOS"),
            None]),
    ]),
    ("URGENCIAS CARRERA 47", [
        ("URGENCIAS 47 ( 2 PACIENTES)", [
            ("CUB 12", "TOMAS CORREA MEJIA", "62", "CC", "1020304053", "PIELONEFRITIS AGUDA", "ESTABLE", "DIETA BLANDA",
             "", "", "PENDIENTE UROCULTIVO"),
            ("CUB 3", "ELSA MARINA ROJAS DIAZ", "55", "CC", "1020304059", "ABDOMEN AGUDO EN ESTUDIO", "EN OBSERVACION",
             "NADA VIA ORAL", "", "TAC DE ABDOMEN 19/10/26", "A CARGO DE CIRUGIA GENERAL"),
            None, None]),
    ]),
    ("PISO 4C (401-421)", [
        ("PISO 4C ( 2 PACIENTES) 401 - 421", [
            ("408", "LAURA GUTIERREZ OSORIO", "34", "TI", "1020304056", "APENDICITIS AGUDA COMPLICADA",
             "SS VAL CX GENERAL 19/10/26", "DIETA LIQUIDA", "", "", ""),
            ("415", "HUMBERTO FORERO LEAL", "66", "CC", "1020309001", "HERNIA INCISIONAL",
             "VALORACION POR CIRUGIA VASCULAR PENDIENTE", "DIETA NORMAL", "", "", "QX PROGRAMADA"),
            None]),
    ]),
]
_ENCABEZADO = ("<tr><td><p>DATOS</p></td><td><p>DX</p></td><td><p>EVOLUCIÓN</p></td><td><p>TRATAMIENTO</p></td>"
               "<td><p>LABORATORIOS</p></td><td><p>IMAGENES / NOTAS</p></td><td><p>PENDIENTES</p></td></tr>")


# --------------------------------------------------------------------------- páginas
STUB = """
window.__grids = {};
window.ASPxClientControl = { GetControlCollection: function () { return { elements: window.__grids }; } };
window.ASPx = { GVPagerOnClick: function (g, cmd) { window.__grids[g].pager(cmd); } };
// op: tam (filas por página), filtro («contiene», «empieza» o «ninguno»: AutoFilterByColumn no hace nada),
// pag_cliente (false: sin GetPageCount/GotoPage, solo el botón de página siguiente)
function crearGrilla(id, columnas, filas, pintar, op) {
  op = op || {};
  var tam = op.tam || 1000000;
  var estado = { filtro: null, enCallback: false, pagina: 0 };
  function callback(fn) {
    estado.enCallback = true;
    setTimeout(function () { fn(); pintar(); estado.enCallback = false; }, 150);
  }
  var g = {
    InCallback: function () { return estado.enCallback; },
    AutoFilterByColumn: function (col, texto) {
      if (op.filtro === "ninguno") return;
      callback(function () {
        estado.filtro = texto ? { col: col, texto: String(texto).toLowerCase() } : null;
        estado.pagina = 0;
      });
    },
    todas: function () {
      return filas().filter(function (f) {
        if (!estado.filtro) return true;
        var i = columnas.indexOf(estado.filtro.col), v = String(f[i]).toLowerCase();
        return op.filtro === "empieza" ? v.indexOf(estado.filtro.texto) === 0 : v.indexOf(estado.filtro.texto) >= 0;
      });
    },
    paginas: function () { return Math.max(1, Math.ceil(g.todas().length / tam)); },
    pagina: function () { return Math.min(estado.pagina, g.paginas() - 1); },
    visibles: function () { return g.todas().slice(g.pagina() * tam, g.pagina() * tam + tam); },
    pager: function (cmd) {
      callback(function () {
        var n = g.paginas();
        if (cmd === "PBN") estado.pagina = Math.min(n - 1, estado.pagina + 1);
        else if (cmd === "PBP") estado.pagina = Math.max(0, estado.pagina - 1);
        else estado.pagina = Math.max(0, Math.min(n - 1, +cmd.slice(2)));
      });
    }
  };
  if (op.pag_cliente !== false) {
    g.GetPageCount = function () { return g.paginas(); };
    g.GotoPage = function (k) { callback(function () { estado.pagina = Math.max(0, Math.min(g.paginas() - 1, k)); }); };
  }
  window.__grids[id] = g;
  return g;
}
"""

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="90" height="30"><rect width="90" height="30" rx="4" fill="#1b5fa8"/>'
        '<path d="M20 15h50M58 7l12 8-12 8" stroke="#fff" stroke-width="3" fill="none"/></svg>')
IMG_BOTON = "data:image/svg+xml;base64," + base64.b64encode(_SVG.encode()).decode()
_LOGO = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"><rect width="120" height="60" fill="#0a7"/></svg>')
IMG_LOGO = "data:image/svg+xml;base64," + base64.b64encode(_LOGO.encode()).decode()


def pagina_login(error="", usuario="", clave="", boton="image", accion="/Login.aspx", realista=False):
    """Si hay error, repite lo escrito (la clave también: un sistema descuidado haría eso). El texto guía «Usuario»
    es un watermark: está en el value y desaparece al enfocar. El botón ENTRAR es una imagen sin texto."""
    if realista:
        return ("""<!doctype html><html><head><meta charset="utf-8"><title>eHC</title></head><body>
<div><img alt="eHC" src="%s" width="120" height="60"></div>%s
<form id="form1" method="post" action="%s"><div style="margin-left:300px">
<input name="txtUsuario" id="txtUsuario" type="text" value="%s" onfocus="if(this.value==='Usuario')this.value=''" onblur="if(!this.value)this.value='Usuario'"><br>
<input name="txtClave" id="txtClave" type="text" value="" onfocus="this.type='password'" onblur="if(!this.value)this.type='text'"><br>
<input type="image" name="ctl00$b1" src="/img/entrar.png" width="90" height="30">
</div></form>
<p>Software Asistencial eHC - Desarrollado por el Departamento de Sistemas Clínica Reina Catalina</p></body></html>"""
                % (IMG_LOGO, f'<p class="err">{html.escape(error)}</p>' if error else "", accion,
                   html.escape(usuario or "Usuario", quote=True)))
    if boton == "enlace":
        btn = (f'<a id="lnkAcceso" href="javascript:void(0)" onclick="document.getElementById(\'form1\').submit();return false;">'
               f'<img src="{IMG_BOTON}" width="90" height="30" alt=""></a>')
    elif boton == "enter":
        btn = ""
    else:
        btn = f'<input type="image" name="ctl00$btnAcceso" id="ctl00_btnAcceso" src="{IMG_BOTON}" width="90" height="30" alt="">'
    return ("""<!doctype html><html><head><meta charset="utf-8"><title>eHC</title></head><body>
<div><img alt="eHC" src="%s" width="120" height="60"></div>%s
<form id="form1" method="post" action="%s"><div style="margin-left:300px">
<input name="txtUsuario" id="txtUsuario" type="text" value="%s" onfocus="if(this.value==='Usuario')this.value=''" onblur="if(!this.value)this.value='Usuario'">
<input name="txtClave" id="txtClave" type="password" value="%s" onkeydown="if(event.key==='Enter'){document.getElementById('form1').submit();}">
%s</div></form>
<p>Software Asistencial eHC - Desarrollado por el Departamento de Sistemas Clínica Reina Catalina</p></body></html>"""
            % (IMG_LOGO, f'<p class="err">{html.escape(error)}</p>' if error else "", accion,
               html.escape(usuario or "Usuario", quote=True), html.escape(clave, quote=True), btn))


LOGIN = pagina_login()

_CABECERAS = [("Menu Principal", [("Inicio", "/Dashboard.aspx"), ("Atencion de Pacientes", "/AtencionPacientes.aspx")]),
              ("Consultas", [("Consulta de Pacientes", "/Otro.aspx")]),
              ("Historia Externa", [("Cargar Historia", "/Otro.aspx")]),
              ("Parametros", [("Usuarios", "/Otro.aspx")]),
              ("Unidades Funcionales", [("Unidades", "/Otro.aspx")]),
              ("Pacientes", [("Registro", "/Otro.aspx")]),
              ("Ayuda", [("Manual", "/Otro.aspx")])]


def pagina_dashboard(desplegado=False, con_atencion=True, icono=False, marco=False, interior=False):
    """Acordeón: pulsar una cabecera despliega su panel (y pliega el resto); pulsarla otra vez la pliega."""
    if marco:       # Dashboard con el menú y el contenido dentro de un iframe
        return ("""<!doctype html><html><head><meta charset="utf-8"><title>DashBoard</title></head><body>
<div style="text-align:right">MEDICO PRUEBA(<a href="/Login.aspx?salir=1">Salir</a>)</div>
<h2>DashBoard del Usuario</h2>
<iframe id="contenido" name="contenido" src="/MenuFrame.aspx" style="width:1200px;height:900px;border:0"></iframe>
</body></html>""")
    partes = ["""<!doctype html><html><head><meta charset="utf-8"><title>DashBoard</title><style>
.hdr{background:#124;color:#fff;padding:6px;cursor:pointer;width:200px}.pnl{max-height:0;overflow:hidden;transition:max-height .2s;width:200px;background:#eef}
.pnl.abierto{max-height:200px}.pnl a{display:block;padding:4px}</style></head><body>
""" + ("" if interior else """<div style="text-align:right">MEDICO PRUEBA(<a href="/Login.aspx?salir=1">Salir</a>)</div>
<h2>DashBoard del Usuario</h2>""") + """<div id="menu">"""]
    for i, (cab, items) in enumerate(_CABECERAS):
        abierto = " abierto" if desplegado and i == 0 else ""
        enl = "".join(f'<a href="{u}">{html.escape(t)}</a>' for t, u in items
                      if con_atencion or t != "Atencion de Pacientes")
        ico = (f'<img src="{IMG_BOTON}" width="16" height="16" alt="">' if icono else '<span class="ico">»</span>')
        partes.append(f'<div class="hdr" data-i="{i}">{"<span>" + html.escape(cab) + "</span> " + ico if icono else ico + " <span>" + html.escape(cab) + "</span>"}</div>'
                      f'<div class="pnl{abierto}" id="pnl{i}">{enl}</div>')
    partes.append("""</div><script>
document.querySelectorAll('.hdr').forEach(function (h) {
  h.addEventListener('click', function () {
    var p = document.getElementById('pnl' + h.dataset.i), abrir = !p.classList.contains('abierto');
    document.querySelectorAll('.pnl').forEach(function (x) { x.classList.remove('abierto'); });
    if (abrir) p.classList.add('abierto');
  });
});</script></body></html>""")
    return "".join(partes)


def pagina_agenda(datos, cfg):
    campos = (["Paciente", "Identificacion", "Admision", "Convenio", "Habitacion", "Estado", "Accion"] if cfg["campos_legibles"]
              else ["NOMBRE_PAC", "NUM_IDENT", "FEC_ADM", "COD_CONV", "UBICACION", "EST", "ACC"])
    cfg = dict(cfg, campos=campos)

    def tabla(gid, titulo):
        tit = "" if cfg.get("sin_titulo") else f'<tr><td id="{gid}_title" colspan="7" class="dxgvTitlePanel">{titulo}</td></tr>'
        return (f'<table id="{gid}" border="1">{tit}'
                f'<tr id="{gid}_DXHeadRow"><td>Paciente</td><td>Identificacion</td><td>Admision</td><td>Convenio</td>'
                f'<td>Habitacion</td><td>Estado</td><td>Acción</td></tr>'
                f'<tr id="{gid}_DXFilterRow">' + "".join('<td><input type="text" class="flt"></td>' for _ in range(6))
                + "<td></td></tr></table>")
    atendidos = ("<h3>Atendidos</h3>" + tabla(cfg["id_aten"], "Pacientes Atendidos")) if cfg["con_atendidos"] else ""
    return """<!doctype html><html><head><meta charset="utf-8"><title>Atencion De Pacientes</title></head><body>
<div style="text-align:right">MEDICO PRUEBA(<a href="/Login.aspx?salir=1">Salir</a>)</div>
<h2>Atencion De Pacientes</h2>
<div><input type="radio" name="modo" id="rbU" checked><label for="rbU">Urgencias</label>
<input type="radio" name="modo" id="rbH"><label for="rbH">Hospitalización</label>
<input type="checkbox" id="chk24" checked><label for="chk24">Últimas 24 horas.</label>
<div id="btnAct" class="dxbButton" style="display:inline-block;border:1px solid #888;padding:4px 10px;cursor:pointer"><span>Actualizar</span></div></div>
""" + tabla(cfg["id_pend"], "Pacientes Por Atender") + atendidos + """
<script>
var DATOS = @@DATOS@@;     // [id, nombre, tipo, doc, hab, modo, pend, reciente]
var CFG = @@CFG@@;
var COLS = ["Paciente", "Identificacion", "Admision", "Convenio", "Habitacion", "Estado", "Acción"];
window.__grids = {};
window.ASPxClientControl = { GetControlCollection: function () { return { elements: window.__grids }; } };
window.ASPx = { GVPagerOnClick: function (g, cmd) { window.__grids[g].pager(cmd); } };
var aplicado = { modo: "Urgencias", r24: true };
function campo(d, i) { return [d[1], d[2] + " - " + d[3], "19/10/2026 0" + (d[0] % 10) + ":00", "CONVENIO " + (d[0] % 3), d[4], "P", ""][i]; }
function montar(id, pend, tam) {
  var t = document.getElementById(id), st = { filtros: {}, pagina: 0, cb: false };
  function base() { return DATOS.filter(function (d) { return d[5] === aplicado.modo && d[6] === pend && (!aplicado.r24 || d[7]); })
    .sort(function (a, b) { return a[1] < b[1] ? -1 : 1; }); }
  function visibles() {
    return base().filter(function (d) {
      return Object.keys(st.filtros).every(function (k) {
        var v = String(campo(d, +k)).toLowerCase(), q = st.filtros[k];
        return CFG.contiene ? v.indexOf(q) >= 0 : v.indexOf(q) === 0;                 // «empieza con» por defecto
      });
    });
  }
  function celda(tr, txt) { var td = document.createElement("td"); td.textContent = txt; tr.appendChild(td); return td; }
  function pintar() {
    var filas = visibles(), paginas = Math.max(1, Math.ceil(filas.length / tam));
    if (st.pagina >= paginas) st.pagina = paginas - 1;
    Array.prototype.slice.call(t.querySelectorAll("tr[id*=_DXDataRow], tr[id*=_DXEmptyRow], tr[id*=_DXPagerBottom]")).forEach(function (x) { x.remove(); });
    filas.slice(st.pagina * tam, st.pagina * tam + tam).forEach(function (d, n) {
      var tr = document.createElement("tr"); tr.id = id + "_DXDataRow" + n;
      celda(tr, d[1]);
      var ti = document.createElement("td");
      ti.appendChild(document.createTextNode(d[2] + " -"));
      if (d[0] % 2) ti.appendChild(document.createElement("br"));       // a veces partida en 2 renglones
      ti.appendChild(document.createTextNode(" " + d[3])); tr.appendChild(ti);
      celda(tr, campo(d, 2)); celda(tr, campo(d, 3)); celda(tr, d[4]); celda(tr, "P");
      var ta = document.createElement("td"), a = document.createElement("a");
      a.href = "HistoriaClinica.aspx?id=" + d[0]; a.textContent = "Atender"; ta.appendChild(a); tr.appendChild(ta);
      t.appendChild(tr);
    });
    if (!filas.length) { var e = document.createElement("tr"); e.id = id + "_DXEmptyRow"; celda(e, "No hay datos para mostrar").colSpan = 7; t.appendChild(e); }
    if (paginas > 1) {
      var pr = document.createElement("tr"); pr.id = id + "_DXPagerBottom";
      var pt = document.createElement("td"); pt.colSpan = 7; var h = "";
      for (var k = 0; k < paginas; k++) h += k === st.pagina ? "<b>" + (k + 1) + "</b> " :
        "<a href='#' onclick=\\"ASPx.GVPagerOnClick('" + id + "','PN" + k + "');return false;\\">" + (k + 1) + "</a> ";
      h += st.pagina < paginas - 1 ? "<a href='#' onclick=\\"ASPx.GVPagerOnClick('" + id + "','PBN');return false;\\">Siguiente</a>"
                                   : "<span class='dxp-disabled'>Siguiente</span>";
      pt.innerHTML = h; pr.appendChild(pt); t.appendChild(pr);
    }
  }
  function callback(fn) { st.cb = true; setTimeout(function () { fn(); pintar(); st.cb = false; }, 180); }
  function col(c) { if (typeof c === "number") return c; if (c && typeof c === "object") return c.index; return CFG.campos.indexOf(c); }
  var g = {
    st: st, pintar: pintar, callback: callback,
    InCallback: function () { return st.cb; },
    AutoFilterByColumn: function (c, texto) {
      if (CFG.autofilter_roto) return;
      var i = col(c); if (i < 0 || i > 5) return;
      callback(function () {
        if (texto) st.filtros[i] = String(texto).toLowerCase(); else delete st.filtros[i]; st.pagina = 0;
        var inp = t.querySelectorAll('input.flt')[i]; if (inp) inp.value = texto || '';    // DevExpress refleja el filtro en su input
      });
    },
    GetColumnsCount: function () { return 7; },
    GetColumn: function (i) { return { fieldName: CFG.campos[i], name: "col" + i, index: i, visible: true }; },
    pager: function (cmd) {
      callback(function () {
        var n = Math.max(1, Math.ceil(visibles().length / tam));
        if (cmd === "PBN") st.pagina = Math.min(n - 1, st.pagina + 1);
        else if (cmd === "PBP") st.pagina = Math.max(0, st.pagina - 1);
        else st.pagina = +cmd.slice(2);
      });
    }
  };
  if (CFG.pag_cliente) {
    g.GetPageCount = function () { return Math.max(1, Math.ceil(visibles().length / tam)); };
    g.GotoPage = function (k) { callback(function () { st.pagina = k; }); };
  }
  window.__grids[id] = g;
  Array.prototype.slice.call(t.querySelectorAll("input.flt")).forEach(function (inp, i) {
    inp.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter") return;
      callback(function () { if (inp.value) st.filtros[i] = inp.value.toLowerCase(); else delete st.filtros[i]; st.pagina = 0; });
    });
  });
  pintar();
  return g;
}
var grillas = [montar(CFG.id_pend, true, CFG.tam_pend)];
if (CFG.con_atendidos) grillas.push(montar(CFG.id_aten, false, CFG.tam_aten));
document.getElementById("btnAct").addEventListener("click", function () {
  var m = document.getElementById("rbH").checked ? "Hospitalización" : "Urgencias", r = document.getElementById("chk24").checked;
  fetch("/_act?m=" + encodeURIComponent(m) + "&r=" + (r ? 1 : 0));
  grillas.forEach(function (g) { g.st.cb = true; setTimeout(function () { aplicado.modo = m; aplicado.r24 = r; g.st.pagina = 0; g.pintar(); g.st.cb = false; }, 300); });
});
</script></body></html>""".replace("@@DATOS@@", json.dumps(datos)).replace("@@CFG@@", json.dumps(cfg))


PESTANAS = ["DIAGNOSTICO:", "UNIDAD EN DONDE SE ENCUENTRA EL PACIENTE", "HIPOTESIS DIAGNOSTICA:", "SINTOMAS DESCRITOS:",
            "-EXAMEN FISICO-", "ANALISIS:", "PLAN-", "SOLICITUD MATERIAL ESPECIAL"]
PESTANAS_IMG = ["EXAMEN", "DESCRIPCIÓN DEL EXAMEN"]


def pagina_historia(pid, cfg=None):
    """Historia clínica del paciente pid. cfg (la del Simulador): filtro_formatos, tam_formatos y pag_cliente."""
    cfg = cfg or {}
    nombre = next(p[1] for p in PACIENTES if p[0] == pid)
    formatos = [(f[0], f[1], f[2], f[3], f[4], 22807000 + pid * 100 + i) for i, f in enumerate(FORMATOS[pid])]
    opciones = {"tam": cfg.get("tam_formatos", 10), "filtro": cfg.get("filtro_formatos", "contiene"),
                "pag_cliente": cfg.get("pag_cliente", True)}
    return """<!doctype html><html><head><meta charset="utf-8"><title>Historia clínica</title>
<style>.dxtc-tab{border:1px solid #888;padding:4px 8px;cursor:pointer;width:170px}.dxtc-activeTab{background:#cde}
.dxtc-content{border:1px solid #888;padding:6px;min-width:520px;min-height:80px}.dxeButtonEdit td{padding:0}</style></head><body>
<h1>Historia clínica</h1><p id="quien">%(nombre)s</p>
<div id="ctl00_cph1_ASPxRoundPanel2">
<table id="%(grid)s"><tr id="%(grid)s_DXHeadRow"><th>N°</th><th>Formato</th><th>Fecha hora</th><th>Estado</th><th>Usuario</th><th>Ver</th></tr></table></div>
<h3>Detalle del Formato</h3>
<div id="detalle"></div>
<script>%(stub)s
var FORMATOS = %(formatos)s;      // [formato, fecha, estado, usuario, detalle, n° de formato]
var PESTANAS = %(pestanas)s;
var PESTANAS_IMG = %(pestanas_img)s;
var COLS = ["N°", "Formato", "Fecha hora", "Estado", "Usuario", "Ver"];
var g = crearGrilla("%(grid)s", COLS, function () {
  return FORMATOS.map(function (f, i) { return [String(f[5]), f[0], f[1], f[2], f[3], "Ver", i]; });
}, pintar, %(opciones)s);
function esc(t) { return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"); }
function combo(v) {
  return '<table class="dxeButtonEdit"><tr><td><input type="text" class="dxeEditArea" readonly value="' + esc(v) +
         '"></td><td>&#9662;</td></tr></table><input type="hidden" value="x">';
}
function fila(et, ctl) { return "<tr><td>" + esc(et) + "</td><td>" + ctl + "</td><td><img alt='' width='12' height='12' src='data:,'>&#128269;</td></tr>"; }
function area(v, dis) { return '<textarea rows="4" cols="60" style="resize:both;color:gray" disabled>' + esc(v) + "</textarea>"; }
function contenido(i, d) {      // lo que devuelve el callback de cada pestaña
  var t = PESTANAS[i], r;
  if (i === 0) r = fila("DX:", area(d.dx)) + fila("SOSPECHA DENGUE", combo("NO")) + fila("SOSPECHA COVID 19", combo("NO")) +
                   fila("RIESGO DE VENTILACION", combo("NO APLICA")) + fila("¿PACIENTE CON SINTOMAS RESPIRATORIOS?", combo("NO")) +
                   fila("VENTILACION MECANICA", combo("NO"));
  else if (i === 1) r = fila("UNIDAD:", combo("PISO 6"));
  else if (i === 2) r = fila("HIPOTESIS DIAGNOSTICA:", area(""));
  else if (i === 3) r = fila("SINTOMAS DESCRITOS:", area(d.sintomas));
  else if (i === 4) r = fila("EXAMEN FISICO:", area(d.examen));
  else if (i === 5) r = fila("ANALISIS:", area(d.analisis));
  else if (i === 6) r = fila("PLAN:", area(d.plan));
  else r = "";
  return '<fieldset><legend>' + esc(t) + '</legend><table>' + r + "</table></fieldset>";
}
function contenidoImg(i, inf) {  // informe de imagenología: EXAMEN tiene la fecha, el tipo, el estudio y el informe SIN etiqueta
  var r = "";
  if (i === 0) r = fila("FECHA DE REALIZACIÓN DEL ESTUDIO", area(inf.fecha)) + fila("TIPO ESTUDIO", combo(inf.tipo)) +
                   fila("ESTUDIO:", area(inf.estudio)) + "<tr><td></td><td>" + area(inf.texto) + "</td><td></td></tr>";
  return '<fieldset><legend>' + esc(PESTANAS_IMG[i]) + '</legend><table>' + r + "</table></fieldset>";    // DESCRIPCIÓN: vacía
}
function mostrar(f) {
  var d = f[4], det = document.getElementById("detalle"), img = typeof d === "object" && !!d.informe;
  var nombres = img ? PESTANAS_IMG : PESTANAS;
  var cont = function (i) { return img ? contenidoImg(i, d.informe) : contenido(i, d); };
  var titulo = '<div class="dxrp-header"><span>Formato: ' + f[5] + " - " + (f[0] === "HOJA DE EVOLUCION" ? f[0] + " MEDICO ESPECIALISTA" : f[0]) + "</span></div>";
  var pie = "<p>Su nivel de permisos no le permite modificar el formato</p>";
  if (typeof d === "string") { det.innerHTML = titulo + '<textarea id="t1" rows="6" cols="80">' + esc(d) + "</textarea>" + pie; return; }
  var tabs = nombres.map(function (n, i) {
    return '<tr><td class="dxtc-tab' + (i ? "" : " dxtc-activeTab") + '" data-i="' + i + '"><a class="dxtc-link" href="#"><span class="dx-vam">' + esc(n) + "</span></a></td></tr>";
  }).join("");
  var conts = nombres.map(function (n, i) {
    return '<div class="dxtc-content" data-i="' + i + '" style="display:' + (i ? "none" : "block") + '">' + (i || img ? "" : cont(0)) + "</div>";
  }).join("");
  det.innerHTML = titulo + '<table class="dxtcLeft"><tr><td valign="top"><table>' + tabs + '</table></td><td valign="top">' + conts + "</td></tr></table>" + pie;
  var llenos = {};
  function cargar(i) {       // callback: el contenido llega con retardo
    llenos[i] = true;
    var caja = det.querySelector('.dxtc-content[data-i="' + i + '"]');
    setTimeout(function () { caja.innerHTML = cont(i); }, 300);
  }
  if (img) cargar(0); else llenos[0] = true;       // las hojas de evolución traen la 1.ª pestaña ya llena
  Array.prototype.forEach.call(det.querySelectorAll(".dxtc-tab"), function (td) {
    td.addEventListener("click", function (ev) {
      ev.preventDefault();
      var i = +td.getAttribute("data-i");
      Array.prototype.forEach.call(det.querySelectorAll(".dxtc-tab"), function (x) { x.classList.toggle("dxtc-activeTab", x === td); });
      Array.prototype.forEach.call(det.querySelectorAll(".dxtc-content"), function (c) { c.style.display = (+c.getAttribute("data-i") === i) ? "block" : "none"; });
      if (!llenos[i]) cargar(i);
    });
  });
}
function pintar() {
  var t = document.getElementById("%(grid)s");
  Array.prototype.slice.call(t.querySelectorAll("tr[id*=_DXDataRow], tr[id*=_DXPager]")).forEach(function (tr) { tr.remove(); });
  g.visibles().forEach(function (f, n) {
    var tr = document.createElement("tr"); tr.id = "%(grid)s_DXDataRow" + n;
    for (var i = 0; i < 5; i++) { var td = document.createElement("td"); td.textContent = f[i]; tr.appendChild(td); }
    var td = document.createElement("td"); var a = document.createElement("a"); a.href = "#"; a.textContent = "Ver";
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      setTimeout(function () { mostrar(FORMATOS[f[6]]); }, 400);      // el detalle llega con un pequeño retardo
    });
    td.appendChild(a); tr.appendChild(td); t.appendChild(tr);
  });
  var paginas = g.paginas(), pag = g.pagina();
  if (paginas > 1) {     // pager de DevExpress: resumen «Page 1 of 2 (18 items)», números y botón de página siguiente
    var pr = document.createElement("tr"); pr.id = "%(grid)s_DXPagerBottom";
    var pt = document.createElement("td"); pt.colSpan = 6;
    var h = "<b class='dxp-summary'>Page " + (pag + 1) + " of " + paginas + " (" + g.todas().length + " items)</b> ";
    for (var k = 0; k < paginas; k++) h += k === pag ? "<b class='dxp-current'>" + (k + 1) + "</b> " :
      "<a href='#' class='dxp-num' onclick=\\"ASPx.GVPagerOnClick('%(grid)s','PN" + k + "');return false;\\">" + (k + 1) + "</a> ";
    h += pag < paginas - 1 ? "<a href='#' class='dxp-button' onclick=\\"ASPx.GVPagerOnClick('%(grid)s','PBN');return false;\\">" +
                             "<img alt='Next' width='12' height='12' src='data:,'>&gt;</a>"
                           : "<span class='dxp-button dxp-disabled'>&gt;</span>";
    pt.innerHTML = h; pr.appendChild(pt); t.appendChild(pr);
  }
}
pintar();
</script></body></html>""" % {"nombre": html.escape(nombre), "grid": GRID_FORM, "stub": STUB, "formatos": json.dumps(formatos),
                              "pestanas": json.dumps(PESTANAS), "pestanas_img": json.dumps(PESTANAS_IMG),
                              "opciones": json.dumps(opciones)}


def _parrafos(lineas):
    return "".join(f"<p>{html.escape(l)}</p>" for l in lineas)


def pagina_kardex():
    """Estructura real del Google Doc: fila 0 = título (colspan 7), fila 1 = encabezados,
    luego pacientes. DATOS: habitación, nombre en 1-3 renglones, vacío, edad, vacío, «CC n».
    DX empieza con «DX:» y TRATAMIENTO con «PLAN»."""
    partes = ["<html><head><style>p{margin:0}</style></head><body><h1>KARDEX MIS PX</h1>"]
    n = 0
    for servicio, filas in KARDEX:
        partes.append(f'<table><tr><td colspan="7"><p>{html.escape(servicio)} ( {len(filas)} PACIENTES)</p></td></tr>'
                      "<tr><td><p>DATOS</p></td><td><p>DX</p></td><td><p>EVOLUCIÓN</p></td><td><p>TRATAMIENTO</p></td>"
                      "<td><p>LABORATORIOS</p></td><td><p>IMÁGENES / NOTAS</p></td><td><p>PENDIENTES</p></td></tr>")
        for nombre, hab, dx, ev, trat, tipo, doc in filas:
            n += 1
            palabras = nombre.split()
            nombre_lineas = [" ".join(palabras[i:i + 2]) for i in range(0, len(palabras), 2)]
            datos = _parrafos([hab] + nombre_lineas) + "<p></p>" + _parrafos([f"{40 + n} AÑOS"]) \
                + "<p></p>" + _parrafos([f"{tipo} {doc}"])
            t = _parrafos(["PLAN"] + trat.split("\n"))
            ev = ev.split("\n")
            partes.append(f"<tr><td>{datos}</td><td>{_parrafos(['DX:', dx])}</td><td>{_parrafos(ev)}</td>"
                          f"<td>{t}</td><td></td><td></td><td></td></tr>")
        partes.append("</table>")
    partes.append("</body></html>")
    return "".join(partes)


def pagina_entregas(n):
    """Documento de entregas n (1, 2…) como HTML exportado de Google Docs, igual que el kardex: una tabla por servicio
    con el título en una celda combinada («PISO 6 ( 3 PACIENTES)»), el encabezado DATOS | DX | … y una fila por
    paciente (DATOS: habitación, nombre en 1-3 renglones, edad y «CC n»), más filas vacías al final."""
    nombre, tablas = ENTREGAS[n - 1]
    partes = [f"<html><head><style>p{{margin:0}}</style></head><body><h1>ENTREGAS CRC {html.escape(nombre)}</h1>"]
    for titulo, filas in tablas:
        partes.append(f'<table><tr><td colspan="7"><p>{html.escape(titulo)}</p></td></tr>{_ENCABEZADO}')
        for f in filas:
            if f is None:
                partes.append("<tr>" + "<td><p></p></td>" * 7 + "</tr>")
                continue
            hab, pac, edad, tipo, doc, *resto = f
            palabras = pac.split()
            renglones = [" ".join(palabras[i:i + 2]) for i in range(0, len(palabras), 2)]
            celdas = [_parrafos([hab] + renglones + [f"{edad} AÑOS", f"{tipo} {doc}"])]
            celdas += [_parrafos(t.split("\n")) if t else "<p></p>" for t in resto]
            partes.append("<tr>" + "".join(f"<td>{c}</td>" for c in celdas) + "</tr>")
        partes.append("</table>")
    partes.append("</body></html>")
    return "".join(partes)


# --------------------------------------------------------------------------- servidor
class Simulador:
    """exige_login: sin cookie de sesión, las páginas protegidas redirigen a /Login.aspx.
    agenda_requiere_menu: /Agenda.aspx solo trae las grillas si en esa sesión se pasó por «Atencion de Pacientes»
    (si no, muestra el Dashboard). vence_tras: la sesión «vence» al recibir esa cantidad de peticiones protegidas.
    agenda_rota_en: números de visita a la Agenda con grillas (1, 2, 3…) que devuelven una página sin grillas.
    boton_login: «image» (input[type=image]), «enlace» (imagen dentro de un enlace) o «enter» (sin botón).
    menu_desplegado: el acordeón llega con «Menu Principal» ya abierto. con_atendidos: añade la grilla de atendidos.
    id_pend: id distinto para la grilla de pendientes (se encuentra por su título). filtro_contiene: el filtro
    es «contiene» y no «empieza con». campos_legibles: fieldName = título de la columna. autofilter_roto:
    AutoFilterByColumn no hace nada (solo funciona escribir en la fila de filtros). pag_cliente=False: sin
    GetPageCount/GotoPage (solo el botón de página siguiente; también en la grilla de formatos). filtro_formatos:
    «contiene», «empieza» (con) o «ninguno» (AutoFilterByColumn de la grilla de formatos no hace nada);
    tam_formatos: filas por página de la grilla de formatos. entregas_fallan: números de documento de entregas que
    responden 404."""

    def __init__(self, agenda_rota_en=(), exige_login=True, agenda_requiere_menu=True, vence_tras=None,
                 boton_login="image", menu_desplegado=False, con_atendidos=False, tam_atendidos=2, id_pend=None,
                 filtro_contiene=False, campos_legibles=False, autofilter_roto=False, pag_cliente=True,
                 con_atencion_en_menu=True, login_realista=False, iframe=False, sin_titulo=False,
                 icono_en_cabecera=False, agenda_redirige=False, filtro_formatos="contiene", tam_formatos=10,
                 entregas_fallan=()):
        self.exige_login = exige_login
        self.agenda_requiere_menu = agenda_requiere_menu
        self.vence_tras = vence_tras
        self.agenda_rota_en = set(agenda_rota_en)
        self.boton_login = boton_login
        self.menu_desplegado = menu_desplegado
        self.con_atencion_en_menu = con_atencion_en_menu
        self.login_realista = login_realista
        self.ruta_login = "/ehc2013/Default.aspx" if login_realista else "/Login.aspx"     # sin «login» en la URL
        self.iframe = iframe
        self.icono_en_cabecera = icono_en_cabecera
        self.agenda_redirige = agenda_redirige
        self.visitas_url_agenda = 0         # peticiones a /Agenda.aspx (la url_agenda configurada)
        if sin_titulo and not id_pend:
            id_pend = "ctl00_cph1_ASPxPageControl1_gvOtraTabla"
        self.cfg = {"sin_titulo": sin_titulo, "id_pend": id_pend or GRID_PEND, "id_aten": GRID_ATEN, "con_atendidos": con_atendidos,
                    "tam_pend": 10, "tam_aten": tam_atendidos, "contiene": filtro_contiene,
                    "campos_legibles": campos_legibles, "autofilter_roto": autofilter_roto, "pag_cliente": pag_cliente,
                    "filtro_formatos": filtro_formatos, "tam_formatos": tam_formatos}
        self.visitas_agenda = 0
        self.protegidas = 0
        self.logins = 0
        self.actualizaciones = []           # (modo, 24 h) de cada pulsación de «Actualizar»
        self.sesiones = {}                  # sid -> {"menu": bool}
        self.kardex_sirve = True
        self.entregas_fallan = set(entregas_fallan)      # números de documento de entregas que responden 404
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.puerto = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.puerto}"
        self._hilo = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url_agenda(self):
        return f"{self.base}/Agenda.aspx"

    @property
    def url_login(self):
        return f"{self.base}{self.ruta_login}"

    @property
    def url_kardex(self):
        return f"http://localhost:{self.puerto}/kardex"

    def url_entregas(self, n):
        """URL del documento de entregas n (1, 2…), como las de Google Docs: se descarga tal cual."""
        return f"http://localhost:{self.puerto}/entregas/{n}"

    @property
    def entregas(self):
        """Lista [{nombre, url}] de los documentos de entregas, como `cfg["entregas"]` de la app."""
        return [{"nombre": nombre, "url": self.url_entregas(n)} for n, (nombre, _) in enumerate(ENTREGAS, 1)]

    def _handler(self):
        sim = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _html(self, cuerpo, codigo=200, cabeceras=()):
                b = cuerpo.encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                for k, v in cabeceras:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(b)

            def _redirigir(self, destino, cabeceras=()):
                self.send_response(302)
                self.send_header("Location", destino)
                self.send_header("Content-Length", "0")
                for k, v in cabeceras:
                    self.send_header(k, v)
                self.end_headers()

            def _sesion(self):
                for parte in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = parte.strip().partition("=")
                    if k == "sid" and v in sim.sesiones:
                        return sim.sesiones[v]
                return None

            def do_POST(self):
                u = urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                campos = parse_qs(self.rfile.read(n).decode("utf-8"))
                if u.path.lower() not in ("/login.aspx", sim.ruta_login.lower()):
                    return self._html("no existe", 404)
                usuario, clave = campos.get("txtUsuario", [""])[0], campos.get("txtClave", [""])[0]
                if usuario == USUARIO and clave == CLAVE:
                    sim.logins += 1
                    sid = secrets.token_hex(8)
                    sim.sesiones[sid] = {"menu": False}
                    # cookie de sesión: sin Expires ni Max-Age (se pierde al cerrar el navegador)
                    return self._redirigir("/Dashboard.aspx", [("Set-Cookie", f"sid={sid}; Path=/; HttpOnly")])
                self._html(pagina_login("Usuario o contraseña incorrectos", usuario, clave, sim.boton_login,
                                        sim.ruta_login, sim.login_realista))

            def do_GET(self):
                u = urlparse(self.path)
                ruta = u.path.lower()
                if ruta in ("/login.aspx", sim.ruta_login.lower()):
                    return self._html(pagina_login(boton=sim.boton_login, accion=sim.ruta_login, realista=sim.login_realista))
                if ruta == "/img/entrar.png":
                    b = _SVG.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/svg+xml")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    return self.wfile.write(b)
                if ruta == "/_act":
                    q = parse_qs(u.query)
                    sim.actualizaciones.append((q.get("m", [""])[0], q.get("r", ["1"])[0] == "1"))
                    return self._html("ok")
                if ruta == "/kardex":
                    return self._html(pagina_kardex()) if sim.kardex_sirve else self._html("no", 404)
                if ruta.startswith("/entregas/"):
                    n = ruta.rsplit("/", 1)[1]
                    if not n.isdigit() or not 1 <= int(n) <= len(ENTREGAS) or int(n) in sim.entregas_fallan:
                        return self._html("no", 404)
                    return self._html(pagina_entregas(int(n)))
                if ruta in ("/dashboard.aspx", "/atencionpacientes.aspx", "/agenda.aspx", "/historiaclinica.aspx", "/otro.aspx", "/menuframe.aspx"):
                    sim.protegidas += 1
                    if ruta == "/agenda.aspx":
                        sim.visitas_url_agenda += 1
                    if sim.vence_tras and sim.protegidas == sim.vence_tras:
                        sim.sesiones.clear()                  # la sesión vence a mitad del análisis
                    ses = self._sesion()
                    if sim.exige_login and ses is None:
                        return self._redirigir(sim.ruta_login + "?ReturnUrl=" + u.path)
                    ses = ses if ses is not None else {"menu": True}
                    dash = pagina_dashboard(sim.menu_desplegado, sim.con_atencion_en_menu, sim.icono_en_cabecera, sim.iframe)
                    if ruta == "/menuframe.aspx":
                        return self._html(pagina_dashboard(sim.menu_desplegado, sim.con_atencion_en_menu,
                                                           sim.icono_en_cabecera, False, True))
                    if ruta in ("/dashboard.aspx", "/otro.aspx"):
                        return self._html(dash)
                    if ruta == "/agenda.aspx" and sim.agenda_redirige:
                        return self._redirigir("/Dashboard.aspx")
                    if ruta in ("/atencionpacientes.aspx", "/agenda.aspx"):
                        if ruta == "/atencionpacientes.aspx":
                            ses["menu"] = True
                        if sim.agenda_requiere_menu and not ses["menu"]:
                            return self._html(dash)
                        sim.visitas_agenda += 1
                        if sim.visitas_agenda in sim.agenda_rota_en:
                            return self._html("<html><body><h1>Error inesperado</h1></body></html>")
                        # con grilla de atendidos, DUQUE (4) y GUTIERREZ (6) ya fueron atendidos: salen de «por atender»
                        datos = [[*p[:6], p[6] and not (sim.cfg["con_atendidos"] and p[0] in (4, 6)), p[7]] for p in PACIENTES]
                        return self._html(pagina_agenda(datos, sim.cfg))
                    try:
                        pid = int(parse_qs(u.query).get("id", ["0"])[0])
                        return self._html(pagina_historia(pid, sim.cfg))
                    except (ValueError, StopIteration, KeyError):
                        return self._html("no existe", 404)
                self._html("no existe", 404)

        return H
