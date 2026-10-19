"""Navegación en Hospital Office con Playwright (usa Chrome o Brave ya instalados)."""
import os
import re
import time
from datetime import datetime

import navegador
from comparar import PacienteSistema, emparejar
from errores import ErrorApp
from notas import (construir_tratamiento, interpretar_evolucion, interpretar_ordenes, normalizar)

GRID_PEND = "ctl00_cph1_cbpPanel1_grdPendientes"
GRID_ATEN = "ctl00_cph1_cbpPanel1_grdAtendidos"
GRID_FORM = "ctl00_cph1_ASPxRoundPanel2_grdFormatos"
MODOS = ("Urgencias", "Hospitalización")


def abrir_contexto(pw, carpeta, preferido, log):
    """Abre Chrome o Brave con un perfil propio que recuerda los inicios de sesión."""
    nombre, ruta = navegador.elegir(preferido)
    if not ruta:
        raise ErrorApp("navegador", "No encontré Chrome ni Brave. Instala uno de los dos.")
    if nombre != preferido:
        log(f"No encontré {preferido.capitalize()}; uso {nombre.capitalize()}.")
    args = ["--start-maximized", "--disable-blink-features=AutomationControlled",
            "--disable-background-mode"]
    sin_ventana = os.environ.get("KARDEX_HEADLESS") == "1"     # solo para pruebas automáticas
    if sin_ventana:
        args.append("--no-sandbox")
    try:
        return pw.chromium.launch_persistent_context(
            str(carpeta / f"perfil-{nombre}"), executable_path=ruta, headless=sin_ventana, no_viewport=True,
            ignore_default_args=["--enable-automation"],   # con estos flags Google no bloquea el inicio de sesión
            args=args)
    except Exception as e:  # noqa: BLE001
        raise ErrorApp("navegador", f"No pude abrir {nombre.capitalize()}: {_primera_linea(e)}") from e


def pagina_pide_login(page):
    """True si la página es un inicio de sesión (URL con «login» o campo de contraseña visible)."""
    if "login" in page.url.lower():
        return True
    try:
        return page.locator("input[type=password]").first.is_visible(timeout=500)
    except Exception:  # noqa: BLE001
        return False


def _primera_linea(e):
    """Primera línea del mensaje de una excepción (nunca falla aunque el mensaje esté vacío)."""
    return (str(e).splitlines() or [e.__class__.__name__])[0]


def _fecha(txt):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", txt or "")
    if not m:
        return datetime.min
    d, mo, y, h, mi = m.groups()
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0))


