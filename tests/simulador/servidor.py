"""Simulador mínimo de Hospital Office y del kardex exportado (solo librería estándar, datos inventados).

Imita lo que describe sistema.py:
  * /Agenda.aspx: grillas ctl00_cph1_cbpPanel1_grdPendientes / grdAtendidos (filas «<grid>_DXDataRow<N>»,
    Habitación en la columna 4, enlace «Atender»), modos «Urgencias» / «Hospitalización», casilla
    «Últimas 24 horas» y un stub de ASPxClientControl.GetControlCollection().elements[id]
    con AutoFilterByColumn («empieza con») e InCallback().
  * /HistoriaClinica.aspx: grilla ctl00_cph1_ASPxRoundPanel2_grdFormatos (N°, Formato, Fecha hora, Estado,
    Usuario, Ver); «Ver» llena los textareas de «Detalle del Formato» tras un pequeño retardo.
  * /kardex: kardex exportado (HTML de Google Docs, simplificado).
  * /Login.aspx: página de inicio de sesión.
"""
import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

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
         "19/10/2026 EMILIANI RUEDA CARLOS: EXAMEN FISICO: ALERTA, SIN DOLOR ANALISIS: EVOLUCION FAVORABLE",
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

LOGIN = """<!doctype html><html><head><meta charset="utf-8"><title>Iniciar sesión</title></head><body>
<h1>Hospital Office</h1><form method="post"><label>Usuario <input name="u" type="text"></label>
<label>Contraseña <input name="p" type="password"></label><button>Entrar</button></form></body></html>"""


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


def pagina_kardex():
    partes = ["<html><head><style>p{margin:0}</style></head><body><h1>KARDEX MIS PX</h1>"]
    for servicio, filas in KARDEX:
        partes.append(f"<p>{html.escape(servicio)}</p><table><tr><td><p>DATOS</p></td><td>DX</td><td>EVOLUCIÓN</td>"
                      "<td>TRATAMIENTO</td><td>LAB</td><td>IMG</td><td>PEND</td></tr>")
        for nombre, hab, dx, ev, trat in filas:
            t = "<br>".join(html.escape(x) for x in trat.split("\n"))
            partes.append(f"<tr><td><p>{html.escape(nombre)}</p><p>{html.escape(hab)}</p></td><td>{html.escape(dx)}</td>"
                          f"<td>{html.escape(ev)}</td><td>{t}</td><td></td><td></td><td></td></tr>")
        partes.append("</table>")
    partes.append("</body></html>")
    return "".join(partes)


# --------------------------------------------------------------------------- servidor
class Simulador:
    """modo_login: None (sesión válida), 'redirigir' (302 a /Login.aspx) o 'en_pagina' (la Agenda muestra el formulario).
    agenda_rota_en: números de visita a la Agenda (1, 2, 3…) que devuelven una página sin grillas."""

    def __init__(self, modo_login=None, agenda_rota_en=()):
        self.modo_login = modo_login
        self.agenda_rota_en = set(agenda_rota_en)
        self.visitas_agenda = 0
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

            def _html(self, cuerpo, codigo=200):
                b = cuerpo.encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urlparse(self.path)
                ruta = u.path.lower()
                if ruta == "/login.aspx":
                    return self._html(LOGIN)
                if ruta == "/kardex":
                    return self._html(pagina_kardex()) if sim.kardex_sirve else self._html("no", 404)
                if ruta == "/agenda.aspx":
                    sim.visitas_agenda += 1
                    if sim.modo_login == "redirigir":
                        self.send_response(302)
                        self.send_header("Location", "/Login.aspx?ReturnUrl=%2fAgenda.aspx")
                        self.end_headers()
                        return
                    if sim.modo_login == "en_pagina":
                        return self._html(LOGIN)
                    if sim.visitas_agenda in sim.agenda_rota_en:
                        return self._html("<html><body><h1>Error inesperado</h1></body></html>")
                    return self._html(pagina_agenda([list(p) for p in PACIENTES]))
                if ruta == "/historiaclinica.aspx":
                    try:
                        pid = int(parse_qs(u.query).get("id", ["0"])[0])
                        return self._html(pagina_historia(pid))
                    except (ValueError, StopIteration):
                        return self._html("no existe", 404)
                self._html("no existe", 404)

        return H
