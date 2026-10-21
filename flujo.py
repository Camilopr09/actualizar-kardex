"""Orquesta las tareas que lanza la interfaz (se ejecutan en un hilo aparte)."""
import copy
import json
import os
import time
import weakref
from pathlib import Path

import kardex_doc
import navegador
import secreto
from comparar import Accion, buscar_paciente, candidatos_cirugia, comparar, modo_preferido, MODOS_AGENDA
from errores import Cancelado, ErrorApp

NOMBRE = "Actualizar Kardex"
_DOC = "https://docs.google.com/document/d/"
CONFIG_BASE = {
    "url_kardex": _DOC + "1Zd2RCwl-KifgPpmm8DiGRJKSxzjDYFlo74NifzHWFA0/edit",
    "url_agenda": "https://appclinicareinacatalina.com.co:8090/ehc2013/historiasclinicas/Agenda.aspx",
    "especialistas": ["DAZA", "FABIAN", "EMILIANI"],
    "navegador": "chrome",
    # documentos «ENTREGAS CRC» (uno por servicio): SOLO se leen, nunca se escriben
    "entregas": [
        {"nombre": "PISO 3 GINECO", "url": _DOC + "1Tl8MZhfT3EXsr2iXXJX2ZEJDe8Krrx-yahen7HXRW_U/edit"},
        {"nombre": "PISO 4C (401-421)", "url": _DOC + "13qS3NFNW6rL4WdMyrRwemWiEBs1klmHRBG_NRnFuGxI/edit"},
        {"nombre": "PISO 4A (422-430)", "url": _DOC + "1aNLMA35809TyPxdpzrYSmGGC671TCCxcdpehxikjtEs/edit"},
        {"nombre": "PISO 4B (430 EN ADELANTE)", "url": _DOC + "1JLpYjbFaX0Ig1STPvXmwretUrr4hku91N4id6TnHTJA/edit"},
        {"nombre": "PISO 5", "url": _DOC + "1SrIrfFb7LGtlIFvTIVrtZqLzdn18C4a3Nc5L9gLCYxE/edit?tab=t.0"},
        {"nombre": "PISO 6", "url": _DOC + "1OkIz3Nk416MfJ-8RiZ5MbJ_6Zfdh1v5c2_j94R0LPik/edit"},
        {"nombre": "PISOS 10 Y 11", "url": _DOC + "1NnrOurx4ts6vThhqxMxonqRvfcwE8O6lf14UJADDaVM/edit?tab=t.0"},
        {"nombre": "URGENCIAS CARRERA 47", "url": _DOC + "1wpDe8-sfVb8JRqjNhLVuLDDRw2xqf2nkkmoLFLFkAvY/edit?tab=t.0"},
        {"nombre": "URGENCIAS CALLE 82", "url": _DOC + "1oZ6csCNXcoT-lAaGGRa7gujmBg9kUP4Y6BiFdpomF_8/edit"},
        {"nombre": "UCI 1", "url": _DOC + "1_uf1Ga_-Uzygws2GwLhmYpMhnZYcRmAbySa6bOel_uM/edit"},
        {"nombre": "UCI 7", "url": _DOC + "1DSL2Wy5TtSZi1D1TB_JQOno31sk_kVx_ocxcL-DLhHY/edit"},
    ],
}


def carpeta_datos():
    """Carpeta de datos de la app (KARDEX_DATOS la redirige, p. ej. en pruebas)."""
    forzada = os.environ.get("KARDEX_DATOS")
    base = Path(forzada) if forzada else (
        Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "ActualizarKardex")
    base.mkdir(parents=True, exist_ok=True)
    return base


