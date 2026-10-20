"""Navegador de automatización que vive mientras vive la app.

Hospital Office guarda la sesión solo mientras la ventana está abierta, así que la ventana no se cierra al
terminar cada tarea. Playwright (API síncrona) no es seguro entre hilos: todo el trabajo con el navegador se
ejecuta en UN hilo dedicado, y las tareas llegan a él con `ejecutar(funcion, *args)`."""
import queue
import threading
from concurrent.futures import Future

from errores import Cancelado, ErrorApp

_FIN = object()


class NavegadorVivo:
    def __init__(self, carpeta, preferido=lambda: "chrome", log=lambda m: None, fabrica_playwright=None, abrir=None):
        """carpeta: Path o función sin argumentos que la devuelve; preferido: función con el navegador elegido.
        fabrica_playwright y abrir existen para las pruebas (por defecto sync_playwright y sistema.abrir_contexto)."""
        self._carpeta = carpeta
        self._preferido = preferido
        self.log = log
        self._fabrica = fabrica_playwright
        self._abrir = abrir
        self._cola = queue.Queue()
        self._lock = threading.Lock()
        self._hilo = None
        self._cerrado = False
        # solo los toca el hilo dedicado
        self._pw = None
        self._ctx = None
        self._ctx_pref = None
        self._ctx_cerrado = False

    # ------------------------------------------------------------ API (hilos de las tareas)
    def ejecutar(self, funcion, *args):
        """Corre funcion(ctx, *args) en el hilo del navegador y devuelve su resultado (o relanza su excepción)."""
        fut = Future()
        with self._lock:
            if self._cerrado:
                raise ErrorApp("navegador", "El navegador de la app ya está cerrado.")
            if self._hilo is None:
                self._hilo = threading.Thread(target=self._bucle, name="navegador-vivo", daemon=True)
                self._hilo.start()
            self._cola.put((fut, funcion, args))
        return fut.result()

    def cerrar(self, espera=30):
        """Cierra el navegador y termina el hilo (espera a la tarea en curso, si la hay)."""
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True
            hilo = self._hilo
            if hilo is not None:
                self._cola.put(_FIN)
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(espera)

    @property
    def hilo_vivo(self):
        return bool(self._hilo and self._hilo.is_alive())

    # ------------------------------------------------------------ hilo dedicado
    def _bucle(self):
        try:
            while True:
                item = self._cola.get()
                if item is _FIN:
                    break
                fut, funcion, args = item
                if not fut.set_running_or_notify_cancel():
                    continue
                try:
                    fut.set_result(self._correr(funcion, args))
                except BaseException as e:  # noqa: BLE001  (se relanza en el hilo que llamó)
                    fut.set_exception(e)
        finally:
            self._cerrar_todo()
            while True:                 # nadie debe quedarse esperando si llegó algo tras el cierre
                try:
                    item = self._cola.get_nowait()
                except queue.Empty:
                    break
                if item is not _FIN:
                    item[0].set_exception(ErrorApp("navegador", "El navegador de la app ya está cerrado."))

    def _correr(self, funcion, args):
        ctx = self._contexto()
        try:
            return funcion(ctx, *args)
        except Cancelado:
            raise
        except BaseException as e:
            if not self._sano(ctx, crear_pagina=False):
                self._soltar_contexto()
                raise ErrorApp("navegador", "Se cerró la ventana del navegador a mitad de la tarea. "
                                            "Vuelve a intentarlo: la app la abre de nuevo.") from e
            raise

    def _importar_pw(self):
        if self._pw is None:
            fabrica = self._fabrica
            if fabrica is None:
                from playwright.sync_api import sync_playwright as fabrica
            self._pw = fabrica().start()
        return self._pw

    def _contexto(self):
        pref = self._preferido()
        if self._ctx is not None:
            if pref != self._ctx_pref:
                self.log("Cambió el navegador elegido: reabro la ventana.")
                self._soltar_contexto(cerrar=True)
            elif not self._sano(self._ctx, crear_pagina=True):
                self.log("La ventana del navegador se había cerrado: la abro de nuevo.")
                self._soltar_contexto(cerrar=True)
        if self._ctx is None:
            abrir = self._abrir
            if abrir is None:
                import sistema
                abrir = sistema.abrir_contexto
            carpeta = self._carpeta() if callable(self._carpeta) else self._carpeta
            ctx = abrir(self._importar_pw(), carpeta, pref, self.log)
            self._ctx_cerrado = False
            try:
                ctx.on("close", lambda *_: setattr(self, "_ctx_cerrado", True))
            except Exception:  # noqa: BLE001
                pass
            self._ctx, self._ctx_pref = ctx, pref
        return self._ctx

    def _sano(self, ctx, crear_pagina):
        """El contexto sigue usable. Si la persona cerró todas las pestañas pero el navegador vive, abre una."""
        if ctx is not self._ctx or self._ctx_cerrado:
            return False
        try:
            if not list(ctx.pages) and crear_pagina:
                ctx.new_page()
            else:
                list(ctx.pages)
        except Exception:  # noqa: BLE001
            return False
        return True

    def _soltar_contexto(self, cerrar=False):
        ctx, self._ctx = self._ctx, None
        if ctx is not None and cerrar:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

    def _cerrar_todo(self):
        self._soltar_contexto(cerrar=True)
        pw, self._pw = self._pw, None
        if pw is not None:
            try:
                pw.stop()
            except Exception:  # noqa: BLE001
                pass
