"""Detección y apertura de Chrome o Brave (el navegador preferido de la persona)."""
import os
import shutil
import subprocess
import sys
import webbrowser

NOMBRES = ("chrome", "brave")

_REL_WIN = {
    "chrome": r"Google\Chrome\Application\chrome.exe",
    "brave": r"BraveSoftware\Brave-Browser\Application\brave.exe",
}
_EXE = {"chrome": "chrome.exe", "brave": "brave.exe"}
_MAC = {
    "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "brave": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
}
_COMANDOS = {
    "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
    "brave": ("brave-browser", "brave"),
}


def _registro(exe):
    """Ruta registrada en Windows (App Paths) o None."""
    try:
        import winreg
    except ImportError:
        return None
    clave = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    vistas = (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0))
    for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for vista in vistas:
            try:
                with winreg.OpenKey(raiz, clave, 0, winreg.KEY_READ | vista) as k:
                    valor, _ = winreg.QueryValueEx(k, "")
                    if valor:
                        return str(valor).strip().strip('"')
            except OSError:
                continue
    return None


def _buscar(nombre):
    if sys.platform.startswith("win"):
        cands = [_registro(_EXE[nombre])]
        for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                cands.append(os.path.join(base, _REL_WIN[nombre]))
    else:
        cands = [_MAC[nombre]] if sys.platform == "darwin" else []
        cands += [shutil.which(c) for c in _COMANDOS[nombre]]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def detectar():
    """{'chrome': ruta|None, 'brave': ruta|None}."""
    res = {n: _buscar(n) for n in NOMBRES}
    forzado = os.environ.get("KARDEX_CHROME")
    if forzado and os.path.isfile(forzado):
        res["chrome"] = forzado
    return res


def _candidatos(preferido):
    """[(nombre, ruta)] instalados, el preferido primero."""
    preferido = preferido if preferido in NOMBRES else "chrome"
    hallados = detectar()
    orden = [preferido] + [n for n in NOMBRES if n != preferido]
    return [(n, hallados[n]) for n in orden if hallados.get(n)]


def elegir(preferido):
    """(nombre, ruta) del preferido si existe; si no, el otro; si no hay, (None, None)."""
    c = _candidatos(preferido)
    return c[0] if c else (None, None)


def abrir(url, preferido, app=False):
    """Abre la URL en el navegador elegido (ventana tipo app o normal). Si ese no arranca, prueba el otro."""
    for _, ruta in _candidatos(preferido):
        try:
            subprocess.Popen([ruta, f"--app={url}"] if app else [ruta, url])
            return
        except OSError:
            continue
    webbrowser.open(url)


def registrar_webbrowser(preferido):
    """Registra el navegador elegido como «kardex» en webbrowser (para el OAuth de Google)."""
    nombre, ruta = elegir(preferido)
    if not ruta:
        return None
    webbrowser.register("kardex", None, webbrowser.BackgroundBrowser(ruta))
    return nombre
