"""Compara lo encontrado en el sistema con lo que hay en el kardex."""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from notas import normalizar


@dataclass
class PacienteSistema:
    nombre: str
    habitacion: str = ""
    modo: str = ""          # Urgencias / Hospitalización
    medico: str = ""
    fecha: str = ""
    dx: str = ""
    evolucion: str = ""
    tratamiento: str = ""   # ya construido con las reglas
    encontrado_detalle: bool = False
    aviso: str = ""


_TIPOS_DOC = ("CC", "TI", "RC", "CE", "PA", "PE", "PT", "MS", "AS", "CN", "NIT", "PP")
_RE_DOC = re.compile(r"^(%s)\b[\s:.\-]*(\d[\d.]*)" % "|".join(_TIPOS_DOC), re.I)
_RE_EDAD = re.compile(r"^\d+\s*(A[ÑN]OS?|MESES|MES|D[IÍ]AS?)\b", re.I)
_RE_FECHA_INGRESO = re.compile(r"^(FIP?|FECHA)\b[\s:.]*\d", re.I)
# palabras de lugar: van a habitación aunque no traigan número
_RE_HAB_PALABRA = re.compile(
    r"^(EX\s+T[OÓ]RAX|PASILLO|CUBICULO|CUBÍCULO|CUB|SALA|OBSERVACI[OÓ]N|AISLAMIENTO|TRIAGE|CAMA|"
    r"HABITACION|HABITACIÓN|HAB)\b", re.I)
# 12, 435A, 420B, 601, H-1, 2-01, UCI5-09, H4CAM-06, HOS82-11
_RE_HAB_CODIGO = re.compile(r"^[A-Z]{0,5}[- ]?\d{1,4}[A-Z]{0,4}(-\d{1,3})?$", re.I)
_RE_NOMBRE = re.compile(r"^[^\W\d_]+(?:[ .'\-]+[^\W\d_]+)*\.?$")


_SIGLAS = {"STT", "ASL", "UCI", "UCE", "NPO", "SNG", "EPS"}      # siglas sueltas: nunca son parte del nombre


def _corta(l):
    """Una sola palabra de 4 letras o menos (STT, ASL, AL)."""
    return len(l.split()) == 1 and len(l.strip(".")) <= 4


def interpretar_datos(texto):
    """Interpreta la celda DATOS (un renglón por párrafo, con renglones vacíos):
    habitación (código o palabra de lugar, a veces ausente), nombre (primer bloque de renglones
    solo letras con >= 2 palabras en total), edad («59 AÑOS»), documento («CC - 123» -> «123»).
    Ignora el resto (FIP, FI, STT, notas). Funciona también con el formato antiguo."""
    hab = edad = doc = tipo = ""
    nombre, bloque = [], []         # bloque: renglones solo-letras consecutivos que se está leyendo
    def cerrar():
        nonlocal nombre, bloque
        if not nombre and sum(len(x.split()) for x in bloque) >= 2:
            nombre = bloque
        bloque = []
    for linea in (texto or "").split("\n"):
        l = " ".join(linea.split())
        if not l:
            continue
        m = _RE_DOC.match(l)
        if m:
            cerrar()
            if not doc:
                tipo, doc = m.group(1).upper(), m.group(2).replace(".", "")
        elif _RE_EDAD.match(l):
            cerrar()
            edad = edad or l
        elif _RE_FECHA_INGRESO.match(l):
            cerrar()
        elif _RE_HAB_PALABRA.match(l) or (_RE_HAB_CODIGO.match(l) and any(c.isdigit() for c in l)):
            cerrar()
            hab = hab or l
        elif _RE_NOMBRE.match(l):
            if _corta(l) and not bloque:
                cerrar()
                if not hab and not nombre:      # «ASL» antes del nombre: ubicación
                    hab = l
            elif len(bloque) < 4 and l.upper() not in _SIGLAS:
                bloque.append(l)
            else:
                cerrar()
        else:
            cerrar()
    cerrar()
    return {"habitacion": hab, "nombre": " ".join(nombre), "edad": edad, "documento": doc, "tipo_documento": tipo}


_RE_DX = re.compile(r"^\s*DX\b\s*:?\s*", re.I)
_RE_PLAN = re.compile(r"^\s*PLAN\b\s*:?\s*", re.I)
_RE_IGUAL = re.compile(r"^\s*IGUAL(ES)?\s+MANEJO\b[^\n]*\n?", re.I)


