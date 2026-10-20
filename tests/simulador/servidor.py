"""Simulador mínimo de Hospital Office y del kardex exportado (solo librería estándar, datos inventados).

Imita lo que describe sistema.py:
  * /Agenda.aspx: grillas ctl00_cph1_cbpPanel1_grdPendientes / grdAtendidos (filas «<grid>_DXDataRow<N>»,
    Habitación en la columna 4, enlace «Atender»), modos «Urgencias» / «Hospitalización», casilla
    «Últimas 24 horas» y un stub de ASPxClientControl.GetControlCollection().elements[id]
    con AutoFilterByColumn («empieza con») e InCallback().
  * /HistoriaClinica.aspx: grilla ctl00_cph1_ASPxRoundPanel2_grdFormatos (N°, Formato, Fecha hora, Estado,
    Usuario, Ver); «Ver» llena los textareas de «Detalle del Formato» tras un pequeño retardo.
  * /kardex: kardex exportado (HTML de Google Docs, simplificado).
  * Inicio de sesión fiel a lo reportado: /Login.aspx (usuario, contraseña, botón «Ingresar») pone una cookie de
    sesión (sin expires); tras entrar lleva a /Inicio.aspx, con el botón «Menu Principal» -> /Menu.aspx, con el
    enlace «Atención de Pacientes» -> /Agenda.aspx. Agenda.aspx sin cookie redirige a login y, sin haber pasado por
    el menú en esa sesión, no trae las grillas. La sesión puede «vencer» tras N peticiones protegidas.
"""
import html
import json
import threading
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USUARIO = "medico.prueba"
CLAVE = "Clave-Inventada-123"

GRID_PEND = "ctl00_cph1_cbpPanel1_grdPendientes"
GRID_ATEN = "ctl00_cph1_cbpPanel1_grdAtendidos"
GRID_FORM = "ctl00_cph1_ASPxRoundPanel2_grdFormatos"

# --------------------------------------------------------------------------- datos inventados
# id, nombre, habitación, modo, pendiente(True)/atendido, visible con «Últimas 24 horas»
PACIENTES = [
    (1, "ALVARADO RUIZ PEDRO PABLO", "2-01", "Hospitalización", True, True),
    (2, "BENAVIDES LUNA SOFIA", "2-02", "Hospitalización", True, True),
    (3, "CORREA MEJIA TOMAS", "U-03", "Urgencias", False, True),
    (4, "DUQUE SALAS MARIA ELENA", "3-04", "Hospitalización", False, True),
    (5, "ESCOBAR TRUJILLO IVAN", "U-07", "Urgencias", False, False),      # solo sin el filtro de 24 h
    (6, "GUTIERREZ OSORIO LAURA", "4-08", "Hospitalización", True, True),  # habitación distinta a la del kardex
]

EVOL = "HOJA DE EVOLUCION"
ORDEN = "ORDEN MEDICA"


def _nota(dx, plan):
    return (f"-MEDICINA INTERNA-\nPTE CON DX: {dx}\nEXAMEN FISICO: ALERTA, SIN DOLOR\n"
            f"ANALISIS: EVOLUCION FAVORABLE\nPLAN {plan}")


