"""Orquesta las tareas que lanza la interfaz (se ejecutan en un hilo aparte)."""
import json
import os
import time
from pathlib import Path

import kardex_doc
import navegador
import secreto
from comparar import Accion, buscar_paciente, comparar, modo_preferido, MODOS_AGENDA
from errores import Cancelado, ErrorApp

NOMBRE = "Actualizar Kardex"
CONFIG_BASE = {
    "url_kardex": "https://docs.google.com/document/d/1Zd2RCwl-KifgPpmm8DiGRJKSxzjDYFlo74NifzHWFA0/edit",
    "url_agenda": "https://appclinicareinacatalina.com.co:8090/ehc2013/historiasclinicas/Agenda.aspx",
    "especialistas": ["DAZA", "FABIAN", "EMILIANI"],
    "navegador": "chrome",
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
    cfg = dict(CONFIG_BASE)
    if f.exists():
        try:
            cfg.update(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            pass
    if cfg.get("navegador") not in navegador.NOMBRES:
        cfg["navegador"] = "chrome"
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


def iniciar_sesion(cfg, log, pasos=lambda estado: None, terminar=lambda: False):
    """Abre el navegador para que la persona inicie sesión. Termina cuando detecta que entró a
    Google (3 revisiones seguidas), cuando terminar() es True o cuando cierra el navegador.
    Hospital Office se informa, pero no es requisito: su sesión no persiste (la app entra en cada análisis).
    pasos({"hospital": bool, "google": bool}) se llama cada vez que cambia."""
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse
    import sistema
    host_agenda = (urlparse(cfg["url_agenda"]).hostname or "").lower()
    with sync_playwright() as pw:
        ctx = sistema.abrir_contexto(pw, carpeta_datos(), _preferido(cfg), log)
        p1 = ctx.pages[0] if ctx.pages else ctx.new_page()
        p1.goto(cfg["url_agenda"])
        ctx.new_page().goto(cfg["url_kardex"])
        log("Entra a Google con la cuenta del kardex (pestaña 2). Se guarda sola cuando detecte que entraste. "
            "Hospital Office (pestaña 1) no guarda la sesión: no hace falta entrar ahí.")
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
                log("Sesiones guardadas.")
                return
            if terminar():
                if not ultimo["google"]:
                    log("Guardo la sesión, pero no detecté que entraras a Google.")
                else:
                    log("Guardo la sesión…")
                break
            estado = _revisar_sesion(ctx, host_agenda)
            if estado != ultimo:
                ultimo = estado
                pasos(dict(estado))
            seguidas = seguidas + 1 if estado["google"] else 0
            if seguidas >= 3:
                log("Detecté que ya entraste a Google. Guardo la sesión…")
                break
            time.sleep(1)
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    log("Sesiones guardadas.")


def analizar(cfg, log, progreso, cancelado):
    """Devuelve (pacientes_sistema, filas_kardex, acciones).
    progreso(i, n, nombre); cancelado() -> bool se revisa antes de cada paciente."""
    from playwright.sync_api import sync_playwright
    import sistema
    with sync_playwright() as pw:
        ctx = sistema.abrir_contexto(pw, carpeta_datos(), _preferido(cfg), log)
        try:
            log("Leyendo el kardex…")
            html = kardex_doc.descargar_html(ctx, cfg["url_kardex"])
            kardex = kardex_doc.parsear_kardex_html(html)
            if not kardex:
                n, primera = kardex_doc.describir_tablas(html)
                raise ErrorApp("kardex", "El documento no trae ninguna tabla con encabezado DATOS "
                                         f"(tablas encontradas: {n}; primera celda de la primera tabla: «{primera}»). "
                                         "Revisa que el enlace sea el del KARDEX y la pestaña correcta.")
            log(f"Kardex: {len(kardex)} pacientes")
            s = sistema.Sistema(ctx, cfg, log, carpeta_datos() / "diagnostico",
                                credenciales=hospital_credenciales(), progreso=progreso, cancelado=cancelado)
            log("Leyendo la Agenda de Hospital Office…")
            s.ir_agenda()                       # aquí falla (sesión / agenda) si no se puede entrar
            pacientes, fallidos = [], []
            n = len(kardex)
            for i, f in enumerate(kardex, 1):
                if cancelado():
                    raise Cancelado()
                progreso(i, n, f.nombre)
                log(f"({i}/{n}) {f.nombre}")
                try:
                    pref = modo_preferido(f.servicio)
                    modos = [pref] + [m for m in MODOS_AGENDA if m != pref]
                    p = s.buscar(f.nombre, f.documento, f.tipo_documento, modos)
                    if not p:
                        log("  no aparece en el sistema")
                        continue
                    if any((p.documento and x.documento == p.documento) or x.nombre == p.nombre for x in pacientes):
                        continue                       # dos filas del kardex para la misma persona
                    p.tratamiento = f.tratamiento      # base para «IGUAL MANEJO»
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
                    fallidos.append((f, str(e).splitlines()[0] if str(e) else e.__class__.__name__))
                    s.diagnostico("buscar")
            # AGREGAR: solo desde la lista de atendidos (si existe). La grilla «Pacientes Por Atender» es de TODO
            # el hospital: nunca se usa para proponer pacientes nuevos.
            try:
                atendidos = s.leer_atendidos()
            except ErrorApp as e:
                if e.codigo == "sesion":
                    raise
                atendidos = []
            except Cancelado:
                raise
            except Exception:  # noqa: BLE001
                atendidos = []
            if not atendidos:
                log("No hay lista de pacientes atendidos: no se proponen pacientes nuevos")
            for a in atendidos:
                if any(buscar_paciente(f.nombre, f.documento, [a]) for f in kardex):
                    continue
                if not any(x.documento and x.documento == a.documento or x.nombre == a.nombre for x in pacientes):
                    pacientes.append(a)
            log(f"Sistema: {len(pacientes)} pacientes")
        except ErrorApp as e:
            if e.codigo == "sesion" and e.mensaje.startswith(sistema.Sistema.MSG_LOGIN_MALO):
                # no reintentar con una clave mala en cada análisis: podría bloquear la cuenta
                hospital_quitar()
                raise ErrorApp("sesion", e.mensaje + ". Borré el usuario guardado para no bloquear tu cuenta: "
                                         "vuelve a guardarlo en Ajustes.") from e
            raise
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    perdidos = {id(f) for f, _ in fallidos}
    acciones = comparar(pacientes, [f for f in kardex if id(f) not in perdidos])
    for f, motivo in fallidos:          # no se pudo buscar: no es lo mismo que «no aparece»
        acciones.append(Accion("REVISAR", f.nombre, detalle=f"No pude buscarlo en el sistema: {motivo}", fila=f,
                               marcada=False, servicio=f.servicio, habitacion=f.habitacion))
    return pacientes, kardex, acciones


def aplicar(cfg, acciones, log):
    """Escribe en el Google Doc. Devuelve (escritas, omitidas) como en kardex_doc.aplicar."""
    servicio = kardex_doc.servicio_docs(carpeta_datos(), _preferido(cfg))
    escritas, omitidas = kardex_doc.aplicar(servicio, cfg["url_kardex"], acciones)
    log(f"Escritas {len(escritas)} celdas.")
    for a, motivo in omitidas:
        log(f"Omitida: {a.paciente} ({a.campo}): {motivo}")
    return escritas, omitidas
