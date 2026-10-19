"""Modo --demo: pacientes ficticios, sin navegador ni red (para probar la interfaz).
Todos los nombres y datos son inventados."""
import time

from comparar import FilaKardex, PacienteSistema, comparar, emparejar
from errores import Cancelado

PAUSA_SESION = 3.0     # segundos que «dura» iniciar sesión
PAUSA_HOSPITAL = 1.0   # a los cuántos segundos «entra» a Hospital Office
PAUSA_GOOGLE = 2.0
PAUSA_PACIENTE = 0.2   # segundos por paciente al analizar
PAUSA_ESCRIBIR = 0.8

_SERVICIOS = [("URGENCIAS", "U-"), ("PISO 2", "2-"), ("PISO 3", "3-"), ("PISO 4", "4-"), ("PISO 5", "5-"),
              ("PISO 6", "6-"), ("PISO 7", "7-"), ("UCI 5", "UCI5-"), ("UCI 7", "UCI7-"), ("CORONARIOS", "C-"),
              ("CIRUGÍA", "Q-"), ("OBSERVACIÓN", "O-"), ("AISLAMIENTO", "A-")]
_NOMBRES = [
    "CARDENAS IBARRA JORGE ENRIQUE", "MORA QUINTERO ESPERANZA", "VARGAS LOZANO MARTHA CECILIA",
    "RUEDA PINZON HECTOR FABIO", "SALAZAR OSPINA LUZ MARINA", "TORRES BELTRAN CARLOS ARTURO",
    "GUERRERO LEAL ANA ISABEL", "NIETO CASTRO RAFAEL ANTONIO", "PARRA MEJIA BLANCA INES",
    "ACOSTA RIVERA LUIS ALBERTO", "DUARTE SOLANO MARIA ELENA", "FONSECA PRADA JAIRO ENRIQUE",
    "CORTES AGUDELO ROSA MARIA", "LEON VELANDIA PEDRO NEL", "MONTOYA RIOS GLORIA PATRICIA",
    "QUIROGA BARON ALVARO JOSE", "ROJAS TELLEZ CLARA INES", "SIERRA CANO WILSON ANDRES",
    "BERMUDEZ HOYOS LILIANA", "ORTIZ NARANJO SAMUEL DAVID", "PALACIOS DUQUE ROSALBA",
    "CAMACHO URIBE FERNANDO LUIS", "ESCOBAR MENDOZA YOLANDA", "RINCON SUAREZ DIEGO ARMANDO",
    "VILLAMIL ARIAS NELLY STELLA", "GALVIS PEÑA HERNAN DARIO", "TOVAR LASSO ADRIANA MARCELA",
    "MEDINA CORREA OSCAR IVAN", "BOHORQUEZ SANTOS TERESA DE JESUS",
]
_AGREGAR = [  # (nombre, habitación, modo, dx)
    ("IBAÑEZ ROMERO JUAN CAMILO", "6-11", "Hospitalización", "PANCREATITIS AGUDA BILIAR"),
    ("QUINTERO PAEZ MARIA EUGENIA", "UCI5-09", "Urgencias", "CHOQUE SEPTICO DE FOCO ABDOMINAL"),
]
_DX = ["COLECISTITIS AGUDA", "APENDICITIS AGUDA COMPLICADA", "NEUMONIA ADQUIRIDA EN LA COMUNIDAD",
       "INSUFICIENCIA CARDIACA DESCOMPENSADA", "PIELONEFRITIS AGUDA", "OBSTRUCCION INTESTINAL",
       "CETOACIDOSIS DIABETICA", "HERNIA INGUINAL ENCARCELADA", "CELULITIS DE MIEMBRO INFERIOR",
       "HEMORRAGIA DE VIAS DIGESTIVAS ALTAS", "EPOC EXACERBADO", "COLANGITIS AGUDA"]
_TRAT = ["DIETA LIQUIDA\nCEFAZOLINA 1 G IV C/8H\nOMEPRAZOL 40 MG IV C/24H",
         "NVO\nCEFTRIAXONA 2 G IV C/24H\nSSN 0.9% A 80 CC/H",
         "DIETA BLANDA\nENOXAPARINA 40 MG SC C/24H\nACETAMINOFEN 1 G VO C/8H"]
_RETIRAR = {5, 21}                     # solo en el kardex (alta)
_HAB_DISTINTA = {12: "UCI5-02", 17: "5-08"}
_AVISO = {8: "La hoja más reciente no es de un especialista de la lista (AUXILIAR TURNO NOCHE).",
          25: "No encontré hoja de evolución."}
