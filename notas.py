"""Interpreta hojas de evolución y órdenes médicas (texto libre) de Hospital Office."""
import re
import unicodedata
from dataclasses import dataclass


def normalizar(texto):
    """MAYÚSCULAS, sin tildes y sin espacios repetidos (para comparar nombres)."""
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().upper()


def limpiar(texto):
    return re.sub(r"[ \t]+", " ", (texto or "").replace("\r", "")).strip()


_PLAN = re.compile(r"\bPLAN\b\s*[:\-]?", re.I)
_DX = re.compile(r"\bCON\s+DX\b\s*[:\-]?|\bDIAGN[OÓ]STICOS?\b\s*[:\-]?", re.I)
_CORTE_DX = re.compile(r"\b(S\s*:|SUBJETIVO|EXAMEN|AN[AÁ]LISIS|PARACL[IÍ]NICOS|PLAN\b)", re.I)


_ESPECIALIDAD = re.compile(r"\s*-\s*([^-\n]{2,60}?)\s*-")


def nombre_dr(medico):
    """«DR. NOMBRE» en mayúsculas, sin duplicar DR/DRA si ya viene."""
    m = " ".join((medico or "").upper().split())
    if not m:
        return ""
    return m if re.match(r"^DRA?\b", m) else "DR. " + m


def encabezado_evolucion(fecha, medico, especialidad=""):
    """«DD/MM/AAAA - DR. NOMBRE (ESPECIALIDAD)» (la parte que falte se omite)."""
    dr = nombre_dr(medico)
    if dr and especialidad:
        dr += f" ({especialidad.upper()})"
    return " - ".join(x for x in ((fecha or "").split(" ")[0], dr) if x)


_ITEM = re.compile(r"[ \t]+(?=(?:\d{1,2}[.)]|-)[ \t]*[A-ZÁÉÍÓÚÑa-záéíóúñ])")


def en_renglones(texto):
    """Pone cada ítem («1. …», «2) …», «- …») en su propio renglón, como en el kardex.
    «1.5 L» no se parte porque exige letra después del número."""
    return "\n".join(_ITEM.sub("\n", linea).strip() for linea in (texto or "").split("\n")).strip()


def interpretar_evolucion(texto, fecha="", medico=""):
    """Devuelve dict con dx, evolucion, plan a partir del texto libre de la nota."""
    t = limpiar(texto)
    dx = ""
    fin_dx = 0
    m = _DX.search(t)
    if m:
        resto = t[m.end():]
        corte = _CORTE_DX.search(resto)
        dx = resto[: corte.start()] if corte else resto
        fin_dx = m.end() + len(dx)          # dónde termina el DX en el texto original (antes de limpiarlo)
    dx = re.sub(r"\s*\n\s*", "\n", dx).strip()

    plan = ""
    ult = None
    for ult in _PLAN.finditer(t):
        pass
    cuerpo = t
    if ult:
        plan = t[ult.end():].strip()
        cuerpo = t[: ult.start()]
    # la evolución es lo que sigue a los diagnósticos y precede al plan
    if m:
        cuerpo = cuerpo[fin_dx:]
    cuerpo = re.sub(r"\s*\n\s*", " ", cuerpo).strip(" -:\n")
    if len(cuerpo) > 700:
        cuerpo = cuerpo[:700].rsplit(" ", 1)[0] + "…"
    esp = _ESPECIALIDAD.match(t)
    especialidad = limpiar(esp.group(1)) if esp else ""
    cab = encabezado_evolucion(fecha, medico, especialidad)
    evolucion = f"{cab}\n{cuerpo.upper()}" if cab and cuerpo else (cuerpo.upper() or cab)
    return {"dx": en_renglones(dx).upper(), "evolucion": evolucion, "plan": en_renglones(plan).upper(),
            "especialidad": especialidad.upper()}


