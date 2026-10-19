"""Localiza un Chromium para las pruebas con navegador (se saltan si no hay playwright o Chromium)."""
import glob
import os

# Se lee al importar: conftest borra KARDEX_CHROME para cada prueba.
_FORZADO = os.environ.get("KARDEX_CHROME")


def ruta_chromium():
    """Ruta de un Chromium utilizable, o None. No usa el Chrome del sistema (en Windows no corre nada)."""
    if _FORZADO and os.path.isfile(_FORZADO):
        return _FORZADO
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    cands = []
    if base:
        cands.append(os.path.join(base, "chromium"))
        cands += sorted(glob.glob(os.path.join(base, "chromium-*", "chrome-linux", "chrome")), reverse=True)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            cands.append(pw.chromium.executable_path)
    except Exception:  # noqa: BLE001
        return None
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def disponible():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return None
    return ruta_chromium()
