"""Compara lo encontrado en el sistema con lo que hay en el kardex."""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from notas import imagenes_nuevas, insertar_imagenes, menciona_cirugia, normalizar, unir_bloques


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
    documento: str = ""         # solo el número («CC - 123» -> «123»)
    tipo_documento: str = ""
    admision: str = ""
    estado: str = ""
    imagenes: list = field(default_factory=list)    # list[notas.EstudioImagen] de los informes de imagenología
    edad: str = ""


@dataclass
class PacienteEntrega:
    """Una fila con paciente de un documento «ENTREGAS CRC» (solo se lee, nunca se escribe)."""
    nombre: str
    documento: str = ""         # solo el número
    tipo_documento: str = ""
    edad: str = ""
    habitacion: str = ""
    datos: str = ""             # texto de la celda DATOS tal cual
    texto: str = ""             # todo el texto de la fila (para menciona_cirugia)
    doc: str = ""               # nombre del documento de entregas («PISO 6»)
    servicio: str = ""          # título limpio de la tabla donde está (si hay)


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
    imagenes: str = ""              # celda «IMAGENES / NOTAS»
    col_imagenes: object = None

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
    def tipo_documento(self):
        return interpretar_datos(self.datos)["tipo_documento"]

    @property
    def edad(self):
        return interpretar_datos(self.datos)["edad"]


@dataclass
class Accion:
    tipo: str               # ACTUALIZAR | AGREGAR | MOVER | RETIRAR | REVISAR
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
    destino: str = ""       # MOVER / AGREGAR: servicio de la tabla destino
    tabla_destino: object = None    # MOVER / AGREGAR: índice de esa tabla en el documento (None = no se sabe)
    insertar: str = ""      # IMÁGENES / NOTAS: texto que se INSERTA en la celda (no la reemplaza)
    fila_nueva: dict = field(default_factory=dict)  # AGREGAR: columna -> texto de la fila nueva
    habitacion_nueva: str = ""      # HABITACIÓN / MOVER: código de habitación que queda en DATOS

    @property
    def automatica(self):
        """Se puede escribir sola: ACTUALIZAR de una fila, MOVER a una tabla conocida o AGREGAR a una tabla conocida."""
        return ((self.tipo == "ACTUALIZAR" and self.fila is not None)
                or (self.tipo == "MOVER" and self.fila is not None and self.tabla_destino is not None)
                or (self.tipo == "AGREGAR" and self.tabla_destino is not None))


@dataclass
class TablaKardex:
    """Una tabla (servicio) del kardex, para decidir a cuál va un paciente según su habitación."""
    indice: int             # posición entre las tablas del documento (igual que FilaKardex.tabla)
    servicio: str           # título limpio: «PISO 4A»
    titulo: str = ""        # título tal cual: «PISO 4A ( 4 PACIENTES) 422 - 430»
    rango: object = None    # (desde, hasta) de habitaciones; hasta=None: «430 EN ADELANTE»; None: sin rango
    filas_pacientes: int = 0


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


_RE_IDENT = re.compile(r"^\s*([A-Za-z]{1,4})?[\s:.\-]*(\d[\d.\s]*)")


def parsear_identificacion(texto):
    """«CC - 1044618156» (a veces partido en 2 renglones) -> («CC», «1044618156»). ("", "") si no hay número."""
    t = " ".join((texto or "").split())
    m = _RE_IDENT.match(t)
    if not m:
        return "", ""
    return (m.group(1) or "").upper(), re.sub(r"\D", "", m.group(2))


MODOS_AGENDA = ("Urgencias", "Hospitalización")


def modo_preferido(servicio):
    """Servicio del kardex -> modo de la Agenda donde probablemente está: URGENCIAS… -> Urgencias."""
    return "Urgencias" if normalizar(servicio).startswith("URGENCIAS") else "Hospitalización"


def _sin_ceros(c):
    return re.sub(r"(?<!\d)0+(?=\d)", "", c)


def _codigo_hab(h):
    t = normalizar(h)
    t = re.sub(r"\b(CUBICULO|CUB|CAMA|HABITACION|HAB)\b\.?", " ", t)
    return re.sub(r"\s+", "", t)