# ------------------------------------------------------------------ DX de la pestaña DIAGNOSTICO
_MARCA = re.compile(r"^\s*(?:\d{1,2}[.)](?!\d)|[-•*])\s*")
_DX_SOLO = re.compile(r"^(?:DIAGN[OÓ]STICOS?|DX|IDX|IMPRESI[OÓ]N\s+DIAGN[OÓ]STICA)\s*:?$", re.I)
_DX_LINEA = re.compile(r"^(?:DIAGN[OÓ]STICOS?|DX|IDX|IMPRESI[OÓ]N\s+DIAGN[OÓ]STICA)\s*:\s*(\S.*)$", re.I)
# encabezado de otra sección / título de la nota (nunca un renglón que empieza con marcador de ítem)
_OTRA = re.compile(r"^(?:(?:EVOLUCI[OÓ]N|AN[AÁ]LISIS|PLAN|EXAMEN|SUBJETIVO|OBJETIVO|PARACL[IÍ]NICOS?|NOTA|MOTIVO"
                   r"|ENFERMEDAD\s+ACTUAL|ANTECEDENTES|RONDA)\b|[SOAP]\s*:)", re.I)
_TITULO_ESP = re.compile(r"^-\s*[^-\n]{2,60}?\s*-$")


def _es_otra(linea):
    return not _MARCA.match(linea) and bool(_OTRA.match(linea))


def _es_titulo(linea):
    return _es_otra(linea) or bool(_TITULO_ESP.match(linea))


def _juntar_items(lineas):
    """Un ítem por renglón: el renglón sin marcador continúa el ítem anterior (si hay marcadores en el texto)."""
    hay_marcas = any(_MARCA.match(x) for x in lineas)
    out = []
    for x in lineas:
        if out and hay_marcas and not _MARCA.match(x):
            out[-1] += " " + x
        else:
            out.append(x)
    res = []
    for x in out:                                  # «1. A 2. B» en un solo renglón -> dos renglones
        if re.match(r"\d{1,2}[.)](?!\d)", x):
            x = re.sub(r"[ \t]+(?=\d{1,2}[.)][ \t]*[A-ZÁÉÍÓÚÑa-záéíóúñ])", "\n", x)
        res.extend(x.split("\n"))
    return res


def extraer_dx(texto):
    """Diagnósticos del campo «DX» de la hoja de evolución (puede traer título y otras secciones).
    1. Con encabezado DIAGNOSTICO(S)/DX/IDX/IMPRESION DIAGNOSTICA (renglón solo con ese título, o «DX: …» con texto
       después) esté donde esté: solo esa sección, hasta el siguiente encabezado de otra sección o el final.
       Si hay varios encabezados de DX se usa el ÚLTIMO bloque.
    2. Sin encabezado de DX: se quitan el título inicial y las secciones de otro tipo.
    3. Sin títulos: todo el texto. Resultado en MAYÚSCULAS, un ítem por renglón."""
    lineas = [x.strip() for x in (texto or "").replace("\r", "").split("\n")]
    ini, primero = None, []
    for i, x in enumerate(lineas):                  # el ÚLTIMO encabezado de DX manda
        solo, linea = _DX_SOLO.match(x), _DX_LINEA.match(x)
        if solo or linea:
            ini, primero = i + 1, ([linea.group(1)] if linea else [])
    if ini is not None:
        cuerpo = primero
        for x in lineas[ini:]:
            if _es_otra(x):
                break
            cuerpo.append(x)
    else:
        i = 0
        while i < len(lineas) and (not lineas[i] or _es_titulo(lineas[i])):
            i += 1
        cuerpo = []
        for x in lineas[i:]:
            if _es_otra(x):
                break
            cuerpo.append(x)
        if any(_MARCA.match(x) for x in cuerpo if x):         # título libre antes del primer ítem
            while cuerpo and not _MARCA.match(cuerpo[0]):
                cuerpo.pop(0)
    return "\n".join(_juntar_items([x for x in cuerpo if x])).upper()


def clave(texto):
    """Clave de pestaña/etiqueta: normalizada y sin signos en los bordes («-EXAMEN FISICO-» -> «EXAMEN FISICO»)."""
    return re.sub(r"^[^A-Z0-9]+|[^A-Z0-9]+$", "", normalizar(texto))


def especialidad_de(textos):
    """«-CX GENERAL-» al comienzo de alguno de los textos. Devuelve (especialidad, [textos sin ese título])."""
    esp, res = "", []
    for t in textos:
        m = None if esp else _ESPECIALIDAD.match(t or "")
        if m:
            esp = limpiar(m.group(1))
            t = t[m.end():]
        res.append(t)
    return esp, res


