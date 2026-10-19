"""Actualizar Kardex — arranca el servidor local y abre la interfaz en Chrome o Brave."""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime

import flujo
import navegador

INACTIVIDAD = 180   # segundos sin peticiones /api/ (y sin tarea) antes de apagarse


def registrar(msg):
    """Registro técnico en registro-app.txt (nunca datos de pacientes)."""
    try:
        with open(flujo.carpeta_datos() / "registro-app.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except OSError:
        pass


def _instancia_viva(archivo):
    """URL de la instancia que ya está corriendo, o None."""
    try:
        d = json.loads(archivo.read_text(encoding="utf-8"))
        req = urllib.request.Request(f"http://127.0.0.1:{int(d['puerto'])}/api/estado",
                                     headers={"X-Token": d["token"]})
        with urllib.request.urlopen(req, timeout=2) as r:
            if r.status == 200:
                return f"http://127.0.0.1:{int(d['puerto'])}/?t={d['token']}"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Actualizar Kardex")
    ap.add_argument("--demo", action="store_true", help="datos ficticios, sin navegador de automatización ni red")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir la interfaz (solo imprime la dirección)")
    ap.add_argument("--puerto", type=int, default=0, help="puerto fijo (por defecto uno libre)")
    args = ap.parse_args(argv)

    cfg = flujo.cargar_config()
    archivo = flujo.carpeta_datos() / ("instancia-demo.json" if args.demo else "instancia.json")
    previa = _instancia_viva(archivo)
    if previa:
        registrar("Ya había una instancia; se reabre su interfaz.")
        if not args.no_abrir:
            navegador.abrir(previa, cfg["navegador"], app=True)
        return 0

    from servidor import Servidor
    try:
        srv = Servidor(demo=args.demo, puerto=args.puerto)
    except OSError as e:
        registrar(f"No pude abrir el puerto: {e}")
        return 1
    srv.iniciar()
    archivo.write_text(json.dumps({"puerto": srv.puerto, "token": srv.token, "pid": os.getpid()}), encoding="utf-8")
    registrar(f"Servidor en el puerto {srv.puerto}{' (demo)' if args.demo else ''}")
    if sys.stdout:
        print(srv.url, flush=True)
    if not args.no_abrir:
        navegador.abrir(srv.url, cfg["navegador"], app=True)
    try:
        while not srv.salir.wait(1):
            if srv.inactivo(INACTIVIDAD):
                registrar("Sin actividad: se apaga.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        srv.detener()
        try:
            archivo.unlink()
        except OSError:
            pass
        registrar("Cerrada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
