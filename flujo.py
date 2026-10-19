"""Orquesta las tareas que lanza la interfaz (se ejecutan en un hilo aparte)."""
import json
import os
import time
from pathlib import Path

import kardex_doc
from comparar import comparar, emparejar

NOMBRE = "Actualizar Kardex"
CONFIG_BASE = {
    "url_kardex": "https://docs.google.com/document/d/1Zd2RCwl-KifgPpmm8DiGRJKSxzjDYFlo74NifzHWFA0/edit",
    "url_agenda": "https://appclinicareinacatalina.com.co:8090/ehc2013/historiasclinicas/Agenda.aspx",
    "especialistas": ["DAZA", "FABIAN", "EMILIANI"],
    "navegador": "chrome",
}


def carpeta_datos():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "ActualizarKardex"
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
    return cfg


def guardar_config(cfg):
    (carpeta_datos() / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def iniciar_sesion(cfg, log):
    """Abre el navegador para que la persona inicie sesión; termina cuando lo cierra."""
    from playwright.sync_api import sync_playwright
    import sistema
    with sync_playwright() as pw:
        ctx = sistema.abrir_contexto(pw, carpeta_datos() / "perfil", cfg.get("navegador", ""))
        p1 = ctx.pages[0] if ctx.pages else ctx.new_page()
        p1.goto(cfg["url_agenda"])
        ctx.new_page().goto(cfg["url_kardex"])
        log("Inicia sesión en Hospital Office (pestaña 1) y en Google (pestaña 2). Luego CIERRA el navegador.")
        while True:
            try:
                if not ctx.pages:
                    break
            except Exception:  # noqa: BLE001
                break
            time.sleep(1)
    log("Sesiones guardadas.")


def analizar(cfg, log, progreso):
    """Devuelve (pacientes_sistema, filas_kardex, acciones)."""
    from playwright.sync_api import sync_playwright
    import sistema
    with sync_playwright() as pw:
        ctx = sistema.abrir_contexto(pw, carpeta_datos() / "perfil", cfg.get("navegador", ""))
        try:
            log("Leyendo el KARDEX…")
            kardex = kardex_doc.parsear_kardex_html(kardex_doc.descargar_html(ctx, cfg["url_kardex"]))
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
                progreso(i, len(filas))
                log(f"({i}/{len(filas)}) {nom}")
                p = por_nombre[nom]
                p.tratamiento = f.tratamiento      # base para «IGUAL MANEJO»
                s.detalle(p)
        finally:
            ctx.close()
    return pacientes, kardex, comparar(pacientes, kardex)


def aplicar(cfg, acciones, log):
    servicio = kardex_doc.servicio_docs(carpeta_datos())
    escritas, omitidas = kardex_doc.aplicar(servicio, cfg["url_kardex"], acciones)
    log(f"Escritas {escritas} celdas.")
    for o in omitidas:
        log("Omitida: " + o)
    return escritas, omitidas