def construir_evolucion(partes, fecha="", medico="", otros=()):
    """«DD/MM/AAAA - DR. NOMBRE (ESPECIALIDAD)» + los textos de `partes` en un solo párrafo (máx. 700 letras).
    La especialidad se busca también en `otros`."""
    esp, partes = especialidad_de(list(partes))
    if not esp:
        esp, _ = especialidad_de(list(otros))
    cuerpo = re.sub(r"\s*\n\s*", " ", " ".join(limpiar(x) for x in partes if limpiar(x))).strip(" -:\n")
    if len(cuerpo) > 700:
        cuerpo = cuerpo[:700].rsplit(" ", 1)[0] + "…"
    cab = encabezado_evolucion(fecha, medico, esp)
    return (f"{cab}\n{cuerpo.upper()}" if cab and cuerpo else (cuerpo.upper() or cab)), esp.upper()


def es_igual_manejo(plan):
    return bool(re.search(r"\bIGUAL(ES)?\s+MANEJO\b|\bCONTINUA\s+IGUAL\b", plan or "", re.I))


_MED = re.compile(r"^\s*\d+\)\s*(.+)$")
_DIETA = re.compile(r"^\s*(NVO|DIETA[^\n]*|ASISTIDA[^\n]*)", re.I | re.M)


def interpretar_ordenes(texto):
    """Devuelve lista de líneas: dieta + medicamentos ('MEDICAMENTO — Dosis')."""
    t = (texto or "").replace("\r", "")
    out = []
    d = _DIETA.search(t)
    if d:
        out.append(limpiar(d.group(0)))
    for linea in t.split("\n"):
        m = _MED.match(linea)
        if not m:
            continue
        s = m.group(1)
        s = re.sub(r"\s*Cantidad:\s*\S+", "", s, flags=re.I)
        s = re.sub(r"\s*Dosis:\s*", " — ", s, flags=re.I)
        out.append(limpiar(s))
    return out


def construir_tratamiento(plan, ordenes, tratamiento_actual="", medico="", fecha=""):
    """Reglas del usuario (todo en MAYÚSCULAS):
    * plan nuevo -> «PLAN\n» + líneas del plan.
    * IGUAL MANEJO -> «IGUAL MANEJO (DR. NOMBRE DD/MM/AAAA)», el tratamiento actual sin su «PLAN» ni
      un «IGUAL MANEJO (…)» anterior, y las órdenes nuevas del día que no estén ya."""
    if plan and not es_igual_manejo(plan):
        return "PLAN\n" + limpiar(plan).upper()
    base = limpiar(tratamiento_actual)
    base = re.sub(r"^\s*IGUAL(ES)?\s+MANEJO\b[^\n]*\n?", "", base, count=1, flags=re.I)
    base = re.sub(r"^\s*PLAN\b\s*:?\s*", "", base, count=1, flags=re.I).strip()
    base_n = normalizar(base)
    nuevas = [o for o in ordenes if normalizar(o) not in base_n]
    quien = " ".join(x for x in (nombre_dr(medico), (fecha or "").split(" ")[0]) if x)
    cab = f"IGUAL MANEJO ({quien})" if quien else "IGUAL MANEJO"
    return "\n".join(p for p in (cab, base, "\n".join(nuevas)) if p).upper()


# ------------------------------------------------------------------ pacientes que piden valoración por cirugía general
# «CIRUGIA» / «CX» seguida de otra especialidad no es cirugía general (se compara sin tildes, ya normalizado)
OTRAS_CIRUGIAS = ("PLASTICA", "ESTETICA", "REPARADORA", "VASCULAR", "CARDIOVASCULAR", "CARDIACA", "CARDIOTORACICA",
                  "TORAX", "TORACICA", "PEDIATRICA", "MANO", "MAXILOFACIAL", "ORAL", "ONCOLOGICA", "ORTOPEDICA",
                  "COLUMNA", "CABEZA", "UROLOGICA", "GINECOLOGICA", "NEUROLOGICA", "OFTALMOLOGICA", "COLON",
                  "COLORRECTAL", "BARIATRICA", "TRASPLANTES")
