"""Modo --demo: pacientes ficticios, sin navegador ni red (para probar la interfaz).
Todos los nombres y datos son inventados."""
import time

from comparar import (Accion, FilaKardex, PacienteEntrega, PacienteSistema, TablaKardex, buscar_paciente,
                      candidatos_cirugia, comparar)
from errores import Cancelado
from notas import EstudioImagen

PAUSA_SESION = 3.0     # segundos que «dura» iniciar sesión
PAUSA_HOSPITAL = 1.0   # a los cuántos segundos «entra» a Hospital Office
PAUSA_GOOGLE = 2.0
PAUSA_PACIENTE = 0.2   # segundos por paciente al analizar
PAUSA_ESCRIBIR = 0.8

# Una tabla por servicio, como en el kardex real: (servicio, rango de habitaciones del título, base de las habitaciones).
# Base entera = habitaciones de piso («PISO 6» -> 601, 602…); texto = prefijo de las de Urgencias / UCI.
_SERVICIOS = [("URGENCIAS 47", None, "CUB"), ("URGENCIAS 82", None, "CUB"), ("UCI 1", None, "UCI1"),
              ("PISO 3", None, 300), ("PISO 4A", (422, 430), 421), ("PISO 4B", (430, None), 430),
              ("PISO 4C", (401, 421), 400), ("PISO 5", None, 500), ("UCI 5", None, "UCI5"), ("PISO 6", None, 600),
              ("UCI 7", None, "UCI7"), ("PISO 10", None, 1000), ("PISO 11", None, 1100)]
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
_DX = ["COLECISTITIS AGUDA", "APENDICITIS AGUDA COMPLICADA", "NEUMONIA ADQUIRIDA EN LA COMUNIDAD",
       "INSUFICIENCIA CARDIACA DESCOMPENSADA", "PIELONEFRITIS AGUDA", "OBSTRUCCION INTESTINAL",
       "CETOACIDOSIS DIABETICA", "HERNIA INGUINAL ENCARCELADA", "CELULITIS DE MIEMBRO INFERIOR",
       "HEMORRAGIA DE VIAS DIGESTIVAS ALTAS", "EPOC EXACERBADO", "COLANGITIS AGUDA"]
_TRAT = ["DIETA LIQUIDA\nCEFAZOLINA 1 G IV C/8H\nOMEPRAZOL 40 MG IV C/24H",
         "NVO\nCEFTRIAXONA 2 G IV C/24H\nSSN 0.9% A 80 CC/H",
         "DIETA BLANDA\nENOXAPARINA 40 MG SC C/24H\nACETAMINOFEN 1 G VO C/8H"]
_RETIRAR = {5, 21}                     # solo en el kardex (alta)
_AVISO = {8: "La hoja más reciente no es de un especialista de la lista (AUXILIAR TURNO NOCHE).",
          25: "No encontré hoja de evolución."}
_CAMBIOS = {1: ("DX",), 3: ("EVOLUCIÓN", "TRATAMIENTO"), 4: ("EVOLUCIÓN",), 7: ("DX", "EVOLUCIÓN"),
            10: ("TRATAMIENTO",), 14: ("EVOLUCIÓN",), 19: ("EVOLUCIÓN", "TRATAMIENTO"), 23: ("DX",),
            27: ("EVOLUCIÓN",)}
# habitación que dice el sistema cuando no coincide con la del kardex
_HAB_DISTINTA = {15: "UCI1-09"}        # sin código de piso: solo se avisa (REVISAR)
_HAB_PISO = {16: "3PISO-306"}          # el mismo piso, otra habitación: ACTUALIZAR «HABITACIÓN»
_MOVER = {9: "5PISO-512", 17: "4PISO-405"}      # otro piso: MOVER (PISO 6 -> PISO 5, PISO 4A -> PISO 4C por el rango)

_ECO_ABDOMEN = EstudioImagen(
    "19/10/26", "ECOGRAFÍA", "ABDOMEN TOTAL",
    "Hígado de tamaño y ecogenicidad normales. Vesícula biliar distendida, con paredes engrosadas (5 mm) y litiasis "
    "en su interior.\nVía biliar intrahepática sin dilatación. Páncreas y bazo sin alteraciones.\n"
    "OPINIÓN: Hallazgos compatibles con colecistitis aguda litiásica.", "1021")
