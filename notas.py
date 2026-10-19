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


def interpretar_evolucion(texto, fecha="", medico=""):
    """Devuelve dict con dx, evolucion, plan a partir del texto libre de la nota."""
    t = limpiar(texto)
    dx = ""
    m = _DX.search(t)
    if m:
        resto = t[m.end():]
        corte = _CORTE_DX.search(resto)
        dx = resto[: corte.start()] if corte else resto
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
        cuerpo = cuerpo[m.end() + len(dx):]
    cuerpo = re.sub(r"\s*\n\s*", " ", cuerpo).strip(" -:\n")
    if len(cuerpo) > 700:
        cuerpo = cuerpo[:700].rsplit(" ", 1)[0] + "…"
    prefijo = " ".join(p for p in (fecha, medico) if p)
    evolucion = f"{prefijo}: {cuerpo}" if prefijo and cuerpo else (cuerpo or prefijo)
    return {"dx": dx, "evolucion": evolucion, "plan": plan}


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


def construir_tratamiento(plan, ordenes, tratamiento_actual=""):
    """Reglas del usuario: plan del especialista; si dice IGUAL MANEJO se conserva
    el tratamiento actual y se agrega lo nuevo de las órdenes del día."""
    if plan and not es_igual_manejo(plan):
        return limpiar(plan)
    base = limpiar(tratamiento_actual)
    base_n = normalizar(base)
    nuevas = [o for o in ordenes if normalizar(o) not in base_n]
    partes = [p for p in (base, "\n".join(nuevas)) if p]
    if plan and not base:
        partes.insert(0, limpiar(plan))
    return "\n".join(partes)