_DISPARADORES = (r"VALORACION|VALORADO|VALORADA|VALORAR|VAL|SS|S/S|IC|INTERCONSULTA|SGTO|SEGUIMIENTO|CARGO\s+DE"
                 r"|A\s+CARGO|POR|X")
_SEP = r"[\s.:,;\-]+"
_CX_GENERAL = re.compile(r"(?<![A-Z0-9])(?:CIRUGIA|CIR|CX)[\s.\-]*(?:GENERAL|GRAL)(?![A-Z0-9])")
_CX_DISPARADA = re.compile(r"(?<![A-Z0-9/])(?:%s)%s(?:(?:POR|X|DE|DEL|A)%s)*(?:CIRUGIA|CX)(?![A-Z0-9])"
                           % (_DISPARADORES, _SEP, _SEP))
_OTRA_ESPECIALIDAD = re.compile(r"[\s.]*(?:(?:DE|DEL|LA)\s+)?(?:%s)(?![A-Z0-9])" % "|".join(OTRAS_CIRUGIAS))


def menciona_cirugia(texto):
    """True si el texto pide/anota valoración o seguimiento por CIRUGÍA GENERAL: «CIRUGIA GENERAL», «CX GENERAL»,
    «CX GRAL» o un disparador (VALORACION, VAL, SS, S/S, IC, INTERCONSULTA, SGTO, SEGUIMIENTO, A CARGO, POR, X…)
    seguido —con «POR»/«X»/«DE» opcionales en medio— de «CIRUGIA» o «CX» como palabra. No cuenta cirugía de otra
    especialidad (OTRAS_CIRUGIAS), ni NEUROCIRUGIA, ni «QX» (pre quirúrgico), ni el «CX POR …» de antecedentes
    quirúrgicos (ahí «CX» va antes del «POR», no después)."""
    t = normalizar(texto)
    if _CX_GENERAL.search(t):
        return True
    return any(not _OTRA_ESPECIALIDAD.match(t, m.end()) for m in _CX_DISPARADA.finditer(t))


# ------------------------------------------------------------------ imágenes diagnósticas (columna IMAGENES / NOTAS)
@dataclass
class EstudioImagen:
    """Un «INFORME DE IMAGENOLOGIA» de la historia (pestaña EXAMEN)."""
    fecha: str                # «DD/MM/AA»
    tipo: str = ""            # «ECOGRAFÍA» (combo TIPO ESTUDIO)
    estudio: str = ""         # «TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA»
    texto: str = ""           # informe tal cual
    numero: str = ""          # N° de formato (a mayor número, más reciente)


_MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
          "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
          "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SEP": 9, "SEPT": 9,
          "OCT": 10, "NOV": 11, "DIC": 12}
_FECHA_ISO = re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_FECHA_NUM = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})(?!\d)")
_FECHA_LETRAS = re.compile(r"(?<!\d)(\d{1,2})\s*(?:DE\s+)?([A-Z]{3,10})\.?\s*(?:DEL?\s+)?(\d{4}|\d{2})(?!\d)")


def _dd_mm_aa(d, m, a):
    d, m, a = int(d), int(m), int(a)
    return f"{d:02d}/{m:02d}/{a % 100:02d}" if 1 <= d <= 31 and 1 <= m <= 12 else ""


def _una_fecha(texto):
    t = normalizar(texto)
    m = _FECHA_ISO.search(t)
    if m:
        return _dd_mm_aa(m.group(3), m.group(2), m.group(1))
    m = _FECHA_NUM.search(t)
    if m:
        return _dd_mm_aa(m.group(1), m.group(2), m.group(3))
    for m in _FECHA_LETRAS.finditer(t):
        mes = _MESES.get(m.group(2))
        if mes:
            return _dd_mm_aa(m.group(1), mes, m.group(3))
    return ""


def fecha_corta(texto, respaldo=""):
    """«19/10/26». Entiende «19 DE OCTUBRE DEL 2026», «19 de octubre de 2026», «19/10/2026», «19/10/26»,
    «2026-10-19», con o sin hora. Si no entiende `texto` usa `respaldo` (p. ej. la Fecha Hora de la grilla);
    si tampoco, ''."""
    return _una_fecha(texto) or _una_fecha(respaldo)


