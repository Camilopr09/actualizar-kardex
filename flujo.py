"""Orquesta las tareas que lanza la interfaz (se ejecutan en un hilo aparte)."""
import json
import os
import time
from pathlib import Path

import kardex_doc
import navegador
from comparar import comparar, emparejar
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
                if (not sistema.pagina_pide_login(pg)
                        and pg.locator(f"#{sistema.GRID_PEND}, #{sistema.GRID_ATEN}").count() > 0):
                    hospital = True
            elif (host in ("docs.google.com", "drive.google.com")
                  or host.endswith((".docs.google.com", ".drive.google.com"))):
                google = True
        except Exception:  # noqa: BLE001  (la página se cerró o navegó durante la revisión)
            continue
    return {"hospital": hospital, "google": google}


def iniciar_sesion(cfg, log, pasos=lambda estado: None, terminar=lambda: False):
    """Abre el navegador para que la persona inicie sesión. Termina cuando detecta que entró a
    Hospital Office y a Google (3 revisiones seguidas), cuando terminar() es True o cuando cierra el navegador.
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
        log("Inicia sesión en Hospital Office (pestaña 1) y en Google (pestaña 2). "
            "Se guarda sola cuando detecte que entraste a los dos.")
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
                faltan = [n for n, k in (("Hospital Office", "hospital"), ("Google", "google")) if not ultimo[k]]
                if faltan:
                    log("Guardo la sesión, pero no detecté que entraras a " + " ni a ".join(faltan) + ".")
                else:
                    log("Guardo la sesión…")
                break
            estado = _revisar_sesion(ctx, host_agenda)
            if estado != ultimo:
                ultimo = estado
                pasos(dict(estado))
            seguidas = seguidas + 1 if (estado["hospital"] and estado["google"]) else 0
            if seguidas >= 3:
                log("Detecté que ya entraste a Hospital Office y a Google. Guardo la sesión…")
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
            kardex = kardex_doc.parsear_kardex_html(kardex_doc.descargar_html(ctx, cfg["url_kardex"]))
            if not kardex:
                raise ErrorApp("kardex", "El documento no trae ninguna tabla con encabezado DATOS. "
                                         "Revisa que el enlace sea el del KARDEX.")
            log(f"Kardex: {len(kardex)} pacientes")
            s = sistema.Sistema(ctx, cfg, log, carpeta_datos() / "diagnostico")
            log("Leyendo la Agenda de Hospital Office…")
            pacientes = s.listar()
            log(f"Sistema: {len(pacientes)} pacientes")
            por_nombre = {p.nombre: p for p in pacientes}
            filas = {}
            for f in kardex:
                nom = emparejar(f.nombre, por_nombre.keys())
                if nom:
                    filas[nom] = f
            for i, (nom, f) in enumerate(filas.items(), 1):
                if cancelado():
                    raise Cancelado()
                progreso(i, len(filas), nom)
                log(f"({i}/{len(filas)}) {nom}")
                p = por_nombre[nom]
                p.tratamiento = f.tratamiento      # base para «IGUAL MANEJO»
                s.detalle(p)
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    return pacientes, kardex, comparar(pacientes, kardex)


def aplicar(cfg, acciones, log):
    """Escribe en el Google Doc. Devuelve (escritas, omitidas) como en kardex_doc.aplicar."""
    servicio = kardex_doc.servicio_docs(carpeta_datos(), _preferido(cfg))
    escritas, omitidas = kardex_doc.aplicar(servicio, cfg["url_kardex"], acciones)
    log(f"Escritas {len(escritas)} celdas.")
    for a, motivo in omitidas:
        log(f"Omitida: {a.paciente} ({a.campo}): {motivo}")
    return escritas, omitidas