def misma_habitacion(kardex, sistema):
    """True si la habitación del kardex corresponde a la del sistema («607» ≡ «6PISO-607», «9» ≡ «HOS82-09»).
    Si alguna no trae número (PASILLO…) no se puede decidir: se considera igual. Solo es distinta si lo es claramente."""
    k, s = _codigo_hab(kardex), _codigo_hab(sistema)
    if not k or not s or not any(c.isdigit() for c in k) or not any(c.isdigit() for c in s):
        return True
    if _sin_ceros(k) == _sin_ceros(s):
        return True
    if "-" in k:                    # el kardex trae su propio prefijo: debe coincidir entero
        return False
    return _sin_ceros(k) == _sin_ceros(s.rsplit("-", 1)[-1])


_RE_COD_PISO = re.compile(r"(?<!\d)(\d{3,4}[A-Z]?)$")


def codigo_kardex(hab_sistema):
    """Habitación como se escribe en el kardex: «6PISO-607» -> «607», «3PISO-305B» -> «305B», «10PISO-1001A» -> «1001A».
    Solo si el código del sistema es de piso (trae PISO, o su parte final es un número de 3-4 dígitos con letra
    opcional); si no («HOS82-09», «UCI5-09», «PEDIA-07», «PASILLO») devuelve ''."""
    t = normalizar(hab_sistema).replace(" ", "")
    final = t.rsplit("-", 1)[-1]
    if "PISO" in t:
        m = _RE_COD_PISO.search(final)
    else:
        m = _RE_COD_PISO.fullmatch(final)
    return m.group(1) if m else ""


def _palabras_servicio(texto):
    """Palabras comparables de un servicio o del nombre de un documento de entregas."""
    t = re.sub(r"\bPISOS\b", "PISO", normalizar(texto))
    return {w for w in re.findall(r"[A-Z0-9]+", t) if w not in ("CARRERA", "CALLE", "CRA", "CL")}


def servicio_destino(hab_sistema, tablas, doc_entregas=""):
    """TablaKardex a la que va un paciente según su habitación del sistema, o None si no se sabe.
    1. Con código de piso (607, 305B, 1001A): piso = número // 100 y candidatas «PISO <piso>[letra]»; con varias
       (4A, 4B, 4C) la que tenga la habitación en su rango (la primera si dos la tienen, p. ej. 430); si ninguna, None.
    2. Sin código (o sin tablas candidatas): la tabla cuyas palabras estén todas en el nombre del documento de
       entregas donde aparece el paciente («URGENCIAS CARRERA 47» -> «URGENCIAS 47»); si coinciden varias
       («PISOS 10 Y 11») o ninguna, None."""
    tablas = list(tablas)
    codigo = codigo_kardex(hab_sistema)
    if codigo:
        n = int(re.sub(r"\D", "", codigo))
        piso = n // 100
        cand = [t for t in tablas if re.match(r"PISO\s*%d[A-Z]?(?![A-Z0-9])" % piso, normalizar(t.servicio))]
        if len(cand) == 1:
            return cand[0]
        if cand:
            return next((t for t in cand if t.rango and t.rango[0] <= n and (t.rango[1] is None or n <= t.rango[1])),
                        None)
    palabras_doc = _palabras_servicio(doc_entregas)
    if palabras_doc:
        cand = [t for t in tablas if _palabras_servicio(t.servicio) and _palabras_servicio(t.servicio) <= palabras_doc]
        if len(cand) == 1:
            return cand[0]
    return None


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


def buscar_paciente(nombre, documento, pacientes):
    """PacienteSistema de la lista que corresponde al del kardex: primero por documento (sin importar el
    nombre), luego por nombre. None si no hay coincidencia clara."""
    pacientes = list(pacientes)
    doc = re.sub(r"\D", "", documento or "")
    if doc:
        for p in pacientes:
            if p.documento and re.sub(r"\D", "", p.documento) == doc:
                return p
    por_nombre = {}
    for p in pacientes:
        if doc and p.documento and re.sub(r"\D", "", p.documento) != doc:
            continue                    # otro documento: es otra persona con nombre parecido
        por_nombre.setdefault(p.nombre, p)
    nom = emparejar(nombre, por_nombre.keys(), documento)
    return por_nombre.get(nom) if nom else None


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


