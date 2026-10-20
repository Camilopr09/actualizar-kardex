"""Guarda las credenciales de Hospital Office cifradas, solo para el usuario actual de Windows.

* Windows: DPAPI (CryptProtectData / CryptUnprotectData, alcance del usuario actual). Otra persona,
  u otro computador, no puede descifrar el archivo.
* Fuera de Windows (SOLO desarrollo y pruebas): se usa base64, que OFUSCA pero NO protege nada.
  No uses este respaldo con claves reales.

La clave nunca se escribe en el registro ni en texto plano en disco; este módulo no registra nada.
Archivo: <carpeta de datos>/hospital.bin  (JSON {usuario, clave} cifrado).
"""
import base64
import json
import sys
from pathlib import Path

NOMBRE_ARCHIVO = "hospital.bin"
_PREFIJO_WIN = b"KDPAPI1:"
_PREFIJO_B64 = b"KB64DEV:"
_ES_WINDOWS = sys.platform.startswith("win")


# ------------------------------------------------------------------ cifrado
def _dpapi(funcion, datos):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(datos, len(datos))
    entrada = Blob(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    salida = Blob()
    if funcion == "proteger":
        ok = crypt32.CryptProtectData(ctypes.byref(entrada), "Actualizar Kardex", None, None, None, 0,
                                      ctypes.byref(salida))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida))
    if not ok:
        raise OSError("DPAPI no pudo procesar los datos")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(salida.pbData, ctypes.c_void_p))


def cifrar(datos: bytes) -> bytes:
    if _ES_WINDOWS:
        return _PREFIJO_WIN + _dpapi("proteger", datos)
    return _PREFIJO_B64 + base64.b64encode(datos)


def descifrar(blob: bytes) -> bytes:
    if blob.startswith(_PREFIJO_WIN) and _ES_WINDOWS:
        return _dpapi("desproteger", blob[len(_PREFIJO_WIN):])
    if blob.startswith(_PREFIJO_B64):
        return base64.b64decode(blob[len(_PREFIJO_B64):])
    raise ValueError("Formato de credenciales no reconocido")


# ------------------------------------------------------------------ credenciales de Hospital Office
def _archivo(carpeta):
    return Path(carpeta) / NOMBRE_ARCHIVO


def guardar_hospital(carpeta, usuario, clave):
    """Guarda (cifrado) usuario y clave. ValueError si alguno está vacío."""
    usuario = (usuario or "").strip() if isinstance(usuario, str) else ""
    if not usuario or not isinstance(clave, str) or not clave:
        raise ValueError("Escribe el usuario y la contraseña de Hospital Office.")
    crudo = json.dumps({"usuario": usuario, "clave": clave}, ensure_ascii=False).encode("utf-8")
    _archivo(carpeta).write_bytes(cifrar(crudo))


def leer_hospital(carpeta):
    """{'usuario', 'clave'} o None si no hay nada guardado o no se puede descifrar."""
    try:
        datos = json.loads(descifrar(_archivo(carpeta).read_bytes()).decode("utf-8"))
        if isinstance(datos, dict) and datos.get("usuario") and datos.get("clave"):
            return {"usuario": str(datos["usuario"]), "clave": str(datos["clave"])}
    except (OSError, ValueError):
        pass
    return None


def quitar_hospital(carpeta):
    try:
        _archivo(carpeta).unlink()
    except FileNotFoundError:
        pass