# abreviaturas equivalentes del tipo de estudio (sin tildes): «ECO» = «ECOGRAFIA», «TAC» = «TOMOGRAFIA»…
_FAMILIAS_IMAGEN = (("ECO", "ECOGRAFIA", "ECOGRAFICA"),
                    ("TAC", "TC", "TOMOGRAFIA", "TOMOGRAFICA"),
                    ("RX", "RADIOGRAFIA", "RADIOGRAFICA", "RAYOS", "RAYO"),
                    ("RM", "RMN", "RESONANCIA"),
                    ("DOPPLER", "ECODOPPLER"),
                    ("GAMMAGRAFIA", "GAMAGRAFIA"),
                    ("ANGIO", "ANGIOGRAFIA", "ANGIOTAC"),
                    ("COLANGIO", "COLANGIOGRAFIA", "COLANGIORM", "COLANGIORMN"),
                    ("MAMOGRAFIA", "MAMO"),
                    ("UROGRAFIA", "UROTAC"),
                    ("FLUOROSCOPIA", "FLUORO"))


def _misma_familia(a, b):
    if a == b:
        return True
    for fam in _FAMILIAS_IMAGEN:
        if all(w in fam or any(len(f) >= 6 and w.startswith(f) for f in fam) for w in (a, b)):
            return True
    return False


def _fecha_de(e):
    """La fecha del estudio como «DD/MM/AA» (por si llegó escrita de otra forma); '' si no se entiende."""
    return fecha_corta(e.fecha)


def _mayusculas(texto):
    """MAYÚSCULAS (con tildes), espacios colapsados, sin «:» al final."""
    return " ".join((texto or "").upper().split()).rstrip(" :")


def titulo_imagen(e):
    """«ECOGRAFÍA TEJIDOS BLANDOS EN LA REGIÓN DORSAL LINEA MEDIA 19/10/26»: el ESTUDIO en mayúsculas; si no empieza
    por el tipo (ni una abreviatura de él: ECO/ECOGRAFIA, TAC/TOMOGRAFIA, RX/RADIOGRAFIA, RM/RESONANCIA…) se le antepone
    el TIPO ESTUDIO (sin agregar «DE»). Sin fecha no se agrega."""
    estudio, tipo = _mayusculas(e.estudio), _mayusculas(e.tipo)
    pe, pt = (normalizar(estudio).split() or [""])[0], (normalizar(tipo).split() or [""])[0]
    nombre = estudio if not tipo or (estudio and _misma_familia(pe, pt)) else " ".join(x for x in (tipo, estudio) if x)
    return " ".join(x for x in (nombre or "ESTUDIO DE IMAGENOLOGIA", _fecha_de(e)) if x)


def _texto_informe(texto):
    """El informe tal cual (sin pasar a mayúsculas): sin espacios al final de renglón ni renglones vacíos repetidos."""
    out = []
    for linea in (texto or "").replace("\r", "").replace("\xa0", " ").split("\n"):
        linea = linea.rstrip()
        if linea or (out and out[-1]):
            out.append(linea)
    return "\n".join(out).strip("\n")


def bloque_imagen(e):
    """Título + «\n» + informe. Sin informe, solo el título."""
    texto = _texto_informe(e.texto)
    return titulo_imagen(e) + ("\n" + texto if texto else "")


def _pegado(texto):
    """Normalizado y sin ningún espacio (para buscar un texto dentro de otro sin importar los saltos de renglón)."""
    return re.sub(r"\s+", "", normalizar(texto))


def _con_fecha(linea, fecha):
    """El renglón trae la fecha «DD/MM/AA» escrita 19/10/26, 19/10/2026, 19-10-2026, 19-10-26 o 19/10 (con o sin
    ceros). Si trae año y es otro, no es la misma fecha."""
    if not re.match(r"\d{2}/\d{2}/\d{2}$", fecha or ""):
        return False
    for m in re.finditer(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{4}|\d{2})(?!\d))?", linea):
        if f"{int(m.group(1)):02d}/{int(m.group(2)):02d}" == fecha[:5] and (not m.group(3) or m.group(3)[-2:] == fecha[6:]):
            return True
    return False


