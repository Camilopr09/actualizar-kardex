"""Navegación en Hospital Office con Playwright (usa Chrome o Brave ya instalados)."""
import os
import re
import time
import unicodedata
from datetime import datetime
from urllib.parse import urlparse

import navegador
from comparar import MODOS_AGENDA, PacienteSistema, emparejar, parsear_identificacion
from errores import Cancelado, ErrorApp
from notas import (clave, construir_evolucion, construir_tratamiento, en_renglones, extraer_dx,
                   interpretar_evolucion, interpretar_ordenes, normalizar)

GRID_PEND = "ctl00_cph1_cbpPanel1_grdPendientes"
GRID_ATEN = "ctl00_cph1_cbpPanel1_grdAtendidos"
GRID_FORM = "ctl00_cph1_ASPxRoundPanel2_grdFormatos"
MODOS = MODOS_AGENDA
_COLS_DEFECTO = {"paciente": 0, "identificacion": 1, "admision": 2, "convenio": 3, "habitacion": 4, "estado": 5}


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


_JS_AYUDAS = r"""
const quitar = s => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
const borde = s => quitar(s).replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, '');
const vis = e => {
  const r = e.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) return false;
  for (let a = e; a && a.nodeType === 1; a = a.parentElement) {
    const cs = getComputedStyle(a);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (a !== e && a.tagName !== 'BODY' && a.tagName !== 'HTML' && cs.overflow !== 'visible') {
      const q = a.getBoundingClientRect();
      if (q.width <= 0 || q.height <= 0 || r.bottom <= q.top || r.top >= q.bottom || r.right <= q.left || r.left >= q.right) return false;
    }
  }
  return true;
};
const ctl = id => {
  try {
    const col = ASPxClientControl.GetControlCollection();
    let c = col.elements[id];
    if (!c) c = Object.values(col.elements).find(x => x && (x.name === id || (x.GetMainElement && (x.GetMainElement() || {}).id === id)));
    return c || null;
  } catch (e) { return null; }
};
// texto de un elemento y candidatos «hoja» visibles cuyo texto es la frase (exacto: sin íconos/signos en los bordes) o la contiene
const tx = e => e.tagName === 'INPUT' ? (e.value || '') : (e.innerText || '');
const SEL_TXT = 'a, button, input[type=button], input[type=submit], [role=button], [role=menuitem], [role=link], li, td, th, span, div, label, b, strong, p, h1, h2, h3, h4, h5, font';
const coincide = (e, frag, exacto) => exacto ? borde(tx(e)) === frag : quitar(tx(e)).includes(frag);
const candidatos = (frag, exacto) => {
  const c = [...document.querySelectorAll(SEL_TXT)].filter(e => vis(e) && coincide(e, frag, exacto));
  return c.filter(e => !c.some(o => o !== e && e.contains(o)));
};
const cabeza = id => document.getElementById(id + '_DXHeadRow') || document.querySelector('[id^="' + id + '_DXHeadRow"]');
const pwVisible = () => [...document.querySelectorAll('input')].find(e => (e.getAttribute('type') || '').toLowerCase() === 'password' && vis(e));
// elementos que parecen el botón ENTRAR: imagen/envío, o id/name/alt/title/value/texto con «entrar» (el más interno)
const botonesEntrar = () => {
  const c = [...document.querySelectorAll('a, img, div, span, input')].filter(e => {
    if (!vis(e)) return false;
    const t = ['id', 'name', 'alt', 'title', 'value'].map(a => quitar(e.getAttribute(a)));
    const src = e.getAttribute('src') || '';
    if (src && !/^data:/i.test(src)) t.push(quitar(src.split('?')[0]));      // p. ej. /img/entrar.png
    t.push(...['entrar', 'login', 'ingres'].map(k => quitar(src).includes(k) && !/^data:/i.test(src) ? 'entrar' : ''));
    if (e.children.length <= 1 && (e.innerText || '').length < 30) t.push(quitar(e.innerText));
    return t.some(x => x.includes('entrar') || /(login|ingres)/.test(x));
  });
  return c.filter(e => !c.some(o => o !== e && e.contains(o)));
};
"""


def quitar_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if not unicodedata.combining(c))


def _js(cuerpo):
    """Función JS lista para page.evaluate: «(arg) => { ayudas + cuerpo }»."""
    return "(arg) => {" + _JS_AYUDAS + cuerpo + "}"


# arg = la URL tiene «login». Un campo de contraseña visible es decisivo; «Salir», «DashBoard» o el menú indican que
# ya se está dentro. El pie «Software Asistencial eHC» (o «Historias Clinicas») cuenta como login con ≥2 campos de
# texto/contraseña visibles (la contraseña puede ser type=text con texto guía), o con 1 campo y un botón de entrar
# (que puede ser una imagen sin texto: input[type=image], src con «entrar»/«login»/«ingres», cualquier envío visible).
_JS_PIDE_LOGIN = _js("""
  if (pwVisible()) return true;
  const t = quitar(document.body ? document.body.innerText : '');
  if (/\\bsalir\\b/.test(t) || t.includes('dashboard') || t.includes('menu principal')) return false;
  if (arg) return true;
  if (!t.includes('software asistencial ehc') && !t.includes('historias clinicas')) return false;
  const campos = [...document.querySelectorAll('input')].filter(e =>
    ['text', 'email', 'search', 'tel', 'password', ''].includes((e.getAttribute('type') || '').toLowerCase()) && vis(e));
  if (campos.length >= 2) return true;
  if (!campos.length) return false;
  return botonesEntrar().length > 0 || [...document.querySelectorAll('input[type=image], input[type=submit]')].some(vis);
""")

_JS_GRILLAS = _js("""
  const ctlDe = a => {            // id del control DevExpress que contiene a la tabla a (o de la tabla con id más cercana)
    for (let t = a; t; t = t.parentElement ? t.parentElement.closest('table') : null) {
      if (t.id && document.querySelector('[id^="' + t.id + '_DX"]')) return t.id;
    }
    for (let e = a; e; e = e.parentElement) {
      if (e.id && /(grd|grid|gv|gridview)\\w*$/i.test(e.id)) return e.id;
    }
    for (let t = a; t; t = t.parentElement ? t.parentElement.closest('table') : null) if (t.id) return t.id;
    if (!a.id) a.id = 'kardex-grilla-' + Math.floor(Math.random() * 1e6);
    return a.id;
  };
  const buscar = (id, titulo) => {
    if (id && document.getElementById(id)) return id;
    const els = [...document.querySelectorAll('td, th, span, div, h1, h2, h3, h4, caption')]
      .filter(e => borde(e.innerText) === titulo && vis(e));
    for (const e of els) {
      for (let a = e.closest('table'); a; a = a.parentElement ? a.parentElement.closest('table') : null) {
        if (a.id && document.querySelector('[id^="' + a.id + '_DX"]')) return a.id;
      }
    }
    return null;
  };
  // tabla cuya fila de encabezados trae Paciente + Identificacion + Habitacion (sin título ni id conocidos)
  const porEncabezados = excluir => {
    for (const tr of document.querySelectorAll('tr')) {
      if (tr.children.length < 3 || tr.children.length > 30) continue;
      const h = [...tr.children].map(c => borde(c.innerText));
      if (!(h.includes('paciente') && h.includes('identificacion') && h.includes('habitacion')) || !vis(tr)) continue;
      const tabla = tr.closest('table');
      if (!tabla) continue;
      const m = /^(.*)_DXHeadRow\\d*$/.exec(tr.id || '');
      const id = m ? m[1] : ctlDe(tabla);
      if (id && !excluir.includes(id)) return id;
    }
    return null;
  };
  const aten = buscar(arg[1], 'pacientes atendidos');
  let pend = buscar(arg[0], 'pacientes por atender');
  if (!pend) pend = porEncabezados([aten]);
  return [pend, aten];
""")


