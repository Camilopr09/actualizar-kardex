"""Interpreta hojas de evolución y órdenes médicas (texto libre) de Hospital Office."""
import re
import unicodedata


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