_TAC_ABDOMEN = EstudioImagen(
    "16/10/26", "TOMOGRAFÍA", "ABDOMEN SIMPLE",
    "CONCLUSIÓN: -Hallazgos compatibles con proceso inflamatorio apendicular sin colecciones.", "1010")
_ECO_YA_ESTA = EstudioImagen(
    "17/10/26", "ECOGRAFÍA", "ABDOMEN TOTAL",
    "Líquido libre escaso en la pelvis. Asas intestinales sin signos de obstrucción.", "1015")
_RX_TORAX = EstudioImagen(
    "18/10/26", "RADIOGRAFÍA", "TÓRAX PA Y LATERAL",
    "Infiltrado alveolar en la base derecha. Silueta cardiaca de tamaño normal. Sin derrame pleural.", "1018")
_IMAGENES_SISTEMA = {0: [_ECO_ABDOMEN, _TAC_ABDOMEN], 2: [_ECO_YA_ESTA], 11: [_RX_TORAX]}
_IMAGENES_KARDEX = {          # celda «IMÁGENES / NOTAS» de esas filas del kardex
    0: "IMÁGENES\nTAC DE ABDOMEN SIMPLE 16/10/26\nCONCLUSIÓN: -Hallazgos compatibles con proceso inflamatorio "
       "apendicular sin colecciones.\n\nCX GENERAL 16/10/26 PENDIENTE DE CIRUGIA",
    2: "ECOGRAFIA DE ABDOMEN TOTAL 17/10/26\nLíquido libre escaso en la pelvis. Asas intestinales sin signos de "
       "obstrucción."}

# Pacientes que las entregas mandan a cirugía general y que NO están en el kardex:
# (nombre, documento, edad, habitación en la entrega, documento de entregas, habitación en el sistema, modo, DX, imágenes)
_NUEVOS = [
    ("IBAÑEZ ROMERO JUAN CAMILO", "1015000111", "47 AÑOS", "611", "PISO 6", "6PISO-611", "Hospitalización",
     "PANCREATITIS AGUDA BILIAR", [EstudioImagen("18/10/26", "ECOGRAFÍA", "VÍAS BILIARES Y PÁNCREAS",
                                                  "Colédoco de 9 mm. Páncreas aumentado de tamaño, con borde mal definido.\n"
                                                  "OPINIÓN: Pancreatitis aguda de probable origen biliar.", "1017")]),
    ("QUINTERO PAEZ MARIA EUGENIA", "52888777", "63 AÑOS", "CUB 9", "URGENCIAS CARRERA 47", "HOS47-09", "Urgencias",
     "DOLOR ABDOMINAL A ESTUDIO", []),                       # la habitación no dice el piso: destino por el documento
    ("BELTRAN SANCHEZ OMAR JULIAN", "80123456", "58 AÑOS", "PASILLO", "PISOS 10 Y 11", "PASILLO", "Hospitalización",
     "HERNIA INCISIONAL ENCARCELADA", []),                   # no se sabe en qué tabla va: AGREGAR a mano
]
_ENTREGAS_EXTRA = [   # filas de las entregas de pacientes sin cirugía general (no se buscan en el sistema)
    ("RAMIREZ ORTEGA SOFIA", "41222333", "71 AÑOS", "512", "PISO 5", "VAL X CX PLASTICA"),
    ("DIAZ PORRAS LEONARDO", "79555444", "35 AÑOS", "CUB 4", "URGENCIAS CALLE 82", "PENDIENTE RX DE TORAX"),
]


def _habitaciones(servicio, base, n):
    """(habitación como se escribe en el kardex, como la devuelve el sistema) de la n-ésima cama de un servicio."""
    if isinstance(base, int):
        cod = base + n
        return str(cod), f"{cod // 100}PISO-{cod}"
    if base == "CUB":
        return f"CUB {n}", f"HOS{servicio[-2:]}-{n:02d}"
    return str(n), f"{base}-{n:02d}"