def quitar_prefijo(campo, texto):
    """Quita el encabezado del campo: «DX:» (DX); «PLAN» o «IGUAL MANEJO (…)» (TRATAMIENTO)."""
    t = texto or ""
    if campo == "DX":
        return _RE_DX.sub("", t, count=1).strip()
    if campo == "TRATAMIENTO":
        t = _RE_IGUAL.sub("", t, count=1)
        return _RE_PLAN.sub("", t, count=1).strip()
    return t


def con_prefijo(campo, nuevo, actual):
    """DX: si la celda actual empieza con «DX», el texto nuevo se escribe como «DX:\\n…».
    TRATAMIENTO: si el nuevo ya trae su encabezado (PLAN / IGUAL MANEJO) se deja; si no, y la celda
    actual empieza con «PLAN», se antepone «PLAN\\n»."""
    if campo == "DX" and _RE_DX.match(actual or ""):
        return "DX:\n" + quitar_prefijo(campo, nuevo)
    if campo == "TRATAMIENTO" and not (_RE_PLAN.match(nuevo or "") or _RE_IGUAL.match(nuevo or "")) \
            and _RE_PLAN.match(actual or ""):
        return "PLAN\n" + quitar_prefijo(campo, nuevo)
    return nuevo


@dataclass
class FilaKardex:
    tabla: int              # índice de tabla dentro del documento
    fila: int               # índice de fila dentro de la tabla
    servicio: str
    datos: str
    dx: str = ""
    evolucion: str = ""
    tratamiento: str = ""
    # índice de columna (según el ENCABEZADO de la tabla) de cada campo; None = la tabla no lo tiene
    col_dx: object = 1
    col_evolucion: object = 2
    col_tratamiento: object = 3

    @property
    def nombre(self):
        return interpretar_datos(self.datos)["nombre"]

    @property
    def habitacion(self):
        return interpretar_datos(self.datos)["habitacion"]

    @property
    def documento(self):
        """Número de documento (sin el tipo) o ''."""
        return interpretar_datos(self.datos)["documento"]

    @property
    def edad(self):
        return interpretar_datos(self.datos)["edad"]


@dataclass
class Accion:
    tipo: str               # ACTUALIZAR | AGREGAR | RETIRAR | REVISAR
    paciente: str
    campo: str = ""
    actual: str = ""
    nuevo: str = ""
    fila: object = None
    detalle: str = ""
    marcada: bool = True
    servicio: str = ""
    habitacion: str = ""
    sis: object = None      # PacienteSistema relacionado (o None)

    @property
    def automatica(self):
        return self.tipo == "ACTUALIZAR" and self.fila is not None


def _tokens(nombre):
    return [t for t in normalizar(nombre).split() if len(t) > 2]


def _sim(x, y):
    """Similitud 0..1 entre dos palabras normalizadas; 0 si no se parecen lo suficiente."""
    if x == y:
        return 1.0
    r = SequenceMatcher(None, x, y).ratio()
    if r >= 0.8:
        return r
    if min(len(x), len(y)) >= 4 and (x.startswith(y) or y.startswith(x)):
        return 0.8
    return 0.0


def _puntaje(a, b):
    """(proporción, coincidencias, suma de similitudes) de las palabras de a con las de b (1 a 1)."""
    libres = list(b)
    n, suma = 0, 0.0
    for t in a:
        mejor, mejor_s = None, 0.0
        for u in libres:
            s = _sim(t, u)
            if s > mejor_s:
                mejor, mejor_s = u, s
        if mejor is not None:
            libres.remove(mejor)
            n += 1
            suma += mejor_s
    return (n / min(len(a), len(b)), n, round(suma, 6))


