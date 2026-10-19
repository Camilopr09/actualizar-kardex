"""Compara lo encontrado en el sistema con lo que hay en el kardex."""
from dataclasses import dataclass, field
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


@dataclass
class FilaKardex:
    tabla: int              # índice de tabla dentro del documento
    fila: int               # índice de fila dentro de la tabla
    servicio: str
    datos: str
    dx: str = ""
    evolucion: str = ""
    tratamiento: str = ""

    @property
    def nombre(self):
        return (self.datos.split("\n")[0] if self.datos else "").strip()

    @property
    def habitacion(self):
        for linea in self.datos.split("\n")[1:]:
            if linea.strip():
                return linea.strip()
        return ""


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
    return {t for t in normalizar(nombre).split() if len(t) > 2}


def emparejar(nombre_kardex, candidatos):
    """Busca el nombre del kardex entre los nombres del sistema (por palabras en común)."""
    a = _tokens(nombre_kardex)
    if not a:
        return None
    mejor, mejor_p = None, 0.0
    for c in candidatos:
        b = _tokens(c)
        if not b:
            continue
        comunes = len(a & b)
        p = comunes / min(len(a), len(b))
        if comunes >= 2 and p > mejor_p:
            mejor, mejor_p = c, p
    return mejor if mejor_p >= 0.6 else None


def _igual(a, b):
    return normalizar(a) == normalizar(b)


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
        nom = emparejar(fila.nombre, por_nombre.keys())
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
        for campo, nuevo, actual in (("DX", p.dx, fila.dx),
                                     ("EVOLUCIÓN", p.evolucion, fila.evolucion),
                                     ("TRATAMIENTO", p.tratamiento, fila.tratamiento)):
            if nuevo and not _igual(nuevo, actual):
                acciones.append(Accion("ACTUALIZAR", fila.nombre, campo, actual, nuevo, fila,
                                       f"{fila.servicio}", servicio=fila.servicio, habitacion=fila.habitacion, sis=p))
    for nom, p in por_nombre.items():
        if nom not in usados:
            acciones.append(Accion("AGREGAR", p.nombre, "", "", _resumen(p.nombre, p.habitacion, p.dx, p.fecha, p.medico),
                                   None, f"En el sistema ({p.modo}, {p.habitacion}) y no en el kardex",
                                   marcada=False, servicio=p.modo, habitacion=p.habitacion, sis=p))
    return acciones
