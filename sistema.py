"""Navegación en Hospital Office con Playwright (usa Chrome o Brave ya instalados)."""
import os
import re
import time
from datetime import datetime

import navegador
from comparar import PacienteSistema, emparejar
from errores import Cancelado, ErrorApp
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
    ESPERA_PERSONA = 300      # segundos que se espera a que la persona inicie sesión
    MSG_LOGIN_MALO = "Usuario o contraseña de Hospital Office no válidos"

    def __init__(self, contexto, cfg, log, carpeta_diag, credenciales=None, progreso=None, cancelado=None):
        """credenciales: {'usuario','clave'} o None (entonces la persona inicia sesión en la ventana)."""
        self.ctx = contexto
        self.cfg = cfg
        self.log = log
        self.diag = carpeta_diag
        self.cred = credenciales
        self.progreso = progreso or (lambda i, n, nombre: None)
        self.cancelado = cancelado or (lambda: False)
        self._url_grilla = None         # URL donde se vio la grilla la última vez
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

    def _ver_grilla(self, ms):
        """True si aparece alguna grilla de la Agenda dentro de ms milisegundos."""
        try:
            self.page.wait_for_selector(f"#{GRID_PEND}, #{GRID_ATEN}", timeout=ms)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _esperar_carga(self):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:  # noqa: BLE001
            pass
        self.page.wait_for_timeout(300)

    def _sigue_login(self):
        try:
            return self._pide_login()
        except Exception:  # noqa: BLE001  (la página está navegando)
            return True

    def _vaciar_clave(self):
        """Borra el campo de contraseña de la página (valor y atributo) antes de guardar un diagnóstico."""
        try:
            self.page.evaluate(
                "() => document.querySelectorAll('input[type=password]').forEach(e => {"
                " e.value = ''; e.removeAttribute('value'); })")
        except Exception:  # noqa: BLE001
            pass

    def _escribir_credenciales(self):
        """Rellena usuario (el input de texto visible más cercano antes del de contraseña) y contraseña."""
        hay = self.page.evaluate(
            """() => {
              const vis = e => !!(e.offsetParent || e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
              document.querySelectorAll('[data-kardex-u]').forEach(e => e.removeAttribute('data-kardex-u'));
              document.querySelectorAll('[data-kardex-p]').forEach(e => e.removeAttribute('data-kardex-p'));
              const todos = [...document.querySelectorAll('input')];
              const pw = todos.find(e => (e.getAttribute('type') || '').toLowerCase() === 'password' && vis(e));
              if (!pw) return false;
              pw.setAttribute('data-kardex-p', '1');
              for (let i = todos.indexOf(pw) - 1; i >= 0; i--) {
                const t = (todos[i].getAttribute('type') || 'text').toLowerCase();
                if ((t === 'text' || t === 'email') && vis(todos[i])) { todos[i].setAttribute('data-kardex-u', '1'); break; }
              }
              return true;
            }""")
        if not hay:
            raise ErrorApp("sesion", "No encontré el campo de contraseña en la página de inicio de sesión de Hospital Office.")
        if self.page.locator("[data-kardex-u]").count():
            self.page.fill("[data-kardex-u]", self.cred["usuario"])
        self.page.fill("[data-kardex-p]", self.cred["clave"])

    def _enviar_login(self):
        patron = re.compile(r"ingresar|entrar|iniciar|login|aceptar", re.I)
        for loc in (self.page.locator("button[type=submit]:visible, input[type=submit]:visible"),
                    self.page.locator("button:visible, input[type=button]:visible, a:visible").filter(has_text=patron)):
            try:
                if loc.count():
                    loc.first.click(timeout=5000)
                    return
            except Exception:  # noqa: BLE001
                continue
        self.page.locator("[data-kardex-p]").press("Enter")

    def _login_automatico(self):
        self.log("Iniciando sesión en Hospital Office con el usuario guardado…")
        self._escribir_credenciales()
        self._enviar_login()
        for _ in range(20):                      # hasta ~10 s
            self.page.wait_for_timeout(500)
            if not self._sigue_login():
                self._esperar_carga()
                return
        self._vaciar_clave()
        self.diagnostico("login")
        raise ErrorApp("sesion", self.MSG_LOGIN_MALO)

    def _esperar_persona(self):
        self.log("Inicia sesión en Hospital Office en la ventana que se abrió; te espero.")
        self.progreso(0, 0, "Esperando inicio de sesión…")
        for _ in range(self.ESPERA_PERSONA):
            if self.cancelado():
                raise Cancelado()
            self.page.wait_for_timeout(1000)
            if not self._sigue_login():
                self._esperar_carga()
                return
        self._vaciar_clave()
        self.diagnostico("login-espera")
        raise ErrorApp("sesion", "No inicié sesión en Hospital Office: se agotaron los 5 minutos de espera.")

    def asegurar_sesion(self):
        """Va a la Agenda; si pide iniciar sesión, entra con el usuario guardado o espera a la persona."""
        self.page.goto(self.cfg["url_agenda"], wait_until="domcontentloaded")
        if not self._pide_login():
            return
        if self.cred:
            self._login_automatico()
        else:
            self._esperar_persona()

    def _clic_texto(self, fragmento, espera_ms):
        """Pulsa un enlace/botón visible cuyo texto contiene fragmento (sin mayúsculas ni tildes)."""
        marca = "data-kardex-clic"
        for _ in range(max(1, espera_ms // 500)):
            try:
                hay = self.page.evaluate(
                    """([frag, marca]) => {
                      const quitar = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
                      const vis = e => !!(e.offsetParent || e.getClientRects().length);
                      document.querySelectorAll('[' + marca + ']').forEach(e => e.removeAttribute(marca));
                      const c = [...document.querySelectorAll('a, button, input[type=button], input[type=submit], [role=button], [role=menuitem], li, td, span, div')]
                        .filter(e => vis(e) && quitar(e.tagName === 'INPUT' ? e.value : e.innerText).includes(frag));
                      if (!c.length) return false;
                      // el más específico: el que no contiene a otro candidato
                      const hoja = c.filter(e => !c.some(o => o !== e && e.contains(o)));
                      const pref = hoja.find(e => /^(A|BUTTON|INPUT)$/.test(e.tagName) || e.getAttribute('role'))
                        || hoja.find(e => e.closest('a, button')) || hoja[0];
                      const obj = pref.closest('a, button') || pref;
                      obj.setAttribute(marca, '1');
                      return true;
                    }""", [fragmento, marca])
                if hay:
                    self.page.locator(f"[{marca}]").first.click(timeout=5000)
                    return True
            except Exception:  # noqa: BLE001  (la página navegó mientras buscaba)
                pass
            self.page.wait_for_timeout(500)
        return False

    def _por_el_menu(self):
        """Desde la pantalla de inicio: «Menu Principal» y luego «Atención de pacientes»."""
        pulso = False
        if self._clic_texto("menu principal", 3000):
            pulso = True
            self._esperar_carga()
        if self._ver_grilla(1500):
            return True
        if self._clic_texto("atencion de pacientes", 5000 if pulso else 3000):
            pulso = True
            self._esperar_carga()
        return self._ver_grilla(15000) if pulso else False

    def ir_agenda(self):
        """Deja la página en la Agenda con sus grillas. Siempre puede volver a iniciar sesión."""
        if self._url_grilla:
            try:
                self.page.goto(self._url_grilla, wait_until="domcontentloaded")
                if not self._pide_login() and self._ver_grilla(5000):
                    return
            except Exception:  # noqa: BLE001
                pass
            self._url_grilla = None            # la sesión venció o la página cambió: proceso completo
        self.asegurar_sesion()
        if not self._ver_grilla(5000) and not self._por_el_menu():
            self.diagnostico("agenda")
            if self._pide_login():
                raise ErrorApp("sesion", "Hospital Office pide iniciar sesión.")
            raise ErrorApp("agenda", "No se ve la Agenda de Hospital Office.")
        self._url_grilla = self.page.url

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
        except Cancelado:
            raise
        except ErrorApp as e:
            if e.codigo == "sesion":      # sin sesión no se puede seguir con nadie
                raise
            p.aviso = f"No pude leer su historia: {e.mensaje}"
            self.diagnostico("error-" + p.nombre.split()[0])
        except Exception as e:  # noqa: BLE001
            p.aviso = f"Error leyendo la historia: {_primera_linea(e)}"
            self.diagnostico("error-" + p.nombre.split()[0])
        return p