class Sistema:
    def __init__(self, contexto, cfg, log, carpeta_diag):
        self.ctx = contexto
        self.cfg = cfg
        self.log = log
        self.diag = carpeta_diag
        self.page = contexto.pages[0] if contexto.pages else contexto.new_page()
        self.page.set_default_timeout(20000)

    # ------------------------------------------------------------ utilidades
    def diagnostico(self, etiqueta):
        try:
            self.diag.mkdir(parents=True, exist_ok=True)
            base = self.diag / f"{datetime.now():%Y%m%d-%H%M%S}-{etiqueta}"
            base.with_suffix(".html").write_text(self.page.content(), encoding="utf-8")
            self.page.screenshot(path=str(base.with_suffix(".png")))
        except Exception:  # noqa: BLE001
            pass

    def _esperar_grid(self, grid):
        try:
            self.page.wait_for_function(
                "g => { const c = ASPxClientControl.GetControlCollection().elements[g];"
                " return !c || !c.InCallback(); }", arg=grid, timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        self.page.wait_for_timeout(400)

    def _filtrar(self, grid, columna, texto):
        self.page.evaluate(
            "([g,c,t]) => { const x = ASPxClientControl.GetControlCollection().elements[g];"
            " if (x) x.AutoFilterByColumn(c, t); }", [grid, columna, texto])
        self._esperar_grid(grid)

    def _filas(self, grid):
        return self.page.evaluate(
            """g => [...document.querySelectorAll(`[id^="${g}_DXDataRow"]`)].map(tr =>
                 [...tr.querySelectorAll('td')].map(td => td.innerText.trim()))""", grid)

    # ------------------------------------------------------------ agenda
    def _pide_login(self):
        """True si la página actual es un inicio de sesión."""
        return pagina_pide_login(self.page)

    def ir_agenda(self):
        self.page.goto(self.cfg["url_agenda"], wait_until="domcontentloaded")
        if self._pide_login():
            raise ErrorApp("sesion", "Hospital Office pide iniciar sesión.")
        try:
            self.page.wait_for_selector(f"#{GRID_PEND}, #{GRID_ATEN}", timeout=15000)
        except Exception:  # noqa: BLE001
            self.diagnostico("agenda")
            if self._pide_login():
                raise ErrorApp("sesion", "Hospital Office pide iniciar sesión.")
            raise ErrorApp("agenda", "No se ve la Agenda de Hospital Office.")

    def _modo(self, modo):
        try:
            self.page.get_by_text(re.compile(modo, re.I)).first.click(timeout=3000)
            self.page.wait_for_timeout(1200)
        except Exception:  # noqa: BLE001
            self.log(f"  (no pude cambiar a modo {modo}; se usa el que esté activo)")
        try:
            self.page.get_by_label(re.compile("ltimas 24", re.I)).uncheck(timeout=2000)
            self.page.wait_for_timeout(1200)
        except Exception:  # noqa: BLE001
            pass

    def listar(self):
        """Todos los pacientes visibles en la Agenda (pendientes + atendidos) por modo."""
        vistos = {}
        for modo in MODOS:
            self.ir_agenda()
            self._modo(modo)
            for grid in (GRID_PEND, GRID_ATEN):
                try:
                    filas = self._filas(grid)
                except Exception:  # noqa: BLE001
                    continue
                for f in filas:
                    if len(f) < 5 or not f[0].strip():
                        continue
                    nombre = re.sub(r"\s+", " ", f[0]).strip()
                    vistos.setdefault(nombre, PacienteSistema(nombre=nombre, habitacion=f[4].strip(), modo=modo))
            self.log(f"{modo}: {sum(1 for p in vistos.values() if p.modo == modo)} pacientes")
        if not vistos:
            self.diagnostico("listado-vacio")
        return list(vistos.values())

    # ------------------------------------------------------------ historia
    def _atender(self, p):
        self.ir_agenda()
        self._modo(p.modo)
        clave = p.nombre.split(" ")[0]
        for grid in (GRID_PEND, GRID_ATEN):
            self._filtrar(grid, "Paciente", clave)
            filas = self.page.locator(f'[id^="{grid}_DXDataRow"]')
            for i in range(filas.count()):
                fila = filas.nth(i)
                if normalizar(fila.locator("td").first.inner_text()) == normalizar(p.nombre):
                    enlace = fila.get_by_text("Atender", exact=True)
                    if enlace.count():
                        enlace.first.click()
                        self.page.wait_for_selector(f"#{GRID_FORM}", timeout=20000)
                        return True
        return False

    def _leer_textareas(self):
        return self.page.evaluate("[...document.querySelectorAll('textarea')].map(t=>t.value).join('\\n')")

    def _ultimo_formato(self, filtro, preferir_usuarios=()):
        """Filtra formatos, elige el más reciente (de especialistas si hay) y lo abre con 'Ver'."""
        self._filtrar(GRID_FORM, "Formato", filtro)
        filas = self.page.locator(f'[id^="{GRID_FORM}_DXDataRow"]')
        cand = []
        for i in range(filas.count()):
            celdas = filas.nth(i).locator("td").all_inner_texts()
            if len(celdas) >= 5:
                cand.append((i, _fecha(celdas[2]), celdas[2].strip(), celdas[4].strip()))
        if not cand:
            return None
        esp = [c for c in cand if any(normalizar(u) in normalizar(c[3]) for u in preferir_usuarios)]
        elegido = max(esp or cand, key=lambda c: c[1])
        antes = self._leer_textareas()
        fila = filas.nth(elegido[0])
        ver = fila.get_by_text("Ver", exact=True)
        (ver.first if ver.count() else fila.locator("td").last).click()   # clic real: por JS no carga
        for _ in range(40):
            self.page.wait_for_timeout(500)
            txt = self._leer_textareas()
            if txt and txt != antes:
                return {"texto": txt, "fecha": elegido[2], "usuario": elegido[3], "es_especialista": bool(esp)}
        return None

    def detalle(self, p):
        """Rellena dx/evolución/tratamiento de p. Devuelve p."""
        try:
            if not self._atender(p):
                p.aviso = "No pude abrir su historia desde la Agenda (no encontré «Atender»)."
                return p
            esp = self.cfg.get("especialistas", [])
            ev = self._ultimo_formato("HOJA DE EVOLUCION", esp)
            if not ev:
                p.aviso = "No encontré hoja de evolución."
                self.diagnostico("sin-evolucion-" + p.nombre.split()[0])
                return p
            if not ev["es_especialista"]:
                p.aviso = f"La hoja más reciente no es de un especialista de la lista ({ev['usuario']})."
            fecha = ev["fecha"].split(" ")[0]
            info = interpretar_evolucion(ev["texto"], fecha, ev["usuario"])
            p.fecha, p.medico = ev["fecha"], ev["usuario"]
            p.dx, p.evolucion = info["dx"], info["evolucion"]
            ordenes = []
            try:
                self.page.reload(wait_until="domcontentloaded")
                self.page.wait_for_selector(f"#{GRID_FORM}")
                od = self._ultimo_formato("ORDEN M")
                if od:
                    ordenes = interpretar_ordenes(od["texto"])
            except Exception:  # noqa: BLE001
                self.log(f"  {p.nombre}: no pude leer las órdenes médicas")
            p.tratamiento = construir_tratamiento(info["plan"], ordenes, p.tratamiento, ev["usuario"], fecha)
            p.encontrado_detalle = True
        except ErrorApp as e:
            if e.codigo == "sesion":      # sin sesión no se puede seguir con nadie
                raise
            p.aviso = f"No pude leer su historia: {e.mensaje}"
            self.diagnostico("error-" + p.nombre.split()[0])
        except Exception as e:  # noqa: BLE001
            p.aviso = f"Error leyendo la historia: {_primera_linea(e)}"
            self.diagnostico("error-" + p.nombre.split()[0])
        return p