def _evolucion(dia, medico, texto):
    return f"{dia} - DR. {medico}\n{texto}"


def _datos():
    """(sistema, kardex, tablas, entradas, nuevos) ficticios con todos los tipos de acción."""
    tablas = [TablaKardex(i, serv, serv, r, 0) for i, (serv, r, _) in enumerate(_SERVICIOS)]
    kardex, sistema, entradas = [], [], []
    por_serv = {}
    for i, nombre in enumerate(_NOMBRES):
        t = i % len(_SERVICIOS)
        serv, _, base = _SERVICIOS[t]
        n = por_serv[serv] = por_serv.get(serv, 0) + 1
        hab_k, hab_s = _habitaciones(serv, base, n)
        doc, edad = str(1010000000 + i * 12347), f"{40 + (i * 7) % 45} AÑOS"
        dx = _DX[i % len(_DX)]
        evol = f"18/10/2026 DAZA: PACIENTE ESTABLE, TOLERA VIA ORAL, SIN FIEBRE. CONTINUA {dx}."
        trat = _TRAT[i % len(_TRAT)]
        tablas[t].filas_pacientes += 1
        sin_trat = serv == "UCI 1"                    # esa tabla no tiene columna TRATAMIENTO
        kardex.append(FilaKardex(tabla=t, fila=n + 1, servicio=serv, datos=f"{hab_k}\n{nombre}\n{edad}\nCC {doc}",
                                 dx=dx, evolucion=evol, tratamiento="" if sin_trat else trat,
                                 col_tratamiento=None if sin_trat else 3, imagenes=_IMAGENES_KARDEX.get(i, ""),
                                 col_imagenes=5))
        if i in (9, 3):                               # aparecen también en las entregas de su piso
            entradas.append(PacienteEntrega(nombre, doc, "CC", edad, hab_k, f"{hab_k}\n{nombre}\n{edad}\nCC {doc}",
                                            "VAL X CX GENERAL" if i == 9 else "PENDIENTE ECOGRAFIA", serv, serv))
        if i in _RETIRAR:
            continue
        p = PacienteSistema(nombre, _MOVER.get(i) or _HAB_PISO.get(i) or _HAB_DISTINTA.get(i, hab_s),
                            "Urgencias" if serv.startswith("URGENCIAS") else "Hospitalización",
                            "FABIAN" if i % 2 else "EMILIANI", "19/10/2026 06:40", dx, evol, trat,
                            encontrado_detalle=True, aviso=_AVISO.get(i, ""), documento=doc, tipo_documento="CC",
                            edad=edad, imagenes=list(_IMAGENES_SISTEMA.get(i, [])))
        for campo in _CAMBIOS.get(i, ()):
            if campo == "DX":
                p.dx = dx + "\nDESNUTRICION PROTEICO CALORICA"
            elif campo == "EVOLUCIÓN":
                p.evolucion = f"19/10/2026 FABIAN: MEJORIA CLINICA, AFEBRIL, PLAN DE EGRESO PROXIMO. {dx}."
            else:
                p.tratamiento = trat + "\nLACTULOSA 15 CC VO C/12H"
        sistema.append(p)
    for t in tablas:        # título como en el kardex real: «PISO 4A ( 2 PACIENTES) 422 - 430»
        r = t.rango
        t.titulo = f"{t.servicio} ( {t.filas_pacientes} PACIENTES)" + (
            "" if not r else f" {r[0]} - {r[1]}" if r[1] else f" {r[0]} EN ADELANTE")
    nuevos = []
    for nombre, doc, edad, hab_e, doc_entregas, hab_s, modo, dx, imagenes in _NUEVOS:
        e = PacienteEntrega(nombre, doc, "CC", edad, hab_e, f"{hab_e}\n{nombre}\n{edad}\nCC {doc}",
                            f"{hab_e}\n{nombre}\n{edad}\nCC {doc}\n{dx}\nVALORACION POR CIRUGIA GENERAL",
                            doc_entregas, doc_entregas)
        p = PacienteSistema(nombre, hab_s, modo, "FABIAN", "19/10/2026 06:55", dx,
                            _evolucion("19/10/2026", "FABIAN (CIRUGIA GENERAL)", f"PACIENTE CON {dx}, EN MANEJO MEDICO."),
                            "PLAN\nDIETA CERO\nSSN 0.9% A 100 CC/H\nCEFAZOLINA 1 G IV C/8H", encontrado_detalle=True,
                            documento=doc, tipo_documento="CC", edad=edad, imagenes=list(imagenes))
        entradas.append(e)
        sistema.append(p)
        nuevos.append((p, e))
    for nombre, doc, edad, hab_e, doc_entregas, texto in _ENTREGAS_EXTRA:
        entradas.append(PacienteEntrega(nombre, doc, "CC", edad, hab_e, f"{hab_e}\n{nombre}\n{edad}\nCC {doc}",
                                        texto, doc_entregas, doc_entregas))
    return sistema, kardex, tablas, entradas, nuevos