def imagen_ya_esta(e, celda):
    """True si el estudio ya está en la celda IMAGENES / NOTAS (sin importar tildes, mayúsculas ni espacios):
    (a) está su título; (b) están los primeros ~60 caracteres de su informe (si tiene >= 20); o (c) algún renglón
    trae su fecha (19/10/26, 19/10/2026, 19-10-2026, 19/10…) y al menos 2 palabras (>= 4 letras) del ESTUDIO
    (si el estudio tiene una sola palabra así, basta con ella)."""
    celda = celda or ""
    pegada = _pegado(celda)
    if _pegado(titulo_imagen(e)) in pegada:
        return True
    texto = normalizar(e.texto)
    if len(texto) >= 20 and _pegado(texto[:60]) in pegada:
        return True
    palabras = sorted(set(re.findall(r"[A-Z]{4,}", normalizar(e.estudio))))
    if not palabras:
        return False
    for linea in celda.split("\n"):
        if _con_fecha(linea, _fecha_de(e)):
            n = normalizar(linea)
            if sum(p in n for p in palabras) >= min(2, len(palabras)):
                return True
    return False


def _clave_reciente(e):
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})$", _fecha_de(e))
    fecha = (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else (0, 0, 0)
    return fecha + (int(e.numero) if str(e.numero).isdigit() else 0,)


def imagenes_nuevas(estudios, celda):
    """Los estudios que NO están en la celda, sin repetidos (mismo título) y del más reciente al más antiguo."""
    vistos, nuevos = set(), []
    for e in sorted(estudios or [], key=_clave_reciente, reverse=True):
        clave = _pegado(titulo_imagen(e))
        if clave in vistos:
            continue
        vistos.add(clave)
        if not imagen_ya_esta(e, celda):
            nuevos.append(e)
    return nuevos


def unir_bloques(estudios):
    """Los bloques de los estudios (ya ordenados) separados por un renglón vacío."""
    return "\n\n".join(bloque_imagen(e) for e in estudios)


# --- dónde y cómo se inserta en la celda
_SUBTITULO_IMAGENES = re.compile(r"^IMAGENES(?:\s+(?:Y|E|/)?\s*[A-Z]+){0,3}\s*:?$")
_FECHA_AL_FINAL = re.compile(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\s*:?$")


def es_subtitulo_imagenes(linea):
    """Renglón corto «IMÁGENES» / «IMÁGENES Y PROCEDIMIENTO» (subtítulo que a veces tiene la celda)."""
    t = normalizar(linea)
    return len(t) <= 40 and bool(_SUBTITULO_IMAGENES.match(t))


def punto_insercion_imagenes(renglones):
    """Índice del renglón (párrafo) de la celda ANTES del cual se insertan los estudios nuevos: el siguiente al
    subtítulo «IMÁGENES…» si la celda lo tiene; si no, 0 (arriba de todo)."""
    for i, linea in enumerate(renglones):
        if es_subtitulo_imagenes(linea):
            return i + 1
    return 0


def lineas_titulo_imagen(texto):
    """Índices de los renglones de `texto` (bloques unidos con unir_bloques) que son título de un bloque: el primero
    y los que siguen a un renglón vacío, están en MAYÚSCULAS (el informe va tal cual) y terminan en fecha."""
    lineas = texto.split("\n")
    return {i for i, x in enumerate(lineas)
            if i == 0 or (not lineas[i - 1].strip() and x.strip() and x == x.upper() and _FECHA_AL_FINAL.search(x))}


def insertar_imagenes(celda, insertar):
    """Texto de la celda IMAGENES / NOTAS después de agregar `insertar` (arriba, o justo debajo del subtítulo
    «IMÁGENES…»), con un renglón vacío de separación si queda contenido debajo."""
    lineas = (celda or "").split("\n")
    k = punto_insercion_imagenes(lineas)
    if any(x.strip() for x in lineas[k:]):
        return "\n".join(lineas[:k] + insertar.split("\n") + [""] + lineas[k:])
    return "\n".join(lineas[:k] + insertar.split("\n"))      # debajo solo hay renglones vacíos