# Panel «Detalle del Formato»: título «Formato: N - NOMBRE», pestañas DevExpress (dxtc-tab…) y controles visibles.
_JS_DET = r"""
const titulo = () => {
  const c = [...document.querySelectorAll('td, th, span, div, h1, h2, h3, h4, h5, legend, b, strong, label')]
    .filter(e => vis(e) && e.innerText.length < 300 && /^formato\s*:\s*\d+/.test(quitar(e.innerText)));
  return c.find(e => !c.some(o => o !== e && e.contains(o))) || null;
};
const NOMBRES = ['diagnostico', 'unidad en donde se encuentra el paciente', 'hipotesis diagnostica', 'sintomas descritos',
                 'examen fisico', 'analisis', 'plan', 'solicitud material especial'];
const enGrilla = e => !!e.closest('[id^="' + arg.grid + '_"]');
const pestanas = c => {
  const esTab = e => [...e.classList].some(k => /^dxtc-?(active)?tab$/i.test(k));
  let l = [...c.querySelectorAll('*')].filter(e => esTab(e) && vis(e) && borde(e.innerText));
  l = l.filter(e => !l.some(o => o !== e && e.contains(o)));
  if (!l.length) {
    const vistos = new Set();
    l = [...c.querySelectorAll('a, li, td, span')].filter(e => vis(e) && NOMBRES.includes(borde(e.innerText)));
    l = l.filter(e => !l.some(o => o !== e && e.contains(o)) && !enGrilla(e)).filter(e => {
      const k = borde(e.innerText); if (vistos.has(k)) return false; vistos.add(k); return true; });
  }
  return l.map(e => ({texto: e.innerText.trim(), clic: e.querySelector('a') || e,
                      activa: [...e.classList].some(k => /active/i.test(k)) || !!e.closest('[class*="ctiveTab"], [class*="dxtc-active"]')}));
};
const controles = c => [...c.querySelectorAll('textarea, select, input')].filter(e => {
  const t = (e.getAttribute('type') || 'text').toLowerCase();
  return !['hidden', 'button', 'submit', 'image', 'checkbox', 'radio', 'reset', 'file'].includes(t) && !enGrilla(e) && vis(e);
});
const etiqueta = (e, c) => {
  if (e.labels && e.labels.length) return e.labels[0].innerText.trim();
  for (let a = e; a && a !== c; a = a.parentElement) {
    if (a.tagName === 'TD' || a.tagName === 'TH') {
      for (let p = a.previousElementSibling; p; p = p.previousElementSibling) {
        const t = (p.innerText || '').trim();
        if (t && !p.querySelector('textarea, select, input')) return t;
      }
    }
  }
  return '';
};
const valor = e => e.tagName === 'SELECT' ? [...e.selectedOptions].map(o => o.text).join(', ') : (e.value || '');
const enCallback = () => {
  try {
    const col = ASPxClientControl.GetControlCollection().elements;
    if (Object.values(col).some(x => x && x.InCallback && x.InCallback())) return true;
  } catch (er) { /* sin librería */ }
  return [...document.querySelectorAll('[class*="dxlp"], [id$="_LP"], [id*="LoadingPanel"]')].some(e => vis(e) && !/^\s*$/.test(e.innerText || 'x'));
};
const contenedor = () => {
  const t = titulo();
  for (let a = t && t.parentElement; a; a = a.parentElement) {
    if (pestanas(a).length || controles(a).length) return a;
  }
  return null;
};
"""

_JS_ESTADO = """
  const c = contenedor();
  if (!c) return null;
  const tabs = pestanas(c);
  let activa = false;
  if (arg.i !== null) {
    document.querySelectorAll('[data-kardex-tab]').forEach(e => e.removeAttribute('data-kardex-tab'));
    const t = tabs[arg.i];
    if (!t) return {textos: tabs.map(x => x.texto), n: 0, ausente: true};
    t.clic.setAttribute('data-kardex-tab', '1');
    activa = t.activa;
  }
  if (arg.guardar) window.__kardexPrev = controles(c);
  const ctls = controles(c);
  const prev = window.__kardexPrev || [];
  return {textos: tabs.map(x => x.texto), activa: activa, n: ctls.length, nuevos: ctls.some(e => !prev.includes(e)),
          cb: enCallback(), campos: arg.leer ? ctls.map(e => ({etiqueta: etiqueta(e, c), valor: valor(e), tag: e.tagName})) : []};
"""



def pagina_pide_login(page):
    """True si la página es un inicio de sesión: campo de contraseña visible, URL con «login», o el texto
    «Software Asistencial eHC» con un campo de usuario y un botón ENTRAR. Si se ve «(Salir)» ya se está dentro
    (aunque la URL diga «login» o el pie de página repita «Software Asistencial eHC»)."""
    url_login = "login" in page.url.lower()
    try:
        return bool(page.evaluate(_JS_PIDE_LOGIN, url_login))
    except Exception:  # noqa: BLE001
        return url_login


def _frames_de(page):
    try:
        return list(page.frames) or [page.main_frame]
    except Exception:  # noqa: BLE001
        return [page.main_frame]