_CAMBIOS = {1: ("DX",), 3: ("EVOLUCIÓN", "TRATAMIENTO"), 4: ("EVOLUCIÓN",), 7: ("DX", "EVOLUCIÓN"),
            10: ("TRATAMIENTO",), 14: ("EVOLUCIÓN",), 19: ("EVOLUCIÓN", "TRATAMIENTO"), 23: ("DX",),
            27: ("EVOLUCIÓN",)}


def _datos():
    """(sistema, kardex) ficticios con los cuatro tipos de acción."""
    kardex, sistema = [], []
    por_serv = {}
    for i, nombre in enumerate(_NOMBRES):
        serv, pre = _SERVICIOS[i % len(_SERVICIOS)]
        n = por_serv[serv] = por_serv.get(serv, 0) + 1
        hab = f"{pre}{n + (i % 3) * 4:02d}"
        dx = _DX[i % len(_DX)]
        evol = f"18/10/2026 DAZA: PACIENTE ESTABLE, TOLERA VIA ORAL, SIN FIEBRE. CONTINUA {dx}."
        trat = _TRAT[i % len(_TRAT)]
        kardex.append(FilaKardex(tabla=0, fila=i + 1, servicio=serv, datos=f"{nombre}\n{hab}",
                                 dx=dx, evolucion=evol, tratamiento=trat))
        if i in _RETIRAR:
            continue
        p = PacienteSistema(nombre, _HAB_DISTINTA.get(i, hab), "Urgencias" if serv == "URGENCIAS" else "Hospitalización",
                            "FABIAN" if i % 2 else "EMILIANI", "19/10/2026 06:40", dx, evol, trat,
                            encontrado_detalle=True, aviso=_AVISO.get(i, ""))
        for campo in _CAMBIOS.get(i, ()):
            if campo == "DX":
                p.dx = dx + "\nDESNUTRICION PROTEICO CALORICA"
            elif campo == "EVOLUCIÓN":
                p.evolucion = f"19/10/2026 FABIAN: MEJORIA CLINICA, AFEBRIL, PLAN DE EGRESO PROXIMO. {dx}."
            else:
                p.tratamiento = trat + "\nLACTULOSA 15 CC VO C/12H"
        sistema.append(p)
    for nombre, hab, modo, dx in _AGREGAR:
        sistema.append(PacienteSistema(nombre, hab, modo, "FABIAN", "19/10/2026 06:55", dx))
    return sistema, kardex


class Demo:
    """Respaldo con la misma interfaz que flujo, pero con datos inventados."""
    es_demo = True

    def __init__(self):
        self._sesion = False

    def sesion_guardada(self, cfg):
        return self._sesion

    def credenciales_ok(self):
        return True

    def iniciar_sesion(self, cfg, log, pasos=lambda estado: None, terminar=lambda: False):
        log("Modo demostración: simulo el inicio de sesión…")
        estado = {"hospital": False, "google": False}
        pasos(dict(estado))
        t0 = time.monotonic()
        while time.monotonic() - t0 < PAUSA_SESION and not terminar():
            for clave, cuando in (("hospital", PAUSA_HOSPITAL), ("google", PAUSA_GOOGLE)):
                if not estado[clave] and time.monotonic() - t0 >= cuando:
                    estado[clave] = True
                    pasos(dict(estado))
            time.sleep(0.05)
        if not terminar() and not all(estado.values()):
            pasos({"hospital": True, "google": True})
        self._sesion = True
        log("Sesiones guardadas.")

    def analizar(self, cfg, log, progreso, cancelado):
        log("Leyendo el kardex…")
        sistema, kardex = _datos()
        log(f"Kardex: {len(kardex)} pacientes")
        log("Leyendo la Agenda de Hospital Office…")
        log(f"Sistema: {len(sistema)} pacientes")
        por_nombre = {p.nombre: p for p in sistema}
        pares = []
        for f in kardex:
            nom = emparejar(f.nombre, por_nombre.keys())
            if nom:
                pares.append(nom)
        for i, nom in enumerate(pares, 1):
            if cancelado():
                raise Cancelado()
            progreso(i, len(pares), nom)
            log(f"({i}/{len(pares)}) {nom}")
            time.sleep(PAUSA_PACIENTE)
        return sistema, kardex, comparar(sistema, kardex)

    def aplicar(self, cfg, acciones, log):
        log("Escribiendo en el kardex (demostración)…")
        time.sleep(PAUSA_ESCRIBIR)
        acciones = list(acciones)
        omitidas = []
        if len(acciones) >= 2:
            a = acciones.pop()
            omitidas.append((a, "La fila cambió (ahora dice «OTRO PACIENTE»); revísala a mano."))
        log(f"Escritas {len(acciones)} celdas.")
        for a, motivo in omitidas:
            log(f"Omitida: {a.paciente} ({a.campo}): {motivo}")
        return acciones, omitidas