# id paciente -> lista de formatos (formato, fecha hora, estado, usuario, detalle)
FORMATOS = {
    1: [(EVOL, "18/10/2026 07:00", "Finalizado", "DAZA PEREZ JUAN",
         _nota("1. COLECISTITIS AGUDA", "1. NVO 2. CEFAZOLINA 1 G IV C/8H")),
        (EVOL, "19/10/2026 09:10", "Finalizado", "LOPEZ RUIZ ANA (ENFERMERIA)",
         _nota("1. OTRO DX NO ESPECIALISTA", "1. NO DEBE LEERSE")),
        (EVOL, "19/10/2026 06:30", "Finalizado", "DAZA PEREZ JUAN",
         _nota("1. COLECISTITIS AGUDA 2. HTA", "1. DIETA LIQUIDA 2. CEFAZOLINA 1 G IV C/8H 3. OMEPRAZOL 40 MG IV C/24H")),
        (ORDEN, "19/10/2026 06:35", "Finalizado", "DAZA PEREZ JUAN",
         "DIETA LIQUIDA\nFórmula #1\n1) CEFAZOLINA 1G Cantidad: 3 Dosis: 1 g IV c/8h\n")],
    2: [(EVOL, "19/10/2026 07:20", "Finalizado", "FABIAN GOMEZ LUIS",
         _nota("NEUMONIA ADQUIRIDA EN LA COMUNIDAD", "IGUAL MANEJO")),
        (ORDEN, "19/10/2026 07:25", "Finalizado", "FABIAN GOMEZ LUIS",
         "DIETA BLANDA\n1) CEFTRIAXONA 2 G Cantidad: 2 Dosis: 2 g IV c/24h\n2) ENOXAPARINA 40 MG Cantidad: 1 Dosis: 40 mg SC c/24h\n")],
    3: [(EVOL, "19/10/2026 08:00", "Finalizado", "EMILIANI RUEDA CARLOS",
         _nota("PIELONEFRITIS AGUDA", "1. DIETA BLANDA 2. CIPROFLOXACINO 400 MG IV C/12H"))],
    4: [(EVOL, "19/10/2026 05:40", "Finalizado", "TORRES NIETO ROSA (AUXILIAR)",
         _nota("1. CELULITIS DE MIEMBRO INFERIOR", "1. DIETA NORMAL"))],
    5: [(EVOL, "19/10/2026 06:50", "Finalizado", "DAZA PEREZ JUAN", _nota("1. PANCREATITIS AGUDA", "1. NVO"))],
    6: [(EVOL, "19/10/2026 08:30", "Finalizado", "FABIAN GOMEZ LUIS",
         _nota("1. APENDICITIS AGUDA COMPLICADA", "1. DIETA LIQUIDA 2. CEFAZOLINA 1 G IV C/8H"))],
}

# Kardex exportado: (servicio, [(nombre, habitación, dx, evolución, tratamiento)])
KARDEX = [
    ("PISO 2", [
        ("PEDRO ALVARADO", "2-01", "COLECISTITIS AGUDA", "17/10/2026 DAZA: EVOLUCION VIEJA", "DIETA LIQUIDA"),
        ("SOFIA BENAVIDES LUNA", "2-02", "NEUMONIA ADQUIRIDA EN LA COMUNIDAD", "ev", "NVO\nCEFTRIAXONA 2 G — 2 g IV c/24h"),
    ]),
    ("URGENCIAS", [
        ("TOMAS CORREA MEJIA", "U-03", "PIELONEFRITIS AGUDA",
         "19/10/2026 - DR. EMILIANI RUEDA CARLOS (MEDICINA INTERNA)\nEXAMEN FISICO: ALERTA, SIN DOLOR ANALISIS: EVOLUCION FAVORABLE",
         "1. DIETA BLANDA 2. CIPROFLOXACINO 400 MG IV C/12H"),     # igual a lo del sistema: sin acciones
        ("ELSA FIGUEROA PARDO", "U-09", "HERNIA INGUINAL", "ev", "DIETA"),     # ya no está en el sistema
    ]),
    ("PISO 3", [
        ("MARIA DUQUE SALAS", "3-04", "CELULITIS DE MIEMBRO INFERIOR", "ev", "DIETA NORMAL"),
    ]),
    ("PISO 4", [
        ("LAURA GUTIERREZ OSORIO", "4-05", "APENDICITIS AGUDA COMPLICADA", "ev", "x"),
    ]),
]


# --------------------------------------------------------------------------- páginas
STUB = """
window.__grids = {};
window.ASPxClientControl = { GetControlCollection: function () { return { elements: window.__grids }; } };
function crearGrilla(id, columnas, filas, pintar) {
  var estado = { filtro: null, enCallback: false };
  var g = {
    InCallback: function () { return estado.enCallback; },
    AutoFilterByColumn: function (col, texto) {
      estado.enCallback = true;
      setTimeout(function () {
        estado.filtro = texto ? { col: col, texto: String(texto).toLowerCase() } : null;
        pintar(); estado.enCallback = false;
      }, 150);
    },
    visibles: function () {
      return filas().filter(function (f) {
        if (!estado.filtro) return true;
        var i = columnas.indexOf(estado.filtro.col);
        return String(f[i]).toLowerCase().indexOf(estado.filtro.texto) === 0;   // «empieza con»
      });
    }
  };
  window.__grids[id] = g;
  return g;
}
"""