def cargar_config():
    f = carpeta_datos() / "config.json"
    cfg = copy.deepcopy(CONFIG_BASE)
    if f.exists():
        try:
            cfg.update(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            pass
    if cfg.get("navegador") not in navegador.NOMBRES:
        cfg["navegador"] = "chrome"
    if not isinstance(cfg.get("entregas"), list):
        cfg["entregas"] = copy.deepcopy(CONFIG_BASE["entregas"])
    return cfg


def guardar_config(cfg):
    (carpeta_datos() / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _preferido(cfg):
    p = cfg.get("navegador", "chrome")
    return p if p in navegador.NOMBRES else "chrome"


def sesion_guardada(cfg):
    """Hay un perfil del navegador elegido con algo dentro (la persona ya inició sesión)."""
    nombre = navegador.elegir(_preferido(cfg))[0] or _preferido(cfg)
    perfil = carpeta_datos() / f"perfil-{nombre}"
    try:
        return perfil.is_dir() and any(perfil.iterdir())
    except OSError:
        return False


def hospital_credenciales():
    """{'usuario','clave'} guardados para Hospital Office, o None."""
    return secreto.leer_hospital(carpeta_datos())


def hospital_usuario():
    c = hospital_credenciales()
    return c["usuario"] if c else ""


def hospital_guardar(usuario, clave):
    secreto.guardar_hospital(carpeta_datos(), usuario, clave)


def hospital_quitar():
    secreto.quitar_hospital(carpeta_datos())


def credenciales_ok():
    return (carpeta_datos() / "credentials.json").exists()


def _revisar_sesion(ctx, host_agenda):
    """Mira todas las páginas abiertas. Devuelve {"hospital": bool, "google": bool}."""
    import sistema
    from urllib.parse import urlparse
    hospital = google = False
    try:
        paginas = list(ctx.pages)
    except Exception:  # noqa: BLE001
        return {"hospital": False, "google": False}
    for pg in paginas:
        try:
            url = pg.url
            host = (urlparse(url).hostname or "").lower()
            if host and host == host_agenda and not hospital:
                # solo cuenta si ya se ve la Agenda: una pantalla de login a medio cargar
                # no debe cerrar el navegador antes de tiempo
                if not sistema.pagina_pide_login(pg) and sistema.hay_grilla(pg):
                    hospital = True
            elif (host in ("docs.google.com", "drive.google.com")
                  or host.endswith((".docs.google.com", ".drive.google.com"))):
                google = True
        except Exception:  # noqa: BLE001  (la página se cerró o navegó durante la revisión)
            continue
    return {"hospital": hospital, "google": google}


_PESTANAS = weakref.WeakKeyDictionary()      # contexto -> {"hospital": página, "kardex": página}
_EN_BLANCO = ("about:blank", "chrome://newtab/", "chrome://new-tab-page/", "edge://newtab/")


def _abierta(pg):
    try:
        return not pg.is_closed()
    except Exception:  # noqa: BLE001
        return False


def _pestana(ctx, clave):
    """La pestaña dedicada (`clave`): la misma de siempre si sigue abierta; si no, una pestaña en blanco que
    ya exista; si no, una nueva."""
    reg = _PESTANAS.setdefault(ctx, {})
    pg = reg.get(clave)
    if pg is not None and _abierta(pg):
        return pg
    for otra in list(ctx.pages):
        if _abierta(otra) and otra.url in _EN_BLANCO and otra not in reg.values():
            reg[clave] = otra
            return otra
    reg[clave] = ctx.new_page()
    return reg[clave]


def _cerrar_pestanas_sobrantes(ctx, antes):
    """Cierra las pestañas que aparecieron durante el trabajo (ventanas emergentes) y no son las dedicadas."""
    propias = list(_PESTANAS.get(ctx, {}).values())
    try:
        paginas = list(ctx.pages)
    except Exception:  # noqa: BLE001
        return
    for pg in paginas:
        if pg not in antes and pg not in propias and _abierta(pg):
            try:
                pg.close()
            except Exception:  # noqa: BLE001
                pass


def iniciar_sesion(nav, cfg, log, pasos=lambda estado: None, terminar=lambda: False):
    """Abre (o reutiliza) la ventana de automatización para que la persona inicie sesión. Termina cuando detecta
    que entró a Google (3 revisiones seguidas), cuando terminar() es True o cuando cierra la ventana.
    NUNCA cierra el navegador: las pestañas quedan abiertas para no perder la sesión de Hospital Office.
    pasos({"hospital": bool, "google": bool}) se llama cada vez que cambia."""
    return nav.ejecutar(_iniciar_sesion, cfg, log, pasos, terminar)


def _iniciar_sesion(ctx, cfg, log, pasos, terminar):
    from urllib.parse import urlparse
    host_agenda = (urlparse(cfg["url_agenda"]).hostname or "").lower()
    p1 = _pestana(ctx, "hospital")
    p1.goto(cfg["url_agenda"])
    pk = _pestana(ctx, "kardex")
    pk.goto(cfg["url_kardex"])
    try:
        pk.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    log("Entra a Google con la cuenta del kardex (pestaña 2). Se guarda sola cuando detecte que entraste. "
        "La ventana queda abierta para no perder la sesión de Hospital Office; puedes minimizarla.")
    cerrado = []
    ctx.on("close", lambda *_: cerrado.append(1))
    ultimo, seguidas = {"hospital": False, "google": False}, 0
    pasos(dict(ultimo))
    while True:
        try:
            abiertas = [pg for pg in ctx.pages if not pg.is_closed()]
        except Exception:  # noqa: BLE001
            abiertas = []
        if cerrado or not abiertas:
            log("Cerraste la ventana: la app la abrirá de nuevo cuando haga falta.")
            return
        if terminar():
            if not ultimo["google"]:
                log("Termino, pero no detecté que entraras a Google.")
            else:
                log("Sesión de Google guardada.")
            break
        estado = _revisar_sesion(ctx, host_agenda)
        if estado != ultimo:
            ultimo = estado
            pasos(dict(estado))
        seguidas = seguidas + 1 if estado["google"] else 0
        if seguidas >= 3:
            log("Detecté que ya entraste a Google. Sesión guardada; la ventana queda abierta.")
            break
        time.sleep(1)


def analizar(nav, cfg, log, progreso, cancelado):
    """Devuelve (pacientes_sistema, filas_kardex, acciones).
    progreso(i, n, nombre); cancelado() -> bool se revisa antes de cada paciente.
    Usa el navegador vivo `nav` (NavegadorVivo) y no lo cierra, ni al terminar ni si falla."""
    return nav.ejecutar(_analizar, cfg, log, progreso, cancelado)


def _documentos_entregas(cfg):
    """Documentos de entregas configurados ([{nombre, url}]); ignora las entradas mal formadas."""
    docs = []
    for e in cfg.get("entregas") or []:
        if isinstance(e, dict) and isinstance(e.get("nombre"), str) and isinstance(e.get("url"), str) \
                and e["nombre"].strip() and e["url"].strip():
            docs.append({"nombre": e["nombre"].strip(), "url": e["url"].strip()})
    return docs


def _leer_entregas(ctx, cfg, log, cancelado):
    """Lee (SOLO lectura) cada documento de entregas con la sesión de Google del navegador.
    Devuelve (entradas: list[PacienteEntrega], fallidos: [(nombre del documento, motivo)]). Un documento que no se
    puede leer se anota y se sigue con los demás; un error de sesión de Google sí corta el análisis."""
    entradas, fallidos = [], []
    docs = _documentos_entregas(cfg)
    if docs:
        log(f"Leyendo {len(docs)} documentos de entregas…")
    for d in docs:
        if cancelado():
            raise Cancelado()
        try:
            filas = kardex_doc.parsear_entregas_html(kardex_doc.descargar_html(ctx, d["url"]), d["nombre"])
        except Cancelado:
            raise
        except ErrorApp as e:
            if e.codigo == "sesion":
                raise
            motivo = e.mensaje.split(". ")[0]       # sin la sugerencia «revisa el enlace del KARDEX»
        except Exception as e:  # noqa: BLE001
            motivo = _motivo(e)
        else:
            log(f"  Entregas {d['nombre']}: {len(filas)} pacientes")
            entradas += filas
            continue
        log(f"  No pude leer las entregas {d['nombre']}: {motivo}")
        fallidos.append((d["nombre"], motivo))
    return entradas, fallidos


def _buscar(s, nombre, documento, tipo, servicio, tratamiento, edad=""):
    """Busca un paciente en la Agenda (el modo del servicio primero, luego el otro). PacienteSistema todavía sin
    detalle (con la base de «IGUAL MANEJO» y la edad), o None si no aparece."""
    pref = modo_preferido(servicio)
    p = s.buscar(nombre, documento, tipo, [pref] + [m for m in MODOS_AGENDA if m != pref])
    if not p:
        return None
    p.tratamiento = tratamiento         # base para «IGUAL MANEJO» (vacía en los pacientes que no están en el kardex)
    if edad:
        p.edad = edad
    return p


def _mismo(p, pacientes):
    """Ya hay en `pacientes` una persona con el mismo documento o el mismo nombre."""
    return any((p.documento and x.documento == p.documento) or x.nombre == p.nombre for x in pacientes)


def _motivo(e):
    """Primer renglón del error (o su nombre si no trae texto)."""
    return str(e).splitlines()[0] if str(e) else e.__class__.__name__


def _analizar(ctx, cfg, log, progreso, cancelado):
    import sistema
    antes = list(ctx.pages)
    fallidos, fallidos_nuevos, nuevos, docs_fallidos = [], [], [], []
    try:
        log("Leyendo el kardex…")
        html = kardex_doc.descargar_html(ctx, cfg["url_kardex"])
        kardex = kardex_doc.parsear_kardex_html(html)
        if not kardex:
            n, primera = kardex_doc.describir_tablas(html)
            raise ErrorApp("kardex", "El documento no trae ninguna tabla con encabezado DATOS "
                                     f"(tablas encontradas: {n}; primera celda de la primera tabla: «{primera}»). "
                                     "Revisa que el enlace sea el del KARDEX y la pestaña correcta.")
        tablas = kardex_doc.tablas_kardex(html)
        log(f"Kardex: {len(kardex)} pacientes")
        # documentos de entregas: de ahí salen los pacientes con valoración por cirugía general que no están en el kardex
        entradas, docs_fallidos = _leer_entregas(ctx, cfg, log, cancelado)
        candidatos = candidatos_cirugia(entradas)
        # los que ya están en el kardex se actualizan con su fila; solo se buscan los demás
        nuevos_cand = [e for e in candidatos if not buscar_paciente(e.nombre, e.documento, kardex)]
        if entradas:
            log(f"Entregas: {len(candidatos)} pacientes con valoración por cirugía general, "
                f"{len(nuevos_cand)} que no están en el kardex")
        s = sistema.Sistema(ctx, cfg, log, carpeta_datos() / "diagnostico",
                            credenciales=hospital_credenciales(), progreso=progreso, cancelado=cancelado,
                            pagina=_pestana(ctx, "hospital"))
        log("Leyendo la Agenda de Hospital Office…")
        s.ir_agenda()                       # aquí falla (sesión / agenda) si no se puede entrar
        pacientes = []
        n = len(kardex) + len(nuevos_cand)
        for i, f in enumerate(kardex, 1):
            if cancelado():
                raise Cancelado()
            progreso(i, n, f.nombre)
            log(f"({i}/{n}) {f.nombre}")
            try:
                p = _buscar(s, f.nombre, f.documento, f.tipo_documento, f.servicio, f.tratamiento)
                if not p:
                    log("  no aparece en el sistema")
                    continue
                if _mismo(p, pacientes):
                    continue                       # dos filas del kardex para la misma persona
                s.detalle(p)
                pacientes.append(p)
            except Cancelado:
                raise
            except ErrorApp as e:
                if e.codigo == "sesion":
                    raise
                fallidos.append((f, e.mensaje))
                s.diagnostico("buscar")
            except Exception as e:  # noqa: BLE001
                fallidos.append((f, _motivo(e)))
                s.diagnostico("buscar")
        for i, e in enumerate(nuevos_cand, len(kardex) + 1):
            if cancelado():
                raise Cancelado()
            progreso(i, n, e.nombre)
            log(f"({i}/{n}) {e.nombre} (entregas {e.doc})")
            try:
                p = _buscar(s, e.nombre, e.documento, e.tipo_documento, e.doc, "", e.edad)
                if not p:
                    log("  no aparece en el sistema")
                    continue
                if _mismo(p, pacientes):
                    log("  ya está en el análisis con otra fila del kardex")
                    continue
                s.detalle(p)
                pacientes.append(p)
                nuevos.append((p, e))
            except Cancelado:
                raise
            except ErrorApp as err:
                if err.codigo == "sesion":
                    raise
                fallidos_nuevos.append((e, err.mensaje))
                s.diagnostico("buscar")
            except Exception as err:  # noqa: BLE001
                fallidos_nuevos.append((e, _motivo(err)))
                s.diagnostico("buscar")
        log(f"Sistema: {len(pacientes)} pacientes")
    except ErrorApp as e:
        if e.codigo == "sesion" and e.mensaje.startswith(sistema.Sistema.MSG_LOGIN_MALO):
            # no reintentar con una clave mala en cada análisis: podría bloquear la cuenta
            hospital_quitar()
            raise ErrorApp("sesion", e.mensaje + ". Borré el usuario guardado para no bloquear tu cuenta: "
                                     "vuelve a guardarlo en Ajustes.") from e
        raise
    finally:
        _cerrar_pestanas_sobrantes(ctx, antes)      # el navegador y la pestaña de Hospital Office quedan abiertos
    perdidos = {id(f) for f, _ in fallidos}
    acciones = comparar(pacientes, [f for f in kardex if id(f) not in perdidos], nuevos=nuevos, tablas=tablas,
                        entregas=entradas)
    for f, motivo in fallidos:          # no se pudo buscar: no es lo mismo que «no aparece»
        acciones.append(Accion("REVISAR", f.nombre, detalle=f"No pude buscarlo en el sistema: {motivo}", fila=f,
                               marcada=False, servicio=f.servicio, habitacion=f.habitacion))
    for e, motivo in fallidos_nuevos:   # está en las entregas con cirugía pero no pude revisarlo en el sistema
        acciones.append(Accion("REVISAR", e.nombre, detalle=f"Está en las entregas ({e.doc}) con valoración por "
                                                            f"cirugía y no pude buscarlo en el sistema: {motivo}",
                               marcada=False, servicio=e.servicio or e.doc, habitacion=e.habitacion))
    for nombre, motivo in docs_fallidos:
        acciones.append(Accion("REVISAR", nombre, detalle=f"No pude leer el documento de entregas {nombre}: {motivo}",
                               marcada=False))
    return pacientes, kardex, acciones


def aplicar(cfg, acciones, log):
    """Escribe en el Google Doc (ACTUALIZAR, AGREGAR y MOVER aprobados). Devuelve (escritas, omitidas) como en
    kardex_doc.aplicar. Los documentos de entregas nunca se escriben."""
    servicio = kardex_doc.servicio_docs(carpeta_datos(), _preferido(cfg))
    escritas, omitidas = kardex_doc.aplicar(servicio, cfg["url_kardex"], acciones)
    log(f"Escritos {len(escritas)} cambios en el kardex.")
    for a, motivo in omitidas:
        log(f"Omitida: {a.paciente} ({a.campo or a.tipo}): {motivo}")
    return escritas, omitidas