def candidatos_cirugia(entregas):
    """Pacientes de los documentos de entregas cuya fila menciona valoración por cirugía general, sin repetidos
    (mismo documento o mismo nombre)."""
    out = []
    for e in entregas:
        if not menciona_cirugia(e.texto):
            continue
        doc = re.sub(r"\D", "", e.documento or "")
        if any((doc and doc == re.sub(r"\D", "", x.documento or "")) or normalizar(e.nombre) == normalizar(x.nombre)
               for x in out):
            continue
        out.append(e)
    return out


_COLUMNAS_FILA_NUEVA = ("DATOS", "DX", "EVOLUCIÓN", "TRATAMIENTO", "IMÁGENES / NOTAS")


def _datos_fila_nueva(p, e, nombre):
    """Celda DATOS de un paciente nuevo: habitación, nombre (como está en la entrega), edad y «CC 123»."""
    hab = codigo_kardex(p.habitacion) or e.habitacion
    doc = e.documento or p.documento
    ident = " ".join(x for x in ((e.tipo_documento or p.tipo_documento) if doc else "", doc) if x)
    return "\n".join(x for x in (hab, nombre, e.edad or p.edad, ident) if x)


def _agregar(p, e, tablas):
    """Acción AGREGAR de un paciente que está en las entregas (con cirugía) y no en el kardex."""
    d = servicio_destino(p.habitacion, tablas, e.doc)
    codigo = codigo_kardex(p.habitacion)
    nombre = " ".join((e.nombre or p.nombre).upper().split())
    fila = {"DATOS": _datos_fila_nueva(p, e, nombre), "DX": p.dx, "EVOLUCIÓN": p.evolucion, "TRATAMIENTO": p.tratamiento,
            "IMÁGENES / NOTAS": unir_bloques(imagenes_nuevas(p.imagenes, ""))}
    fila = {c: t for c, t in fila.items() if t}
    nuevo = "\n\n".join(f"{c}\n{fila[c]}" for c in _COLUMNAS_FILA_NUEVA if c in fila)
    donde = f"en las entregas ({e.doc})" if e.doc else "en las entregas"
    aviso = f". Aviso: {p.aviso}" if p.aviso else ""
    if d is None:
        return Accion("AGREGAR", nombre, "", "", nuevo, None,
                      f"No sé en qué tabla va (habitación {p.habitacion or 'sin dato'}): agrégalo a mano. "
                      f"Está {donde} con valoración por cirugía y no en el kardex" + aviso,
                      marcada=False, servicio=e.servicio or e.doc or p.modo, habitacion=codigo or p.habitacion,
                      sis=p, fila_nueva=fila, habitacion_nueva=codigo)
    return Accion("AGREGAR", nombre, "", "", nuevo, None,
                  f"Está {donde} con valoración por cirugía y no en el kardex: fila nueva en {d.servicio}" + aviso,
                  servicio=d.servicio, habitacion=codigo or p.habitacion, sis=p, destino=d.servicio,
                  tabla_destino=d.indice, fila_nueva=fila, habitacion_nueva=codigo)


def _otra_tabla(fila, p, tablas, entregas):
    """True si la habitación del sistema es de piso y lleva a una tabla del kardex distinta de la de la fila."""
    if not codigo_kardex(p.habitacion):
        return False
    ent = buscar_paciente(fila.nombre, fila.documento, entregas)
    d = servicio_destino(p.habitacion, tablas, ent.doc if ent else "")
    return d is not None and d.indice != fila.tabla and normalizar(d.servicio) != normalizar(fila.servicio)


