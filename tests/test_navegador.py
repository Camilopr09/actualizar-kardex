import navegador


def _simular(monkeypatch, hallados):
    """hallados: rutas que «existen» (el resto no)."""
    monkeypatch.setattr(navegador, "_registro", lambda exe: None)
    monkeypatch.setattr(navegador.shutil, "which", lambda c: hallados.get(c))
    monkeypatch.setattr(navegador.os.path, "isfile", lambda r: r in hallados.values() or r in hallados)
    monkeypatch.setattr(navegador.sys, "platform", "linux")


def test_detectar_linux(monkeypatch):
    _simular(monkeypatch, {"google-chrome": "/usr/bin/google-chrome", "brave-browser": "/usr/bin/brave-browser"})
    assert navegador.detectar() == {"chrome": "/usr/bin/google-chrome", "brave": "/usr/bin/brave-browser"}


def test_detectar_ninguno(monkeypatch):
    _simular(monkeypatch, {})
    assert navegador.detectar() == {"chrome": None, "brave": None}
    assert navegador.elegir("chrome") == (None, None)


def test_detectar_windows_registro_y_rutas(monkeypatch):
    reg = r"C:\Chrome\chrome.exe"
    monkeypatch.setattr(navegador.sys, "platform", "win32")
    monkeypatch.setattr(navegador, "_registro", lambda exe: reg if exe == "chrome.exe" else None)
    monkeypatch.setenv("LOCALAPPDATA", "LOCAL")
    brave = navegador.os.path.join("LOCAL", r"BraveSoftware\Brave-Browser\Application\brave.exe")
    monkeypatch.setattr(navegador.os.path, "isfile", lambda r: r in (reg, brave))
    assert navegador.detectar() == {"chrome": reg, "brave": brave}


def test_elegir_preferido_y_respaldo(monkeypatch):
    _simular(monkeypatch, {"google-chrome": "/c", "brave": "/b"})
    assert navegador.elegir("brave") == ("brave", "/b")
    assert navegador.elegir("chrome") == ("chrome", "/c")
    assert navegador.elegir("otro") == ("chrome", "/c")
    _simular(monkeypatch, {"brave": "/b"})
    assert navegador.elegir("chrome") == ("brave", "/b")      # el preferido no está: usa el otro
    _simular(monkeypatch, {"google-chrome": "/c"})
    assert navegador.elegir("brave") == ("chrome", "/c")


def test_kardex_chrome_fuerza(monkeypatch, tmp_path):
    _simular(monkeypatch, {})
    f = tmp_path / "chrome-falso"
    f.write_text("x")
    monkeypatch.setenv("KARDEX_CHROME", str(f))
    monkeypatch.setattr(navegador.os.path, "isfile", lambda r: r == str(f))
    assert navegador.elegir("brave") == ("chrome", str(f))


def test_abrir_y_registrar(monkeypatch):
    _simular(monkeypatch, {"brave": "/b"})
    llamadas = []
    monkeypatch.setattr(navegador.subprocess, "Popen", lambda cmd: llamadas.append(cmd))
    navegador.abrir("http://x/", "brave", app=True)
    navegador.abrir("http://x/", "brave")
    assert llamadas == [["/b", "--app=http://x/"], ["/b", "http://x/"]]
    registrado = []
    monkeypatch.setattr(navegador.webbrowser, "register", lambda *a, **k: registrado.append(a))
    assert navegador.registrar_webbrowser("chrome") == "brave"
    assert registrado[0][0] == "kardex"


def test_abrir_sin_navegador_usa_webbrowser(monkeypatch):
    _simular(monkeypatch, {})
    vistos = []
    monkeypatch.setattr(navegador.webbrowser, "open", lambda u: vistos.append(u))
    navegador.abrir("http://x/", "chrome", app=True)
    assert vistos == ["http://x/"]
    assert navegador.registrar_webbrowser("chrome") is None