def pagina_login(error="", usuario="", clave=""):
    """Si hay error, repite lo escrito (la clave también: un sistema descuidado haría eso)."""
    return ("""<!doctype html><html><head><meta charset="utf-8"><title>Iniciar sesión</title></head><body>
<h1>Hospital Office</h1>%s<form method="post" action="/Login.aspx"><label>Usuario <input name="u" type="text" value="%s"></label>
<label>Contraseña <input name="p" type="password" value="%s"></label><button type="submit">Ingresar</button></form></body></html>"""
            % (f'<p class="err">{html.escape(error)}</p>' if error else "",
               html.escape(usuario, quote=True), html.escape(clave, quote=True)))


LOGIN = pagina_login()

INICIO = """<!doctype html><html><head><meta charset="utf-8"><title>Inicio</title></head><body>
<h1>Bienvenido a Hospital Office</h1>
<button type="button" onclick="location.href='/Menu.aspx'">Menu Principal</button></body></html>"""

MENU = """<!doctype html><html><head><meta charset="utf-8"><title>Menú</title></head><body>
<h1>Menú</h1><ul><li><a href="/Otro.aspx">Facturación</a></li>
<li><a href="/Agenda.aspx">Atención de Pacientes</a></li></ul></body></html>"""

SIN_MENU = "<html><body><h1>Seleccione una opción del menú</h1></body></html>"


def pagina_agenda(datos):
    return """<!doctype html><html><head><meta charset="utf-8"><title>Agenda</title></head><body>
<h1>Agenda médica</h1>
<div id="modos"><a href="#" id="m1" class="modo" data-m="Urgencias">Urgencias</a> |
<a href="#" id="m2" class="modo" data-m="Hospitalización">Hospitalización</a></div>
<div><input type="checkbox" id="chk24" checked><label for="chk24">Últimas 24 horas</label></div>
<h2>Pendientes</h2>
<table id="%(pend)s"><tr id="%(pend)s_DXHeadRow"><th>Paciente</th><th>Documento</th><th>Hora</th><th>Médico</th><th>Habitación</th><th></th></tr>
<tr id="%(pend)s_DXFilterRow"><td></td></tr></table>
<h2>Atendidos</h2>
<table id="%(aten)s"><tr id="%(aten)s_DXHeadRow"><th>Paciente</th><th>Documento</th><th>Hora</th><th>Médico</th><th>Habitación</th><th></th></tr>
<tr id="%(aten)s_DXFilterRow"><td></td></tr></table>
<script>%(stub)s
var DATOS = %(datos)s;           // [id, nombre, hab, modo, pendiente, reciente]
var COLS = ["Paciente", "Documento", "Hora", "Médico", "Habitación", ""];
var modo = "Hospitalización";
function filas(pend) {
  var r24 = document.getElementById("chk24").checked;
  return DATOS.filter(function (d) { return d[3] === modo && d[4] === pend && (!r24 || d[5]); })
    .map(function (d) { return [d[1], "CC " + (1000 + d[0]), "0" + d[0] + ":00", "DR. PRUEBA", d[2], d[0]]; });
}
function montar(id, pend) {
  var g = crearGrilla(id, COLS, function () { return filas(pend); }, pintar);
  function pintar() {
    var t = document.getElementById(id);
    Array.prototype.slice.call(t.querySelectorAll("tr[id*=_DXDataRow]")).forEach(function (tr) { tr.remove(); });
    g.visibles().forEach(function (f, n) {
      var tr = document.createElement("tr"); tr.id = id + "_DXDataRow" + n;
      for (var i = 0; i < 5; i++) { var td = document.createElement("td"); td.textContent = f[i]; tr.appendChild(td); }
      var td = document.createElement("td"); var a = document.createElement("a");
      a.href = "HistoriaClinica.aspx?id=" + f[5]; a.textContent = "Atender"; td.appendChild(a); tr.appendChild(td);
      t.appendChild(tr);
    });
  }
  return pintar;
}
var repintar = [montar("%(pend)s", true), montar("%(aten)s", false)];
function todo() { repintar.forEach(function (f) { f(); }); }
document.querySelectorAll(".modo").forEach(function (a) {
  a.addEventListener("click", function (ev) { ev.preventDefault(); modo = a.dataset.m; setTimeout(todo, 100); });
});
document.getElementById("chk24").addEventListener("change", function () { setTimeout(todo, 100); });
todo();
</script></body></html>""" % {"pend": GRID_PEND, "aten": GRID_ATEN, "stub": STUB, "datos": json.dumps(datos)}