def emparejar(nombre_kardex, candidatos, documento=""):
    """Busca el nombre del kardex entre los nombres del sistema. Tolera errores de escritura,
    tildes y el orden APELLIDOS NOMBRES. Devuelve None si no hay coincidencia clara o si dos
    candidatos empatan (para no mezclar pacientes). Si hay documento y un único candidato lo
    contiene, empareja directo."""
    candidatos = list(candidatos)
    doc = re.sub(r"\D", "", documento or "")
    if doc:
        con_doc = [c for c in candidatos if doc in re.sub(r"[\s.]", "", c)]
        if len(con_doc) == 1:
            return con_doc[0]
    a = _tokens(nombre_kardex)
    if not a:
        return None
    puntajes = []
    for c in candidatos:
        b = _tokens(c)
        if not b:
            continue
        p = _puntaje(a, b)
        if p[1] >= 2 and p[0] >= 0.6:
            puntajes.append((p, c))
    if not puntajes:
        return None
    puntajes.sort(key=lambda x: x[0], reverse=True)
    if len(puntajes) > 1 and puntajes[0][0] == puntajes[1][0]:
        return None
    return puntajes[0][1]


def _igual(a, b):
    return normalizar(a) == normalizar(b)


def _igual_campo(campo, a, b):
    """Igual ignorando mayúsculas, tildes, espacios y los prefijos «DX:» / «PLAN»."""
    return _igual(quitar_prefijo(campo, a), quitar_prefijo(campo, b))


def _resumen(nombre, habitacion, dx="", fecha="", medico=""):
    """Texto corto de un paciente: «NOMBRE · HAB», DX y última evolución."""
    lineas = [" · ".join(x for x in (nombre, habitacion) if x)]
    if dx:
        lineas.append("DX: " + dx.replace("\n", " · "))
    ev = ", ".join(x for x in (fecha, medico) if x)
    if ev:
        lineas.append("Última evolución: " + ev)
    return "\n".join(lineas)


def comparar(sistema, kardex):
    """Devuelve lista de Accion. sistema: list[PacienteSistema], kardex: list[FilaKardex]."""
    acciones = []
    por_nombre = {p.nombre: p for p in sistema}
    usados = set()
    for fila in kardex:
        nom = emparejar(fila.nombre, por_nombre.keys(), fila.documento)
        if not nom:
            acciones.append(Accion("RETIRAR", fila.nombre, "", _resumen(fila.nombre, fila.habitacion, fila.dx), "",
                                   fila, f"No aparece en el sistema (¿alta?). Está en {fila.servicio}.",
                                   marcada=False, servicio=fila.servicio, habitacion=fila.habitacion))
            continue
        usados.add(nom)
        p = por_nombre[nom]
        if p.aviso:
            acciones.append(Accion("REVISAR", fila.nombre, detalle=p.aviso, fila=fila, marcada=False,
                                   servicio=fila.servicio, habitacion=fila.habitacion, sis=p))
        if p.habitacion and fila.habitacion and not _igual(p.habitacion, fila.habitacion):
            acciones.append(Accion("REVISAR", fila.nombre, "HABITACIÓN", fila.habitacion, p.habitacion,
                                   fila, "Habitación distinta (cambiar a mano; puede requerir mover de servicio)",
                                   marcada=False, servicio=fila.servicio, habitacion=fila.habitacion, sis=p))
        if not p.encontrado_detalle:
            continue
        nota = ", ".join(x for x in (p.fecha.split(" ")[0], p.medico) if x) or "la nota más reciente"
        cols = {"DX": fila.col_dx, "EVOLUCIÓN": fila.col_evolucion, "TRATAMIENTO": fila.col_tratamiento}
        for campo, nuevo, actual, detalle in (
                ("DX", p.dx, fila.dx, f"Reemplazar por lo que dice {nota}"),
                ("EVOLUCIÓN", p.evolucion, fila.evolucion, f"Nota más reciente: {nota}"),
                ("TRATAMIENTO", p.tratamiento, fila.tratamiento, f"Plan de {nota} y órdenes del día")):
            if cols[campo] is None:         # la tabla de este servicio no tiene esa columna
                continue
            if nuevo and not _igual_campo(campo, nuevo, actual):
                acciones.append(Accion("ACTUALIZAR", fila.nombre, campo, actual, con_prefijo(campo, nuevo, actual), fila,
                                       detalle, servicio=fila.servicio, habitacion=fila.habitacion, sis=p))
    for nom, p in por_nombre.items():
        if nom not in usados:
            acciones.append(Accion("AGREGAR", p.nombre, "", "", _resumen(p.nombre, p.habitacion, p.dx, p.fecha, p.medico),
                                   None, f"En el sistema ({p.modo}, {p.habitacion}) y no en el kardex",
                                   marcada=False, servicio=p.modo, habitacion=p.habitacion, sis=p))
    return acciones
