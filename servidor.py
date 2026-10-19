"""Servidor HTTP local (solo librería estándar): sirve ui/ y la API JSON que usa la interfaz."""
import json
import mimetypes
import secrets
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import demo as modulo_demo
import flujo
import navegador
from comparar import emparejar
from errores import Cancelado, ErrorApp

VERSION = "2.0.0"
MAX_CUERPO = 2_000_000
MARCADOR = ("<!doctype html><html lang=\"es\"><meta charset=\"utf-8\"><title>Actualizar Kardex</title>"
            "<body><p>Falta ui/index.html (la interfaz).</p></body></html>")


def carpeta_ui():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "ui"


class Servidor:
    """Estado de la app (en memoria) + servidor HTTP. Una sola tarea a la vez."""

    def __init__(self, demo=False, puerto=0, token=None, ui_dir=None, abrir=None):
        self.demo = demo
        self.backend = modulo_demo.Demo() if demo else flujo
        self.token = token or secrets.token_urlsafe(24)
        self.ui_dir = Path(ui_dir) if ui_dir else carpeta_ui()
        self.abrir_url = abrir or navegador.abrir
        self.cfg = flujo.cargar_config()
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.salir = threading.Event()
        self.tarea = None
        self.ultima = None
        self.progreso = {"actual": 0, "total": 0, "paciente": ""}
        self.registro = deque(maxlen=200)
        self.sistema, self.kardex, self.acciones = None, [], []   # acciones: [(id, Accion)]
        self.fecha = ""
        self.escritura = None
        self.error = None
        self.n = 0
        self.ultima_api = time.monotonic()
        self._nav = (0.0, {})
        self._cache_res = None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", puerto), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = self
        self.puerto = self.httpd.server_address[1]
        self._hilo = None

    # ------------------------------------------------------------ ciclo de vida
    @property
    def url(self):
        return f"http://127.0.0.1:{self.puerto}/?t={self.token}"

    def iniciar(self):
        self._hilo = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self._hilo.start()

    def detener(self):
        self.salir.set()
        self.cancel.set()
        try:
            self.httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.httpd.server_close()

    def inactivo(self, segundos):
        with self.lock:
            return self.tarea is None and time.monotonic() - self.ultima_api > segundos

    # ------------------------------------------------------------ registro y estado
    def log(self, msg):
        with self.lock:
            for linea in str(msg).splitlines() or [""]:
                self.registro.append(f"{datetime.now():%H:%M}  {linea}")

    def _navegadores(self):
        t, v = self._nav
        if time.monotonic() - t > 10:
            v = {n: bool(r) for n, r in navegador.detectar().items()}
            self._nav = (time.monotonic(), v)
        return v

    def _resultado(self):
        if self.sistema is None:
            return None
        clave = (id(self.sistema), id(self.kardex), self.fecha, tuple(aid for aid, _ in self.acciones))
        if self._cache_res and self._cache_res[0] == clave:
            return self._cache_res[1]
        res = self._construir_resultado()
        self._cache_res = (clave, res)
        return res

    def _construir_resultado(self):
        id_s = {id(p): f"s{i}" for i, p in enumerate(self.sistema)}
        id_k = {id(f): f"k{i}" for i, f in enumerate(self.kardex)}
        por_nombre = {p.nombre: p for p in self.sistema}
        par_k, par_s = {}, {}          # id de kardex <-> id de sistema (mismo paciente)
        for f in self.kardex:
            nom = emparejar(f.nombre, por_nombre.keys())
            if nom and id(por_nombre[nom]) not in par_s:
                par_k[id(f)], par_s[id(por_nombre[nom])] = id_s[id(por_nombre[nom])], id_k[id(f)]
        return {
            "fecha": self.fecha,
            "sistema": [{"id": f"s{i}", "nombre": p.nombre, "habitacion": p.habitacion, "medico": p.medico,
                         "fecha": p.fecha, "dx": p.dx, "id_kardex": par_s.get(id(p))}
                        for i, p in enumerate(self.sistema)],
            "kardex": [{"id": f"k{i}", "servicio": f.servicio, "nombre": f.nombre, "habitacion": f.habitacion,
                        "dx": f.dx, "id_sistema": par_k.get(id(f))}
                       for i, f in enumerate(self.kardex)],
            "acciones": [{"id": aid, "tipo": a.tipo, "paciente": a.paciente, "servicio": a.servicio,
                          "habitacion": a.habitacion, "campo": a.campo, "detalle": a.detalle,
                          "id_sistema": id_s.get(id(a.sis)), "id_kardex": id_k.get(id(a.fila)),
                          "actual": a.actual, "nuevo": a.nuevo, "automatica": a.automatica,
                          "marcada": a.marcada} for aid, a in self.acciones],
        }

    def estado(self):
        with self.lock:
            return {
                "version": VERSION, "demo": self.demo,
                "config": dict(self.cfg),
                "navegadores": self._navegadores(),
                "sesion_guardada": bool(self.backend.sesion_guardada(self.cfg)),
                "credenciales": bool(self.backend.credenciales_ok()),
                "tarea": {"tipo": self.tarea} if self.tarea else None,
                "ultima": dict(self.ultima) if self.ultima else None,
                "progreso": dict(self.progreso),
                "registro": list(self.registro),
                "resultado": self._resultado(),
                "escritura": self.escritura,
                "error": self.error,
            }

    # ------------------------------------------------------------ tareas
    def lanzar(self, tipo, trabajo, al_terminar=None):
        """Arranca la tarea en un hilo. False si ya hay otra en curso."""
        with self.lock:
            if self.tarea:
                return False
            self.tarea, self.error = tipo, None
            self.cancel.clear()
            if tipo == "escribir":
                self.escritura = None
            if tipo == "analizar":
                self.progreso = {"actual": 0, "total": 0, "paciente": ""}
        threading.Thread(target=self._correr, args=(tipo, trabajo, al_terminar), daemon=True).start()
        return True

    def _correr(self, tipo, trabajo, al_terminar):
        fin, error, res = "ok", None, None
        try:
            res = trabajo()
        except Cancelado:
            fin = "cancelado"
            self.log("Análisis cancelado.")
        except ErrorApp as e:
            fin, error = "error", {"codigo": e.codigo, "mensaje": e.mensaje}
            self.log(f"Error: {e.mensaje}")
        except Exception as e:  # noqa: BLE001
            fin, error = "error", {"codigo": "otro", "mensaje": str(e) or e.__class__.__name__}
            self.log(f"Error: {error['mensaje']}")
        with self.lock:
            if fin == "ok" and al_terminar:
                try:
                    al_terminar(res)
                except Exception as e:  # noqa: BLE001
                    fin, error = "error", {"codigo": "otro", "mensaje": str(e) or e.__class__.__name__}
            self.error = error
            self.n += 1
            self.ultima = {"n": self.n, "tipo": tipo, "fin": fin}
            self.tarea = None

    def _progreso(self, i, n, nombre):
        with self.lock:
            self.progreso = {"actual": i, "total": n, "paciente": nombre}

    def tarea_sesion(self):
        cfg = dict(self.cfg)
        return self.lanzar("sesion", lambda: self.backend.iniciar_sesion(cfg, self.log))

    def tarea_analizar(self):
        cfg = dict(self.cfg)

        def trabajo():
            return self.backend.analizar(cfg, self.log, self._progreso, self.cancel.is_set)

        def listo(res):
            sistema, kardex, acciones = res
            self.sistema, self.kardex = sistema, kardex
            self.acciones = [(f"a{i}", a) for i, a in enumerate(acciones)]
            self.fecha = f"{datetime.now():%d/%m/%Y %H:%M}"
            self.escritura = None
            auto = sum(1 for a in acciones if a.automatica)
            self.log(f"Análisis terminado: {auto} celdas por actualizar, {len(acciones) - auto} avisos a revisar a mano.")
        return self.lanzar("analizar", trabajo, listo)

    def tarea_escribir(self, elegidas):
        cfg = dict(self.cfg)

        def listo(res):
            escritas, omitidas = res
            ids = {id(a): aid for aid, a in self.acciones}
            self.escritura = {
                "escritas": [{"id": ids.get(id(a), ""), "paciente": a.paciente, "campo": a.campo} for a in escritas],
                "omitidas": [{"id": ids.get(id(a), ""), "paciente": a.paciente, "campo": a.campo, "motivo": m}
                             for a, m in omitidas]}
            hechas = {id(a) for a in escritas}
            self.acciones = [(aid, a) for aid, a in self.acciones if id(a) not in hechas]
        return self.lanzar("escribir", lambda: self.backend.aplicar(cfg, elegidas, self.log), listo)

    # ------------------------------------------------------------ operaciones de la API
    def guardar_config(self, datos):
        """Valida y guarda un cambio parcial de configuración. Lanza ValueError si es inválido."""
        nuevo = {}
        for k in ("url_kardex", "url_agenda"):
            if k in datos:
                if not isinstance(datos[k], str):
                    raise ValueError(f"{k} debe ser texto")
                v = datos[k].strip()
                if not v.lower().startswith(("http://", "https://")):
                    # además evita que un valor tipo «--opción» llegue como argumento al navegador
                    raise ValueError("El enlace debe empezar por http:// o https://")
                nuevo[k] = v
        if "navegador" in datos:
            if datos["navegador"] not in navegador.NOMBRES:
                raise ValueError("navegador debe ser «chrome» o «brave»")
            nuevo["navegador"] = datos["navegador"]
        if "especialistas" in datos:
            esp = datos["especialistas"]
            if not isinstance(esp, list) or not all(isinstance(e, str) and e.strip() for e in esp):
                raise ValueError("especialistas debe ser una lista de textos no vacíos")
            nuevo["especialistas"] = [e.strip() for e in esp]
        with self.lock:
            self.cfg.update(nuevo)
            flujo.guardar_config(self.cfg)
            return dict(self.cfg)

    def guardar_credenciales(self, contenido):
        try:
            datos = json.loads(contenido) if isinstance(contenido, str) else None
        except ValueError:
            datos = None
        if not isinstance(datos, dict) or not any(isinstance(datos.get(k), dict) for k in ("installed", "web")):
            raise ValueError("El archivo no es un credentials.json de Google (falta «installed» o «web»).")
        carpeta = flujo.carpeta_datos()
        (carpeta / "credentials.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            (carpeta / "token.json").unlink()      # el permiso anterior era de otro cliente
        except FileNotFoundError:
            pass

    def quitar_credenciales(self):
        carpeta = flujo.carpeta_datos()
        for nombre in ("credentials.json", "token.json"):
            try:
                (carpeta / nombre).unlink()
            except FileNotFoundError:
                pass

    def abrir(self, que):
        with self.lock:
            url, pref = self.cfg["url_kardex" if que == "kardex" else "url_agenda"], self.cfg.get("navegador", "chrome")
        if self.demo:
            self.log(f"Modo demostración: no abro {que}.")
            return
        self.abrir_url(url, pref)


class _Handler(BaseHTTPRequestHandler):
    server_version = "ActualizarKardex"
    timeout = 60

    def log_message(self, *_):      # sin ruido (la app puede correr sin consola)
        pass

    @property
    def app(self):
        return self.server.app

    # ------------------------------------------------------------ utilidades
    def _enviar(self, codigo, cuerpo, tipo):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, codigo, obj):
        self._enviar(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _fallo(self, estado, mensaje, **extra):
        self._json(estado, {"ok": False, "mensaje": mensaje, **extra})

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{self.app.puerto}", f"localhost:{self.app.puerto}")

    def _permitido(self, api):
        if not self._host_ok():
            self._fallo(403, "Host no permitido")
            return False
        if api:
            if not secrets.compare_digest((self.headers.get("X-Token") or "").encode(), self.app.token.encode()):
                self._fallo(403, "Token inválido")
                return False
            self.app.ultima_api = time.monotonic()
        return True

    def _cuerpo(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_CUERPO:
            raise ValueError("Cuerpo demasiado grande")
        if n == 0:
            return {}
        datos = json.loads(self.rfile.read(n).decode("utf-8"))
        if not isinstance(datos, dict):
            raise ValueError("Se esperaba un objeto JSON")
        return datos

    # ------------------------------------------------------------ GET
    def do_GET(self):
        ruta = self.path.split("?", 1)[0]
        api = ruta.startswith("/api/")
        if not self._permitido(api):
            return
        if api:
            if ruta == "/api/estado":
                return self._json(200, self.app.estado())
            return self._fallo(404, "No existe")
        self._estatico(ruta)

    def _estatico(self, ruta):
        rel = "index.html" if ruta in ("", "/") else ruta.lstrip("/")
        base = self.app.ui_dir.resolve()
        try:
            f = (base / rel).resolve()
            f.relative_to(base)
            ok = f.is_file()
        except (ValueError, OSError):
            ok = False
        if not ok:
            if rel == "index.html":
                return self._enviar(200, MARCADOR.encode("utf-8"), "text/html; charset=utf-8")
            return self._fallo(404, "No existe")
        tipo = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        self._enviar(200, f.read_bytes(), tipo)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        ruta = self.path.split("?", 1)[0]
        if not self._permitido(True):
            return
        try:
            datos = self._cuerpo()
        except (ValueError, UnicodeDecodeError) as e:
            return self._fallo(400, f"Solicitud inválida: {e}")
        accion = {
            "/api/config": self._config, "/api/sesion": self._sesion, "/api/analizar": self._analizar,
            "/api/cancelar": self._cancelar, "/api/escribir": self._escribir, "/api/abrir": self._abrir,
            "/api/credenciales": self._credenciales, "/api/credenciales/quitar": self._quitar,
            "/api/salir": self._salir,
        }.get(ruta)
        if not accion:
            return self._fallo(404, "No existe")
        accion(datos)

    def _ocupado(self):
        self._fallo(409, "Ya hay una tarea en curso")

    def _config(self, d):
        try:
            self._json(200, {"ok": True, "config": self.app.guardar_config(d)})
        except ValueError as e:
            self._fallo(400, str(e))

    def _sesion(self, _):
        self._json(200, {"ok": True}) if self.app.tarea_sesion() else self._ocupado()

    def _analizar(self, _):
        self._json(200, {"ok": True}) if self.app.tarea_analizar() else self._ocupado()

    def _cancelar(self, _):
        self.app.cancel.set()
        self._json(200, {"ok": True})

    def _escribir(self, d):
        ids = d.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            return self._fallo(400, "ids debe ser una lista de textos")
        app = self.app
        if not app.backend.credenciales_ok():
            return self._fallo(400, "Faltan las credenciales de Google. Cárgalas en Ajustes.", codigo="credenciales")
        with app.lock:
            if app.tarea:
                return self._ocupado()
            quiero = set(ids)
            elegidas = [a for aid, a in app.acciones if aid in quiero and a.automatica]
        if not elegidas:
            return self._fallo(400, "No hay actualizaciones válidas para escribir")
        self._json(200, {"ok": True}) if app.tarea_escribir(elegidas) else self._ocupado()

    def _abrir(self, d):
        if d.get("que") not in ("kardex", "agenda"):
            return self._fallo(400, "«que» debe ser «kardex» o «agenda»")
        self.app.abrir(d["que"])
        self._json(200, {"ok": True})

    def _credenciales(self, d):
        try:
            self.app.guardar_credenciales(d.get("contenido"))
        except ValueError as e:
            return self._fallo(400, str(e), codigo="credenciales")
        self._json(200, {"ok": True})

    def _quitar(self, _):
        self.app.quitar_credenciales()
        self._json(200, {"ok": True})

    def _salir(self, _):
        self._json(200, {"ok": True})
        self.app.salir.set()
        threading.Thread(target=self.app.detener, daemon=True).start()