class Demo:
    """Respaldo con la misma interfaz que flujo, pero con datos inventados."""
    es_demo = True

    def __init__(self):
        self._sesion = False
        self._hospital = None        # en demostración solo vive en memoria

    def hospital_usuario(self):
        return self._hospital[0] if self._hospital else ""

    def hospital_guardar(self, usuario, clave):
        self._hospital = (usuario, clave)

    def hospital_quitar(self):
        self._hospital = None

    def sesion_guardada(self, cfg):
        return self._sesion

    def credenciales_ok(self):
        return True

    def iniciar_sesion(self, nav, cfg, log, pasos=lambda estado: None, terminar=lambda: False):
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

    def analizar(self, nav, cfg, log, progreso, cancelado):
        log("Leyendo el kardex…")
        sistema, kardex, tablas, entradas, nuevos = _datos()
        log(f"Kardex: {len(kardex)} pacientes")
        log("Leyendo 11 documentos de entregas…")
        log("  No pude leer las entregas UCI 7: respuesta 403 (demostración)")
        candidatos = candidatos_cirugia(entradas)
        pendientes = [e for e in candidatos if not buscar_paciente(e.nombre, e.documento, kardex)]
        log(f"Entregas: {len(candidatos)} pacientes con valoración por cirugía general, "
            f"{len(pendientes)} que no están en el kardex")
        log("Leyendo la Agenda de Hospital Office…")
        # como en el análisis real: se recorre cada paciente del kardex y luego los de las entregas que no están en él
        total = len(kardex) + len(pendientes)
        for i, (nombre, documento) in enumerate([(x.nombre, x.documento) for x in kardex + pendientes], 1):
            if cancelado():
                raise Cancelado()
            progreso(i, total, nombre)
            log(f"({i}/{total}) {nombre}")
            if not buscar_paciente(nombre, documento, sistema):
                log("  no aparece en el sistema")
            time.sleep(PAUSA_PACIENTE)
        log(f"Sistema: {len(sistema)} pacientes")
        acciones = comparar(sistema, kardex, nuevos=nuevos, tablas=tablas, entregas=entradas)
        acciones.append(Accion("REVISAR", "UCI 7", detalle="No pude leer el documento de entregas UCI 7: "
                                                          "respuesta 403 (demostración)", marcada=False))
        return sistema, kardex, acciones

    def aplicar(self, cfg, acciones, log):
        log("Escribiendo en el kardex (demostración)…")
        time.sleep(PAUSA_ESCRIBIR)
        escritas = [a for a in acciones if a.automatica]
        omitidas = [(a, "No es una acción que se escriba sola") for a in acciones if not a.automatica]
        actualizar = [x for x in escritas if x.tipo == "ACTUALIZAR"]
        if len(escritas) >= 2 and actualizar:      # una se «omite» para mostrar cómo se ve: la última ACTUALIZAR
            escritas.remove(actualizar[-1])
            omitidas.append((actualizar[-1], "La fila cambió (ahora dice «OTRO PACIENTE»); revísala a mano."))
        log(f"Escritos {len(escritas)} cambios en el kardex.")
        for a, motivo in omitidas:
            log(f"Omitida: {a.paciente} ({a.campo or a.tipo}): {motivo}")
        return escritas, omitidas