def _cambio_de_habitacion(fila, p, tablas, entregas):
    """Qué hacer cuando la habitación del sistema no coincide con la del kardex (lista de Accion)."""
    codigo = codigo_kardex(p.habitacion)
    revisar = Accion("REVISAR", fila.nombre, "HABITACIÓN", fila.habitacion, p.habitacion, fila,
                     "Habitación distinta (cambiar a mano; puede requerir mover de servicio)",
                     marcada=False, servicio=fila.servicio, habitacion=fila.habitacion, sis=p)
    if not codigo:
        return [revisar]
    ent = buscar_paciente(fila.nombre, fila.documento, entregas)
    d = servicio_destino(p.habitacion, tablas, ent.doc if ent else "")
    if d is None:
        revisar.detalle = ("Habitación distinta y no sé a qué tabla del kardex corresponde (cambiar a mano; "
                           "puede requerir mover de servicio)") if tablas else revisar.detalle
        return [revisar]
    if d.indice != fila.tabla and normalizar(d.servicio) != normalizar(fila.servicio):
        donde = " · ".join(x for x in (fila.servicio, fila.habitacion) if x)
        return [Accion("MOVER", fila.nombre, "HABITACIÓN", donde, f"{d.servicio} · {codigo}", fila,
                       f"Cambió de piso: estaba en {fila.servicio}, el sistema dice {p.habitacion} → va a {d.servicio}",
                       servicio=fila.servicio, habitacion=fila.habitacion, sis=p, destino=d.servicio,
                       tabla_destino=d.indice, habitacion_nueva=codigo)]
    return [Accion("ACTUALIZAR", fila.nombre, "HABITACIÓN", fila.habitacion, codigo, fila,
                   f"Cambió de habitación: el sistema dice {p.habitacion}",
                   servicio=fila.servicio, habitacion=fila.habitacion, sis=p, habitacion_nueva=codigo)]


def comparar(sistema, kardex, nuevos=(), tablas=(), entregas=()):
    """Devuelve lista de Accion.
    sistema: list[PacienteSistema]; kardex: list[FilaKardex].
    nuevos: pares (PacienteSistema, PacienteEntrega) de pacientes que las entregas mandan a cirugía general y que NO
        están en el kardex (el PacienteSistema ya con su detalle; la PacienteEntrega aporta nombre, edad y documento
        tal como están en las entregas). Cada par genera una acción AGREGAR.
    tablas: list[TablaKardex] (kardex_doc.tablas_kardex) para saber a qué tabla va una habitación; sin ellas no hay
        MOVER ni se puede decidir el destino de un AGREGAR.
    entregas: list[PacienteEntrega] para saber en qué documento de entregas está un paciente del kardex
        (desempata el servicio cuando la habitación no alcanza)."""
    acciones = []
    for fila in kardex:
        p = buscar_paciente(fila.nombre, fila.documento, sistema)
        if not p:
            acciones.append(Accion("RETIRAR", fila.nombre, "", _resumen(fila.nombre, fila.habitacion, fila.dx), "",
                                   fila, f"No aparece en el sistema (¿alta?). Está en {fila.servicio}.",
                                   marcada=False, servicio=fila.servicio, habitacion=fila.habitacion))
            continue
        if p.aviso:
            acciones.append(Accion("REVISAR", fila.nombre, detalle=p.aviso, fila=fila, marcada=False,
                                   servicio=fila.servicio, habitacion=fila.habitacion, sis=p))
        if p.habitacion and fila.habitacion and not misma_habitacion(fila.habitacion, p.habitacion):
            acciones.extend(_cambio_de_habitacion(fila, p, tablas, entregas))
        elif p.habitacion and _otra_tabla(fila, p, tablas, entregas):
            # sin número en el kardex (PASILLO, CUB 12…) pero el sistema dice otro piso: también se mueve
            acciones.extend(_cambio_de_habitacion(fila, p, tablas, entregas))
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
        faltan = imagenes_nuevas(p.imagenes, fila.imagenes) if fila.col_imagenes is not None else []
        if faltan:                          # los estudios nuevos se INSERTAN arriba; lo que ya hay no se toca
            insertar = unir_bloques(faltan)
            acciones.append(Accion("ACTUALIZAR", fila.nombre, "IMÁGENES / NOTAS", fila.imagenes,
                                   insertar_imagenes(fila.imagenes, insertar), fila,
                                   f"{len(faltan)} estudio(s) nuevo(s) de imágenes",
                                   servicio=fila.servicio, habitacion=fila.habitacion, sis=p, insertar=insertar))
    for p, e in nuevos:
        acciones.append(_agregar(p, e, tablas))
    return acciones