def hay_grilla(page):
    """True si algún frame de la página muestra la grilla de pacientes (por id, por su título «Pacientes Por
    Atender» o por sus encabezados) o la de atendidos."""
    for fr in _frames_de(page):
        try:
            if any(fr.evaluate(_JS_GRILLAS, [GRID_PEND, GRID_ATEN])):
                return True
        except Exception:  # noqa: BLE001
            continue
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

    def __init__(self, contexto, cfg, log, carpeta_diag, credenciales=None, progreso=None, cancelado=None,
                 pagina=None):
        """credenciales: {'usuario','clave'} o None (entonces la persona inicia sesión en la ventana)."""
        self.ctx = contexto
        self.cfg = cfg
        self.log = log
        self.diag = carpeta_diag
        self.cred = credenciales
        self.progreso = progreso or (lambda i, n, nombre: None)
        self.cancelado = cancelado or (lambda: False)
        self._url_grilla = None         # URL donde se vio la grilla la última vez
        self.grid_pend = GRID_PEND      # id real de la grilla «Pacientes Por Atender» (se descubre al verla)
        self.grid_aten = GRID_ATEN
        self._filtros = {}              # grilla -> {columna: texto} filtros puestos en esta carga de la página
        self._cols = {}                 # (grilla, columna) -> (posición, campo) descubiertos
        self._modo_actual = None
        self.page = pagina or (contexto.pages[0] if contexto.pages else contexto.new_page())
        self.page.set_default_timeout(20000)
        self._frame = self.page.main_frame   # frame donde se vio la grilla: todas las operaciones sobre ella lo usan
        self._paso = ""                      # paso de la navegación que falló (mensaje para ErrorApp)
        self._agenda_al_dashboard = None     # ruta del dashboard si url_agenda redirige allí (no se repite el goto)

    # ------------------------------------------------------------ utilidades
    def _fr(self):
        """Frame donde está la grilla (el documento principal si aún no se ha visto o ya no existe)."""
        f = self._frame
        try:
            if f is not None and not f.is_detached():
                return f
        except Exception:  # noqa: BLE001
            pass
        self._frame = self.page.main_frame
        return self._frame

    def diagnostico(self, etiqueta):
        """Guarda el HTML de cada frame (el principal en .html, los demás en -frameN.html) y una captura."""
        try:
            self.diag.mkdir(parents=True, exist_ok=True)
            base = self.diag / f"{datetime.now():%Y%m%d-%H%M%S}-{etiqueta}"
            try:
                self.page.screenshot(path=str(base.with_suffix(".png")))
            except Exception:  # noqa: BLE001
                pass
            for k, fr in enumerate(_frames_de(self.page)):
                try:
                    destino = base.with_suffix(".html") if k == 0 else base.parent / f"{base.name}-frame{k}.html"
                    destino.write_text(fr.content(), encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    def _esperar_grid(self, grid):
        try:
            self._fr().wait_for_function(
                "g => { const c = ASPxClientControl.GetControlCollection().elements[g];"
                " return !c || !c.InCallback(); }", arg=grid, timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        self.page.wait_for_timeout(300)

    def _filtrar(self, grid, columna, texto):
        """Filtro por AutoFilterByColumn (grilla de formatos)."""
        self._fr().evaluate(
            "([g,c,t]) => { const x = ASPxClientControl.GetControlCollection().elements[g];"
            " if (x) x.AutoFilterByColumn(c, t); }", [grid, columna, texto])
        self._esperar_grid(grid)

    # ------------------------------------------------------------ lectura de grillas (Agenda)
    def _buscar_grillas(self):
        """(id de pendientes o None, id de atendidos o None) en la página actual, en cualquier frame; recuerda los
        ids reales y el frame donde está la grilla (`self._frame`)."""
        marco = self._fr()
        frames = [marco] + [f for f in _frames_de(self.page) if f is not marco]
        for fr in frames:
            try:
                p, a = fr.evaluate(_JS_GRILLAS, [self.grid_pend, self.grid_aten])
            except Exception:  # noqa: BLE001
                continue
            if p or a:
                self._frame = fr
                if p:
                    self.grid_pend = p
                if a:
                    self.grid_aten = a
                return p, a
        return None, None

    def _grillas(self):
        """Grillas presentes ahora, pendientes primero."""
        return [g for g in self._buscar_grillas() if g]

    def _ver_grilla(self, ms):
        """True si aparece alguna grilla de la Agenda dentro de ms milisegundos."""
        for _ in range(max(1, ms // 300)):
            if any(self._buscar_grillas()):
                return True
            self.page.wait_for_timeout(300)
        return False

    def _estado_grilla(self, grid):
        """(en callback, firma de las filas visibles) o None si la página está cambiando."""
        try:
            return self._fr().evaluate(_js(
                "const c = ctl(arg); return [c && c.InCallback ? !!c.InCallback() : false,"
                " [...document.querySelectorAll('[id^=\"' + arg + '_DXDataRow\"]')].map(t => t.innerText).join('|')];"), grid)
        except Exception:  # noqa: BLE001
            return None

    def _esperar_cambio(self, grid, antes, minimo=1500, maximo=12000):
        """Espera a que termine el callback de la grilla o a que cambien sus filas."""
        t0 = time.monotonic()
        visto = False
        while True:
            self.page.wait_for_timeout(150)
            ms = (time.monotonic() - t0) * 1000
            est = self._estado_grilla(grid)
            if est:
                if est[0]:
                    visto = True
                elif visto or est[1] != antes:
                    self.page.wait_for_timeout(300)
                    return
            if ms >= (maximo if visto else minimo):
                return

    def _datos_columnas(self, grid):
        return self._fr().evaluate(_js("""
          const h = cabeza(arg);
          const c = ctl(arg);
          const cols = [];
          if (c && c.GetColumnsCount) for (let i = 0; i < c.GetColumnsCount(); i++) {
            const k = c.GetColumn(i);
            if (k) cols.push([String(k.fieldName || ''), String(k.name || ''), String(k.caption || k.Caption || ''), i, k.visible !== false]);
          }
          return {head: h ? [...h.children].map(td => borde(td.innerText)) : [], cols: cols};
        """), grid)

    def _columna(self, grid, caption):
        """(posición de la columna en la tabla, campo para AutoFilterByColumn) de la columna con ese título."""
        clave = (grid, caption)
        if clave in self._cols:
            return self._cols[clave]
        try:
            d = self._datos_columnas(grid)
        except Exception:  # noqa: BLE001
            return None, None
        head, cols = d["head"], d["cols"]
        pos = head.index(caption) if caption in head else None
        campo = None
        for fn, nm, cp, i, _v in cols:                     # 1) por el nombre del campo / caption del cliente
            if any(caption in normalizar(x).lower() for x in (fn, nm, cp)):
                campo = fn or i
                break
        if campo is None and pos is not None:               # 2) por la posición del encabezado
            vis = [c for c in cols if c[4]]
            base = vis if len(vis) == len(head) else cols
            if pos < len(base):
                campo = base[pos][0] or base[pos][3]
        if pos is not None or campo is not None:
            self._cols[clave] = (pos, campo)
        return pos, campo

    def _filas(self, grid):
        """Filas de datos de la página actual de la grilla, como dicts."""
        crudo = self._fr().evaluate(_js("""
          const h = cabeza(arg);
          return {head: h ? [...h.children].map(td => borde(td.innerText)) : [],
                  filas: [...document.querySelectorAll('[id^="' + arg + '_DXDataRow"]')]
                    .map(tr => [...tr.children].map(td => (td.innerText || '').trim()))};
        """), grid)
        head = crudo["head"]
        idx = {k: (head.index(k) if k in head else d) for k, d in _COLS_DEFECTO.items()}
        filas = []
        for celdas in crudo["filas"]:
            if len(celdas) <= max(idx["paciente"], idx["identificacion"], idx["habitacion"]):
                continue
            nombre = re.sub(r"\s+", " ", celdas[idx["paciente"]]).strip()
            if not nombre:
                continue
            tipo, numero = parsear_identificacion(celdas[idx["identificacion"]])
            g = lambda k: re.sub(r"\s+", " ", celdas[idx[k]]).strip() if idx[k] < len(celdas) else ""  # noqa: E731
            filas.append({"nombre": nombre, "tipo": tipo, "numero": numero, "admision": g("admision"),
                          "habitacion": g("habitacion"), "estado": g("estado"), "pagina": 0})
        return filas

    def _js_cliente(self, grid, expresion, arg=None):
        """Evalúa una expresión sobre el control cliente de la grilla (c); None si no existe."""
        return self._fr().evaluate(_js("const c = ctl(arg[0]); if (!c) return null; const a = arg[1]; " + expresion),
                                  [grid, arg])

    def _ir_pagina(self, grid, k):
        self._js_cliente(grid, "if (c.GotoPage) c.GotoPage(a);", k)
        self._esperar_grid(grid)

    def _boton_siguiente(self, grid):
        """Marca y devuelve True si hay un botón de página siguiente habilitado."""
        return self._fr().evaluate(_js("""
          document.querySelectorAll('[data-kardex-sig]').forEach(e => e.removeAttribute('data-kardex-sig'));
          const zona = [...document.querySelectorAll('[id^="' + arg + '_DXPager"]')];
          for (const z of zona) for (const e of z.querySelectorAll('a, img, span, td')) {
            if (!vis(e) || /disabled/i.test(e.className || '')) continue;
            const oc = e.getAttribute('onclick') || '';
            const t = borde(e.innerText) || quitar(e.getAttribute('alt') || e.getAttribute('title'));
            if (/PBN/.test(oc) || ['siguiente', 'next', '>', 'sig'].includes(t) || /^[>›»]/.test((e.innerText || '').trim())) {
              if (e.tagName === 'SPAN' && !/PBN/.test(oc)) continue;
              e.setAttribute('data-kardex-sig', '1'); return true;
            }
          }
          return false;
        """), grid)

    def _leer_todo(self, grid, max_paginas=300):
        """Todas las filas de la grilla, recorriendo sus páginas (GotoPage del cliente DevExpress;
        respaldo: botón de página siguiente)."""
        try:
            n = self._js_cliente(grid, "return c.GetPageCount ? c.GetPageCount() : null;")
        except Exception:  # noqa: BLE001
            n = None
        if isinstance(n, int) and n >= 1:
            todas = []
            for k in range(min(n, max_paginas)):
                if k:
                    self._ir_pagina(grid, k)
                for f in self._filas(grid):
                    f["pagina"] = k
                    todas.append(f)
            if n > 1:
                self._ir_pagina(grid, 0)
            return todas
        todas, vistas = [], set()
        for k in range(max_paginas):
            filas = self._filas(grid)
            firma = tuple((f["nombre"], f["numero"]) for f in filas)
            if firma in vistas:
                break
            vistas.add(firma)
            for f in filas:
                f["pagina"] = k
                todas.append(f)
            if not self._boton_siguiente(grid):
                break
            antes = self._estado_grilla(grid)
            self._fr().locator("[data-kardex-sig]").first.click(timeout=5000)
            self._esperar_cambio(grid, antes[1] if antes else "", minimo=1200)
        return todas

    def _filtro_js(self, grid, campo, texto):
        self._js_cliente(grid, "if (c.AutoFilterByColumn) c.AutoFilterByColumn(a[0], a[1]);", [campo, texto])
        self._esperar_grid(grid)

    def _filtro_escrito(self, grid, pos, texto):
        """Respaldo: escribe en el input de la fila de filtros de esa columna y Enter."""
        celda = self._fr().locator(f'[id="{grid}_DXFilterRow"] > td').nth(pos)
        caja = celda.locator("input[type=text], input:not([type])").first
        antes = self._estado_grilla(grid)
        caja.click(timeout=5000)
        self.page.keyboard.press("Control+A")
        if texto:
            self.page.keyboard.type(texto)
        else:
            self.page.keyboard.press("Delete")
        self.page.keyboard.press("Enter")
        self._esperar_cambio(grid, antes[1] if antes else "", minimo=1200)

    def _contiene(self, caption, fila, texto):
        if caption == "identificacion":
            return re.sub(r"\D", "", texto) in fila["numero"] or re.sub(r"\D", "", texto) == ""
        return normalizar(texto) in normalizar(fila["nombre"])

    def _poner_filtro(self, grid, caption, texto):
        """Deja la grilla filtrada SOLO por esa columna (quita antes el filtro de las otras columnas puestas por nosotros)."""
        activos = self._filtros.setdefault(grid, {})
        for otra in [c for c, t in activos.items() if c != caption and t]:
            self._cambiar_filtro(grid, otra, "")
            activos[otra] = ""
        self._cambiar_filtro(grid, caption, texto)
        activos[caption] = texto

    def _cambiar_filtro(self, grid, caption, texto):
        pos, campo = self._columna(grid, caption)
        hecho = False
        if campo is not None:
            try:
                self._filtro_js(grid, campo, texto)
                hecho = self._filtro_aplicado(grid, caption, pos, texto)
            except Exception:  # noqa: BLE001
                hecho = False
        if not hecho and pos is not None:
            self._filtro_escrito(grid, pos, texto)

    def _filtro_aplicado(self, grid, caption, pos, texto):
        """¿AutoFilterByColumn hizo efecto? DevExpress muestra el filtro en el input de la fila de filtros; si no
        se puede mirar ese input, se mira que alguna fila cumpla el filtro (con filas y ninguna que cumpla = no hizo nada)."""
        if pos is not None:
            valor = self._fr().evaluate(
                "([g, p]) => { const r = document.getElementById(g + '_DXFilterRow'); const c = r && r.children[p];"
                " const i = c && c.querySelector('input[type=text], input:not([type])'); return i ? i.value : null; }",
                [grid, pos])
            if valor is not None:
                return valor.strip().lower() == (texto or "").strip().lower()
        filas = self._filas(grid)
        return not texto or not filas or any(self._contiene(caption, f, texto) for f in filas)

    def _filtrar_y_leer(self, grid, caption, texto, todas=False):
        self._poner_filtro(grid, caption, texto)
        return self._leer_todo(grid, 8) if todas else self._filas(grid)

    # ------------------------------------------------------------ agenda
    def _pide_login(self):
        """True si la página actual es un inicio de sesión."""
        return pagina_pide_login(self.page)

    def _esperar_carga(self, a_fondo=False):
        """Espera a que cargue la página; con a_fondo, también a que la red se calme (con tope: algunas páginas
        hacen peticiones periódicas y nunca quedan quietas)."""
        try:
            self.page.wait_for_load_state("load" if a_fondo else "domcontentloaded", timeout=10000)
        except Exception:  # noqa: BLE001
            pass
        if a_fondo:
            try:
                self.page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:  # noqa: BLE001
                pass
        self.page.wait_for_timeout(300)

    def _sigue_login(self):
        try:
            return self._pide_login()
        except Exception:  # noqa: BLE001  (la página está navegando)
            return True

    def _login_ok(self):
        """Ya se entró: se ve «(Salir)»/«Salir», «DashBoard» o la grilla, o ya no hay pantalla de login."""
        try:
            if self.page.evaluate(_js(
                    "const t = quitar(document.body ? document.body.innerText : '');"
                    " return /\\bsalir\\b/.test(t) || t.includes('dashboard');")):
                return True
            if any(self._buscar_grillas()):
                return True
        except Exception:  # noqa: BLE001  (navegando)
            return False
        return not self._sigue_login()

    def _vaciar_clave(self):
        """Borra el campo de contraseña de la página (valor y atributo) antes de guardar un diagnóstico."""
        try:
            self.page.evaluate(
                "() => document.querySelectorAll('input[type=password]').forEach(e => {"
                " e.value = ''; e.removeAttribute('value'); })")
        except Exception:  # noqa: BLE001
            pass

    def _escribir_credenciales(self):
        """Marca usuario y contraseña y los rellena con clic + Ctrl+A + Supr + teclado (así funcionan los textos
        guía / watermark de DevExpress). Contraseña = el input type=password visible o, si no lo hay (el campo
        cambia a password al enfocar), el segundo input de texto visible; usuario = el visible anterior."""
        hay = self.page.evaluate(_js("""
          document.querySelectorAll('[data-kardex-u]').forEach(e => e.removeAttribute('data-kardex-u'));
          document.querySelectorAll('[data-kardex-p]').forEach(e => e.removeAttribute('data-kardex-p'));
          const campos = [...document.querySelectorAll('input')].filter(e =>
            ['text', 'email', 'search', 'tel', 'password', ''].includes((e.getAttribute('type') || '').toLowerCase()) && vis(e));
          let pw = pwVisible();
          if (!pw) pw = campos[1] || null;
          if (!pw) return false;
          pw.setAttribute('data-kardex-p', '1');
          const antes = campos.filter(e => e !== pw && (e.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING));
          const u = antes.pop() || campos.find(e => e !== pw);
          if (u) u.setAttribute('data-kardex-u', '1');
          return true;
        """))
        if not hay:
            raise ErrorApp("sesion", "No encontré el campo de contraseña en la página de inicio de sesión de Hospital Office.")
        for _ in range(2):
            for marca, valor in (("data-kardex-u", self.cred["usuario"]), ("data-kardex-p", self.cred["clave"])):
                caja = self.page.locator(f"[{marca}]")
                if not caja.count():
                    continue
                caja.first.click(timeout=5000)
                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Delete")
                self.page.keyboard.type(valor)
                self.page.keyboard.press("Tab")                  # blur: algunos formularios validan al salir del campo
            u = self.page.locator("[data-kardex-u]")
            if not u.count() or u.first.input_value() == self.cred["usuario"]:
                break                                            # si el texto guía «Usuario» sigue, se reescribe

    def _enviar_login(self):
        """Botón de entrar: input[type=image], input[type=submit], button, algo con «entrar», una imagen dentro de
        un enlace junto al formulario; si nada sirve, Enter en la contraseña."""
        for sel in ("input[type=image]:visible", "input[type=submit]:visible", "button:visible"):
            try:
                loc = self.page.locator(sel)
                if loc.count():
                    loc.first.click(timeout=5000)
                    return
            except Exception:  # noqa: BLE001
                continue
        marca = "data-kardex-entrar"
        for cuerpo in (
                "const c = botonesEntrar(); if (!c.length) return false; c[0].setAttribute(arg, '1'); return true;",
                "const pw = pwVisible();"
                " const c = [...document.querySelectorAll('a img, a input[type=image]')].filter(vis);"
                " if (!c.length) return false;"
                " const d = c.filter(e => !pw || (pw.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING));"
                " (d[0] || c[0]).setAttribute(arg, '1'); return true;"):
            try:
                self.page.evaluate(_js("document.querySelectorAll('[' + arg + ']').forEach(e => e.removeAttribute(arg));"
                                       + cuerpo), marca)
                if self.page.evaluate(_js("return !!document.querySelector('[' + arg + ']');"), marca):
                    self.page.locator(f"[{marca}]").first.click(timeout=5000)
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
            if self._login_ok():
                self._esperar_carga(a_fondo=True)      # el login redirige: no buscar el menú a mitad de la navegación
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
                self._esperar_carga(a_fondo=True)
                return
        self._vaciar_clave()
        self.diagnostico("login-espera")
        raise ErrorApp("sesion", "No inicié sesión en Hospital Office: se agotaron los 5 minutos de espera.")

    def _ruta_actual(self):
        try:
            return urlparse(self.page.url).path.lower()
        except Exception:  # noqa: BLE001
            return ""

    def asegurar_sesion(self):
        """Va a la Agenda; si pide iniciar sesión, entra con el usuario guardado o espera a la persona.
        Si ya se está dentro, en el dashboard al que redirige `url_agenda`, no se vuelve a pedir esa URL (evita bucles)."""
        if (self._agenda_al_dashboard and self._ruta_actual() == self._agenda_al_dashboard
                and not self._sigue_login() and self._login_ok()):
            return
        destino = urlparse(self.cfg["url_agenda"]).path.lower()
        self.page.goto(self.cfg["url_agenda"], wait_until="domcontentloaded")
        if not self._pide_login():
            self._esperar_carga(a_fondo=True)
            ruta = self._ruta_actual()
            if ruta and ruta != destino and not self._ver_grilla(300):
                self._agenda_al_dashboard = ruta       # la URL de la Agenda lleva a otra pantalla (el dashboard)
            return
        if self.cred:
            self._login_automatico()
        else:
            self._esperar_persona()

    @staticmethod
    def _patron_texto(frase, exacto):
        """Regex (sin distinguir mayúsculas ni tildes) para get_by_text/get_by_role: «Atenci[oó]n\\s+de\\s+Pacientes».
        Con exacto, solo admite signos/íconos en los bordes («» Menu Principal»)."""
        alt = {"a": "aáàä", "e": "eéèë", "i": "iíìï", "o": "oóòö", "u": "uúùü"}
        cuerpo = []
        for ch in quitar_tildes(frase).lower().strip():
            if ch.isspace():
                if not cuerpo or cuerpo[-1] != r"\s+":
                    cuerpo.append(r"\s+")
            elif ch in alt:
                cuerpo.append("[" + alt[ch] + "]")
            else:
                cuerpo.append(re.escape(ch))
        c = "".join(cuerpo)
        return r"^[\W_]*" + c + r"[\W_]*$" if exacto else c

    def _clic_nativo(self, fr, fragmento, exacto):
        """Estrategia con los localizadores de Playwright (texto y rol «link»/«button») y clic real."""
        pat = re.compile(self._patron_texto(fragmento, exacto), re.I)
        for loc in (fr.get_by_text(pat), fr.get_by_role("link", name=pat), fr.get_by_role("button", name=pat)):
            try:
                vis = loc.filter(visible=True)
                if vis.count():
                    vis.first.click(timeout=3000)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _clic_texto(self, fragmento, espera_ms, exacto=False):
        """Pulsa un elemento visible cuyo texto contiene fragmento (o, con exacto, es exactamente fragmento,
        sin contar íconos como «»» en los bordes). Sin mayúsculas ni tildes. Busca en TODOS los frames: primero
        con JS (marca el elemento más específico) y, si no sirve, con los localizadores de Playwright."""
        marca = "data-kardex-clic"
        for _ in range(max(1, espera_ms // 500)):
            for fr in _frames_de(self.page):
                try:
                    hay = fr.evaluate(_js("""
                      const [frag, marca, exacto] = arg;
                      document.querySelectorAll('[' + marca + ']').forEach(e => e.removeAttribute(marca));
                      const hoja = candidatos(frag, exacto);
                      if (!hoja.length) return false;
                      const pref = hoja.find(e => /^(A|BUTTON|INPUT)$/.test(e.tagName) || e.getAttribute('role'))
                        || hoja.find(e => e.closest('a, button')) || hoja[0];
                      const obj = pref.closest('a, button') || pref;
                      obj.setAttribute(marca, '1');
                      return true;
                    """), [fragmento, marca, exacto])
                    if hay:
                        objetivo = fr.locator(f"[{marca}]").first
                        try:
                            objetivo.click(timeout=3000)
                        except Exception:  # noqa: BLE001  (tapado por otro elemento: clic por JS)
                            objetivo.evaluate("e => e.click()")
                        return True
                except Exception:  # noqa: BLE001  (la página navegó mientras buscaba)
                    pass
                if self._clic_nativo(fr, fragmento, exacto):
                    return True
            self.page.wait_for_timeout(500)
        return False

    def _texto_visible(self, texto):
        """¿Hay en algún frame un elemento visible cuyo texto (sin íconos/signos en los bordes) es `texto`?"""
        for fr in _frames_de(self.page):
            try:
                if fr.evaluate(_js("return candidatos(arg, true).length > 0;"), texto):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _esperar_texto(self, texto, ms):
        for _ in range(max(1, ms // 250)):
            if self._texto_visible(texto):
                return True
            self.page.wait_for_timeout(250)
        return False

    def _por_el_menu(self):
        """Menú lateral tipo acordeón: pulsar la cabecera «Menu Principal» (solo si no está ya desplegada,
        porque pulsarla otra vez la pliega), esperar «Atencion de Pacientes», pulsarlo y esperar la grilla.
        Si falla, deja en `self._paso` el paso que falló."""
        self._paso = ""
        if self._ver_grilla(600):
            return True
        if not self._texto_visible("atencion de pacientes"):
            self.log("Abriendo Menu Principal…")
            if not self._clic_texto("menu principal", 4000, exacto=True):
                self._paso = 'No encontré "Menu Principal"'
                return False
            if not self._esperar_texto("atencion de pacientes", 3000):
                # la pulsación no desplegó nada (quizá estaba cerrándose): una vez más
                self._clic_texto("menu principal", 1500, exacto=True)
                if not self._esperar_texto("atencion de pacientes", 3000):
                    self._paso = 'Pulsé "Menu Principal" pero no apareció "Atencion de Pacientes"'
                    return False
        self.log("Entrando a Atencion de Pacientes…")
        if not self._clic_texto("atencion de pacientes", 4000, exacto=True):
            self._paso = 'No pude pulsar "Atencion de Pacientes"'
            return False
        self._esperar_carga()
        if not self._ver_grilla(15000):
            self._paso = 'Pulsé "Atencion de Pacientes" pero no reconocí la tabla de pacientes'
            return False
        return True

    def _donde(self):
        """« (página: <título> — <ruta>)» para los mensajes de error (sin query ni datos de pacientes)."""
        try:
            titulo = re.sub(r"\s+", " ", self.page.title() or "").strip()
        except Exception:  # noqa: BLE001
            titulo = ""
        try:
            ruta = urlparse(self.page.url).path
        except Exception:  # noqa: BLE001
            ruta = ""
        return f" (página: {titulo or 'sin título'} — {ruta or '/'})"

    def _url_de_la_grilla(self):
        fr = self._fr()
        return self.page.url if fr is self.page.main_frame else (fr.url or self.page.url)

    def ir_agenda(self):
        """Deja la página en la pantalla «Atencion De Pacientes» con su grilla. Siempre puede volver a iniciar sesión."""
        self._filtros = {}                     # página nueva: sin filtros ni modo elegido
        self._modo_actual = None
        self._frame = self.page.main_frame
        aprendida = self._url_grilla
        if aprendida:
            try:
                self.page.goto(aprendida, wait_until="domcontentloaded")
                self._frame = self.page.main_frame
                if not self._pide_login() and self._ver_grilla(5000):
                    self._url_grilla = self._url_de_la_grilla()
                    return
            except Exception:  # noqa: BLE001
                pass
            self._url_grilla = None            # la sesión venció o la página cambió: proceso completo
        self.asegurar_sesion()
        if self._ver_grilla(2500) or self._por_el_menu():
            self.log("Tabla de pacientes encontrada")
            self._url_grilla = self._url_de_la_grilla()
            return
        paso = self._paso or 'No encontré "Menu Principal"'
        if aprendida and aprendida != self.page.url:      # último recurso: la URL donde se vio la tabla antes
            try:
                self.page.goto(aprendida, wait_until="domcontentloaded")
                self._frame = self.page.main_frame
                if not self._pide_login() and self._ver_grilla(5000):
                    self.log("Tabla de pacientes encontrada")
                    self._url_grilla = self._url_de_la_grilla()
                    return
            except Exception:  # noqa: BLE001
                pass
        self.diagnostico("agenda")
        if self._pide_login():
            raise ErrorApp("sesion", "Hospital Office pide iniciar sesión.")
        raise ErrorApp("agenda", paso + self._donde())

    def _marcar_opcion(self, patron, tipo, deseado):
        """Pone una opción (radio o casilla) en el estado deseado, buscándola por su etiqueta (patrón sobre el
        texto normalizado). Lee el estado del input aunque esté oculto (DevExpress) y pulsa la etiqueta visible."""
        info = self._fr().evaluate(_js("""
          document.querySelectorAll('[data-kardex-opt]').forEach(e => e.removeAttribute('data-kardex-opt'));
          const re = new RegExp(arg[0]);
          const c = [...document.querySelectorAll('label, span, td, div, a')].filter(e => vis(e) && re.test(borde(e.innerText)));
          const hoja = c.filter(e => !c.some(o => o !== e && e.contains(o)));
          if (!hoja.length) return null;
          const e = hoja[0];
          let inp = e.control || e.querySelector('input[type=' + arg[1] + ']');
          for (let p = e.parentElement, n = 0; !inp && p && n < 3; p = p.parentElement, n++) {
            const l = [...p.querySelectorAll('input[type=' + arg[1] + ']')];
            inp = l.filter(i => (e.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_PRECEDING)).pop() || l[0];
          }
          e.setAttribute('data-kardex-opt', '1');
          return {checked: inp ? !!inp.checked : null};
        """), [patron, tipo])
        if not info:
            return False
        if info["checked"] is deseado:
            return True
        if info["checked"] is None and not deseado and tipo == "checkbox":
            return False
        self._fr().locator("[data-kardex-opt]").first.click(timeout=3000)
        self.page.wait_for_timeout(200)
        return True

    def _modo(self, modo):
        """Elige el radio del modo, quita «Últimas 24 horas» y pulsa «Actualizar» (sin eso la grilla no cambia);
        espera a que termine el callback o cambie la grilla."""
        patron = "^urgencias$" if modo == "Urgencias" else "^hospitalizacion$"
        try:
            ok = self._marcar_opcion(patron, "radio", True)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            self.log(f"  (no pude cambiar a modo {modo}; se usa el que esté activo)")
        try:
            self._marcar_opcion("^ultimas 24", "checkbox", False)
        except Exception:  # noqa: BLE001
            pass
        grid = self.grid_pend
        antes = self._estado_grilla(grid)
        if self._clic_texto("actualizar", 3000, exacto=True):
            self._esperar_cambio(grid, antes[1] if antes else "")
        else:
            self.log("  (no encontré el botón «Actualizar»)")
        self._modo_actual = modo

    # ------------------------------------------------------------ búsqueda de pacientes
    def _paciente(self, f, modo):
        return PacienteSistema(nombre=f["nombre"], habitacion=f["habitacion"], modo=modo, documento=f["numero"],
                               tipo_documento=f["tipo"], admision=f["admision"], estado=f["estado"])

    def _buscar_en_modo(self, nombre, documento, tipo, modo):
        """Busca en la grilla (ya en ese modo). Devuelve (PacienteSistema, grilla, fila) o None.
        Con documento filtra por Identificacion; si no hay (o no aparece) filtra por Paciente y empareja por nombre."""
        doc = re.sub(r"\D", "", documento or "")
        palabras = [t for t in normalizar(nombre).split() if len(t) >= 3]
        for grid in self._grillas():
            if doc:
                for texto in dict.fromkeys([doc, f"{tipo} - {doc}" if tipo else ""]):
                    if not texto:
                        continue
                    filas = self._filtrar_y_leer(grid, "identificacion", texto)
                    for i, f in enumerate(filas):
                        if f["numero"] == doc:
                            return self._paciente(f, modo), grid, i, f["pagina"]
            for pal in palabras[: (1 if doc else 3)]:
                filas = self._filtrar_y_leer(grid, "paciente", pal, todas=True)
                if doc:                                # otro documento = otra persona con nombre parecido
                    filas = [f for f in filas if not f["numero"] or f["numero"] == doc]
                nom = emparejar(nombre, [f["nombre"] for f in filas])
                if nom:
                    i = next(i for i, f in enumerate(filas) if f["nombre"] == nom)
                    return self._paciente(filas[i], modo), grid, i, filas[i]["pagina"]
        return None

    def buscar(self, nombre, documento="", tipo="", modos=MODOS):
        """Busca un paciente del kardex en la Agenda: en cada modo de `modos` (el preferido primero).
        PacienteSistema (con su modo) o None si no aparece en ninguno."""
        self.ir_agenda()
        for modo in modos:
            self._modo(modo)
            r = self._buscar_en_modo(nombre, documento, tipo, modo)
            if r:
                return r[0]
        return None

    def leer_atendidos(self):
        """Pacientes de la grilla de atendidos (todas sus páginas), de ambos modos. Lista vacía si no existe."""
        res = []
        for modo in MODOS:
            self.ir_agenda()
            self._modo(modo)
            if not self._buscar_grillas()[1]:
                continue
            res += [self._paciente(f, modo) for f in self._leer_todo(self.grid_aten)]
        return res

    # ------------------------------------------------------------ historia
    def _atender(self, p):
        self.ir_agenda()
        self._modo(p.modo)
        r = self._buscar_en_modo(p.nombre, p.documento, p.tipo_documento, p.modo)
        if not r:
            return False
        _, grid, i, pagina = r
        if pagina:
            self._ir_pagina(grid, pagina)
        fila = self._fr().locator(f'[id^="{grid}_DXDataRow"]').nth(i)
        enlace = fila.get_by_text("Atender", exact=True)
        if not enlace.count():
            return False
        enlace.first.click()
        self._fr().wait_for_selector(f"#{GRID_FORM}", timeout=20000)
        return True

    def _recargar(self):
        """Recarga la pantalla actual (el frame de la grilla; no toda la página si está dentro de un iframe)."""
        fr = self._fr()
        if fr is self.page.main_frame:
            self.page.reload(wait_until="domcontentloaded")
        else:
            with fr.expect_navigation(wait_until="domcontentloaded"):
                fr.evaluate("() => location.reload()")

    def _leer_textareas(self):
        return self._fr().evaluate("[...document.querySelectorAll('textarea')].map(t=>t.value).join('\\n')")

    # --- panel «Detalle del Formato» (page control DevExpress con pestañas verticales)
    def _titulo_detalle(self):
        """(N° de formato, nombre) del título «Formato: 22807843 - HOJA DE EVOLUCION …» visible, o None."""
        try:
            r = self._fr().evaluate(_js(_JS_DET + "const t = titulo(); return t ? t.innerText : null;"), {"grid": GRID_FORM})
        except Exception:  # noqa: BLE001  (la página está cambiando)
            return None
        m = re.match(r"\s*formato\s*:\s*(\d+)\s*-?\s*(.*)", r or "", re.I | re.S)
        return (m.group(1), m.group(2).strip()) if m else None

    def _esperar_detalle(self, numero, antes=None, ms=20000):
        """Espera el panel «Detalle del Formato» del formato elegido (su título lleva el N° de la fila). Sin N°
        conocido, espera un título distinto del que había antes."""
        for _ in range(max(1, ms // 250)):
            t = self._titulo_detalle()
            if t and ((numero and t[0] == numero) or (not numero and t != antes)):
                return True
            self.page.wait_for_timeout(250)
        return False

    def _estado(self, **kw):
        arg = {"grid": GRID_FORM, "i": None, "guardar": False, "leer": False}
        arg.update(kw)
        return self._fr().evaluate(_js(_JS_DET + _JS_ESTADO), arg)

    def _leer_formato(self):
        """Lee el «Detalle del Formato» pestaña por pestaña (clic real en cada una; solo una es visible a la vez).
        Devuelve {pestaña: {etiqueta: valor, ..., "_texto": textareas unidas}} con pestañas y etiquetas normalizadas
        (sin tildes, mayúsculas y sin signos en los bordes: «DIAGNOSTICO», «DX», «EXAMEN FISICO»…).
        Sin pestañas (otro formato) devuelve todo en una sola entrada «FORMATO» con todas las textareas."""
        est = self._estado(leer=True)
        if not est or not est["textos"]:
            campos = (est or {}).get("campos") or []
            return {"FORMATO": self._campos_a_dict(campos, self._leer_textareas())}
        res = {}
        for i, nombre in enumerate(est["textos"]):
            self._estado(guardar=True)
            est = self._estado(i=i)
            if est is None or est.get("ausente"):
                continue
            self._fr().locator('[data-kardex-tab="1"]').first.click(timeout=5000)
            activa, quieto, t0 = est["activa"], 0, time.time()
            while time.time() - t0 < 10:
                self.page.wait_for_timeout(250)
                e = self._estado()
                if e is None:
                    continue
                if e["cb"]:
                    quieto = 0
                    continue
                if e["n"] and e["nuevos"]:
                    break
                quieto += 1
                if e["n"] and activa and quieto >= 1:
                    break
                if (not e["n"] and quieto >= 6) or quieto >= 14:
                    break
            self.page.wait_for_timeout(150)
            e = self._estado(leer=True) or {"campos": []}
            tex = "\n".join(c["valor"] for c in e["campos"] if c["tag"] == "TEXTAREA" and c["valor"].strip())
            k, n = clave(nombre) or f"PESTANA {i + 1}", 2
            while k in res:
                k, n = f"{clave(nombre)} {n}", n + 1
            res[k] = self._campos_a_dict(e["campos"], tex)
        return res

    @staticmethod
    def _campos_a_dict(campos, texto):
        d = {}
        for j, c in enumerate(campos, 1):
            k, n = clave(c["etiqueta"]) or f"CAMPO {j}", 2
            base = k
            while k in d:
                k, n = f"{base} {n}", n + 1
            d[k] = c["valor"]
        d["_texto"] = texto
        return d

    def _ultimo_formato(self, filtro, preferir_usuarios=(), estructurado=False):
        """Filtra formatos, elige el más reciente (de especialistas si hay) y lo abre con 'Ver'; espera el panel
        «Detalle del Formato» con el N° de esa fila. Con estructurado=True lee las pestañas (`_leer_formato`)."""
        self._filtrar(GRID_FORM, "Formato", filtro)
        filas = self._fr().locator(f'[id^="{GRID_FORM}_DXDataRow"]')
        cand = []
        for i in range(filas.count()):
            celdas = filas.nth(i).locator("td").all_inner_texts()
            if len(celdas) >= 5:
                cand.append((i, _fecha(celdas[2]), celdas[2].strip(), celdas[4].strip(), re.sub(r"\D", "", celdas[0])))
        if not cand:
            return None
        esp = [c for c in cand if any(normalizar(u) in normalizar(c[3]) for u in preferir_usuarios)]
        elegido = max(esp or cand, key=lambda c: c[1])
        antes = self._titulo_detalle()
        fila = filas.nth(elegido[0])
        ver = fila.get_by_text("Ver", exact=True)
        (ver.first if ver.count() else fila.locator("td").last).click()   # clic real: por JS no carga
        if not self._esperar_detalle(elegido[4], antes):
            return None
        r = {"fecha": elegido[2], "usuario": elegido[3], "es_especialista": bool(esp), "formato": None}
        if estructurado:
            r["formato"] = self._leer_formato()
            r["texto"] = "\n".join(v.get("_texto", "") for v in r["formato"].values() if v.get("_texto"))
            return r
        for _ in range(40):                       # órdenes: texto completo (el contenido llega por callback)
            txt = self._leer_textareas()
            if txt.strip():
                r["texto"] = txt
                return r
            self.page.wait_for_timeout(500)
        return None

    @staticmethod
    def _interpretar_formato(formato, texto, fecha, medico):
        """dx / evolución / plan a partir de las pestañas leídas. Lo que no se pueda sacar de las pestañas
        (formato sin ellas, sin campo DX…) se saca del texto completo como siempre (`interpretar_evolucion`)."""
        base = interpretar_evolucion(texto, fecha, medico)
        pest = lambda *nombres: next((formato[n] for n in nombres if n in formato), None)  # noqa: E731
        diag, ana, pla = pest("DIAGNOSTICO"), pest("ANALISIS"), pest("PLAN")
        sin, exa = pest("SINTOMAS DESCRITOS"), pest("EXAMEN FISICO")
        txt = lambda d: (d or {}).get("_texto", "")  # noqa: E731
        dx = base["dx"]
        if diag and "DX" in diag:
            dx = extraer_dx(diag["DX"])
        evolucion = base["evolucion"]
        if ana is not None or sin is not None or exa is not None:
            partes = [txt(ana)] if txt(ana).strip() else [txt(sin), txt(exa)]
            evolucion, _ = construir_evolucion(partes, fecha, medico, otros=[v.get("_texto", "") for v in formato.values()])
        plan = base["plan"]
        if pla is not None:
            plan = en_renglones(re.sub(r"^\s*PLAN\b\s*[:\-]?", "", txt(pla), flags=re.I).strip()).upper()
        return {"dx": dx, "evolucion": evolucion, "plan": plan}

    def detalle(self, p):
        """Rellena dx/evolución/tratamiento de p. Devuelve p."""
        try:
            if not self._atender(p):
                p.aviso = "No pude abrir su historia desde la Agenda (no encontré «Atender»)."
                return p
            esp = self.cfg.get("especialistas", [])
            ev = self._ultimo_formato("HOJA DE EVOLUCION", esp, estructurado=True)
            if not ev:
                p.aviso = "No encontré hoja de evolución."
                self.diagnostico("sin-evolucion-" + p.nombre.split()[0])
                return p
            if not ev["es_especialista"]:
                p.aviso = f"La hoja más reciente no es de un especialista de la lista ({ev['usuario']})."
            fecha = ev["fecha"].split(" ")[0]
            info = self._interpretar_formato(ev["formato"], ev["texto"], fecha, ev["usuario"])
            p.fecha, p.medico = ev["fecha"], ev["usuario"]
            p.dx, p.evolucion = info["dx"], info["evolucion"]
            ordenes = []
            try:
                self._recargar()
                self._fr().wait_for_selector(f"#{GRID_FORM}")
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