def pagina_historia(pid):
    nombre = next(p[1] for p in PACIENTES if p[0] == pid)
    return """<!doctype html><html><head><meta charset="utf-8"><title>Historia clínica</title></head><body>
<h1>Historia clínica</h1><p id="quien">%(nombre)s</p>
<div id="ctl00_cph1_ASPxRoundPanel2">
<table id="%(grid)s"><tr id="%(grid)s_DXHeadRow"><th>N°</th><th>Formato</th><th>Fecha hora</th><th>Estado</th><th>Usuario</th><th>Ver</th></tr></table></div>
<h3>Detalle del Formato</h3>
<textarea id="t1" rows="6" cols="80"></textarea><textarea id="t2" rows="3" cols="80"></textarea><textarea id="t3" rows="3" cols="80"></textarea>
<script>%(stub)s
var FORMATOS = %(formatos)s;      // [formato, fecha, estado, usuario, detalle]
var COLS = ["N°", "Formato", "Fecha hora", "Estado", "Usuario", "Ver"];
var g = crearGrilla("%(grid)s", COLS, function () {
  return FORMATOS.map(function (f, i) { return [String(i + 1), f[0], f[1], f[2], f[3], "Ver", i]; });
}, pintar);
function pintar() {
  var t = document.getElementById("%(grid)s");
  Array.prototype.slice.call(t.querySelectorAll("tr[id*=_DXDataRow]")).forEach(function (tr) { tr.remove(); });
  g.visibles().forEach(function (f, n) {
    var tr = document.createElement("tr"); tr.id = "%(grid)s_DXDataRow" + n;
    for (var i = 0; i < 5; i++) { var td = document.createElement("td"); td.textContent = f[i]; tr.appendChild(td); }
    var td = document.createElement("td"); var a = document.createElement("a"); a.href = "#"; a.textContent = "Ver";
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      setTimeout(function () {                  // el detalle llega con un pequeño retardo
        document.getElementById("t1").value = FORMATOS[f[6]][4];
        document.getElementById("t2").value = ""; document.getElementById("t3").value = "";
      }, 400);
    });
    td.appendChild(a); tr.appendChild(td); t.appendChild(tr);
  });
}
pintar();
</script></body></html>""" % {"nombre": html.escape(nombre), "grid": GRID_FORM, "stub": STUB,
                              "formatos": json.dumps(FORMATOS[pid])}


def _parrafos(lineas):
    return "".join(f"<p>{html.escape(l)}</p>" for l in lineas)


def pagina_kardex():
    """Estructura real del Google Doc: fila 0 = título (colspan 7), fila 1 = encabezados,
    luego pacientes. DATOS: habitación, nombre en 1-3 renglones, vacío, edad, vacío, «CC n».
    DX empieza con «DX:» y TRATAMIENTO con «PLAN»."""
    partes = ["<html><head><style>p{margin:0}</style></head><body><h1>KARDEX MIS PX</h1>"]
    n = 0
    for servicio, filas in KARDEX:
        partes.append(f'<table><tr><td colspan="7"><p>{html.escape(servicio)} ( {len(filas)} PACIENTES)</p></td></tr>'
                      "<tr><td><p>DATOS</p></td><td><p>DX</p></td><td><p>EVOLUCIÓN</p></td><td><p>TRATAMIENTO</p></td>"
                      "<td><p>LABORATORIOS</p></td><td><p>IMÁGENES / NOTAS</p></td><td><p>PENDIENTES</p></td></tr>")
        for nombre, hab, dx, ev, trat in filas:
            n += 1
            palabras = nombre.split()
            nombre_lineas = [" ".join(palabras[i:i + 2]) for i in range(0, len(palabras), 2)]
            datos = _parrafos([hab] + nombre_lineas) + "<p></p>" + _parrafos([f"{40 + n} AÑOS"]) \
                + "<p></p>" + _parrafos([f"CC 9000{n:04d}"])
            t = _parrafos(["PLAN"] + trat.split("\n"))
            ev = ev.split("\n")
            partes.append(f"<tr><td>{datos}</td><td>{_parrafos(['DX:', dx])}</td><td>{_parrafos(ev)}</td>"
                          f"<td>{t}</td><td></td><td></td><td></td></tr>")
        partes.append("</table>")
    partes.append("</body></html>")
    return "".join(partes)


# --------------------------------------------------------------------------- servidor
class Simulador:
    """exige_login: sin cookie de sesión, Agenda/Historia/Inicio/Menú redirigen a /Login.aspx.
    agenda_requiere_menu: la Agenda solo trae las grillas si en esa sesión se pasó por /Menu.aspx.
    vence_tras: la sesión «vence» (se borran todas) al recibir esa cantidad de peticiones protegidas.
    agenda_rota_en: números de visita a la Agenda con grillas (1, 2, 3…) que devuelven una página sin grillas."""

    def __init__(self, agenda_rota_en=(), exige_login=True, agenda_requiere_menu=True, vence_tras=None):
        self.exige_login = exige_login
        self.agenda_requiere_menu = agenda_requiere_menu
        self.vence_tras = vence_tras
        self.agenda_rota_en = set(agenda_rota_en)
        self.visitas_agenda = 0
        self.protegidas = 0
        self.logins = 0
        self.sesiones = {}                  # sid -> {"menu": bool}
        self.kardex_sirve = True
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.puerto = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.puerto}"
        self._hilo = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url_agenda(self):
        return f"{self.base}/Agenda.aspx"

    @property
    def url_kardex(self):
        return f"http://localhost:{self.puerto}/kardex"

    def _handler(self):
        sim = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _html(self, cuerpo, codigo=200, cabeceras=()):
                b = cuerpo.encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                for k, v in cabeceras:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(b)

            def _redirigir(self, destino, cabeceras=()):
                self.send_response(302)
                self.send_header("Location", destino)
                self.send_header("Content-Length", "0")
                for k, v in cabeceras:
                    self.send_header(k, v)
                self.end_headers()

            def _sesion(self):
                for parte in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = parte.strip().partition("=")
                    if k == "sid" and v in sim.sesiones:
                        return sim.sesiones[v]
                return None

            def do_POST(self):
                u = urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                campos = parse_qs(self.rfile.read(n).decode("utf-8"))
                if u.path.lower() != "/login.aspx":
                    return self._html("no existe", 404)
                usuario, clave = campos.get("u", [""])[0], campos.get("p", [""])[0]
                if usuario == USUARIO and clave == CLAVE:
                    sim.logins += 1
                    sid = secrets.token_hex(8)
                    sim.sesiones[sid] = {"menu": False}
                    # cookie de sesión: sin Expires ni Max-Age (se pierde al cerrar el navegador)
                    return self._redirigir("/Inicio.aspx", [("Set-Cookie", f"sid={sid}; Path=/; HttpOnly")])
                self._html(pagina_login("Usuario o contraseña incorrectos", usuario, clave))

            def do_GET(self):
                u = urlparse(self.path)
                ruta = u.path.lower()
                if ruta == "/login.aspx":
                    return self._html(LOGIN)
                if ruta == "/kardex":
                    return self._html(pagina_kardex()) if sim.kardex_sirve else self._html("no", 404)
                if ruta in ("/inicio.aspx", "/menu.aspx", "/agenda.aspx", "/historiaclinica.aspx"):
                    sim.protegidas += 1
                    if sim.vence_tras and sim.protegidas == sim.vence_tras:
                        sim.sesiones.clear()                  # la sesión vence a mitad del análisis
                    ses = self._sesion()
                    if sim.exige_login and ses is None:
                        return self._redirigir("/Login.aspx?ReturnUrl=" + u.path)
                    ses = ses if ses is not None else {"menu": True}
                    if ruta == "/inicio.aspx":
                        return self._html(INICIO)
                    if ruta == "/menu.aspx":
                        ses["menu"] = True
                        return self._html(MENU)
                    if ruta == "/agenda.aspx":
                        if sim.agenda_requiere_menu and not ses["menu"]:
                            return self._html(SIN_MENU)
                        sim.visitas_agenda += 1
                        if sim.visitas_agenda in sim.agenda_rota_en:
                            return self._html("<html><body><h1>Error inesperado</h1></body></html>")
                        return self._html(pagina_agenda([list(p) for p in PACIENTES]))
                    try:
                        pid = int(parse_qs(u.query).get("id", ["0"])[0])
                        return self._html(pagina_historia(pid))
                    except (ValueError, StopIteration):
                        return self._html("no existe", 404)
                self._html("no existe", 404)

        return H
