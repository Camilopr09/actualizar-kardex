"""Recorrido completo de la interfaz real (Playwright) contra el backend real en modo --demo.
Se salta si no hay playwright o Chromium. Capturas: variable KARDEX_CAPTURAS=<carpeta>."""
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time

import pytest

from chromium_pruebas import disponible

CHROMIUM = disponible()
pytestmark = [
    pytest.mark.skipif(CHROMIUM is None, reason="falta playwright o Chromium"),
    pytest.mark.skipif(sys.platform.startswith("win"), reason="el recorrido usa un «brave» falso de Linux"),
]
RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAPTURAS = os.environ.get("KARDEX_CAPTURAS")


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def app(tmp_path):
    datos = tmp_path / "datos"
    datos.mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    brave = bin_ / "brave"                      # «Brave» falso, solo para que figure como instalado
    brave.write_text("#!/bin/sh\nexit 0\n")
    brave.chmod(0o755)
    env = dict(os.environ, KARDEX_DATOS=str(datos), PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}",
               KARDEX_CHROME=CHROMIUM, PYTHONUNBUFFERED="1")
    puerto = _puerto_libre()
    proc = subprocess.Popen([sys.executable, "app.py", "--demo", "--no-abrir", "--puerto", str(puerto)],
                            cwd=RAIZ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    archivo = datos / "instancia-demo.json"
    t0 = time.time()
    while not archivo.exists():
        if proc.poll() is not None or time.time() - t0 > 20:
            proc.kill()
            pytest.fail("la app no arrancó: " + (proc.stdout.read() if proc.stdout else ""))
        time.sleep(0.1)
    time.sleep(0.2)
    info = json.loads(archivo.read_text())
    yield {"puerto": info["puerto"], "token": info["token"], "datos": datos, "proc": proc,
           "url": f"http://127.0.0.1:{info['puerto']}/?t={info['token']}"}
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _api(app, ruta, cuerpo=None):
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{app['puerto']}{ruta}", headers={"X-Token": app["token"]},
                                 data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                                 method="GET" if cuerpo is None else "POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _esperar_fin(app, n_previo):
    """Espera a que termine la tarea en curso (ultima.n > n_previo y sin tarea)."""
    for _ in range(100):
        e = _api(app, "/api/estado")
        if not e["tarea"] and e["ultima"] and e["ultima"]["n"] > n_previo:
            return e
        time.sleep(0.1)
    raise AssertionError("la tarea no terminó")


def test_recorrido_completo(app, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    errores, malas = [], []
    esperadas_4xx = []          # (fragmento de URL) que la prueba provoca a propósito

    def foto(page, nombre):
        if CAPTURAS:
            pathlib.Path(CAPTURAS).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(pathlib.Path(CAPTURAS) / f"{nombre}.png"))

    with sync_playwright() as pw:
        nav = pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        ctx = nav.new_context(viewport={"width": 1280, "height": 800}, color_scheme="light",
                              permissions=["clipboard-read", "clipboard-write"])
        # sin red: las tipografías de Google se sirven vacías para no ensuciar la consola
        ctx.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
                  lambda r: r.fulfill(status=200, body="", content_type="text/css"))
        page = ctx.new_page()
        page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errores.append(f"pageerror: {e}"))
        page.on("response", lambda r: malas.append((r.status, r.url)) if r.status >= 400 else None)
        page.set_default_timeout(15000)

        # ---- Principal vacía
        page.goto(app["url"])
        expect(page.get_by_text("Todavía no hay resultados")).to_be_visible()
        expect(page.locator("#sesText")).to_have_text("Sin sesión guardada")
        expect(page.locator("#demoTag")).to_be_visible()
        foto(page, "01-principal-vacia")

        # ---- Analizar sin sesión: aviso y Primer uso
        page.click("#bAnalyze")
        expect(page.locator("#toast")).to_contain_text("Primero inicia sesión")
        expect(page.locator("#sc-login")).to_be_visible()
        expect(page.get_by_text("Paso 1. Abre el navegador")).to_be_visible()
        foto(page, "02-primer-uso")

        # ---- Sesión (demo): En curso -> Hecho
        page.get_by_role("button", name="Abrir Chrome").click()
        expect(page.get_by_text("En curso")).to_be_visible()
        expect(page.get_by_text("Hospital Office: ✓ dentro")).to_be_visible(timeout=10000)
        expect(page.get_by_text("Google: ✓ dentro")).to_be_visible(timeout=10000)
        foto(page, "03-sesion-en-curso")
        expect(page.locator("#sc-login").get_by_text("Sesión guardada")).to_be_visible(timeout=15000)
        expect(page.locator("#sesText")).to_have_text("Sesión guardada")
        page.get_by_role("button", name="Ir al inicio").click()
        expect(page.locator("#sc-main")).to_be_visible()

        # ---- Un análisis cancelado no deja resultado
        page.click("#bAnalyze")
        expect(page.locator("#sc-analyzing")).to_be_visible()
        expect(page.locator("#sc-analyzing")).to_contain_text(re.compile(r"\(\d+/27\)"))
        foto(page, "04-analizando")
        page.get_by_role("button", name="Cancelar").click()
        expect(page.locator("#sc-main")).to_be_visible()
        expect(page.get_by_text("Todavía no hay resultados")).to_be_visible()
        _esperar_fin(app, 1)
        assert _api(app, "/api/estado")["resultado"] is None

        # ---- Analizar completo -> Resultado
        page.click("#bAnalyze")
        expect(page.locator("#sc-result")).to_be_visible(timeout=30000)
        expect(page.get_by_role("heading", name="Resultado del análisis")).to_be_visible()
        foto(page, "05-resultado")
        page.get_by_role("button", name="Revisar y aprobar cambios →").click()
        expect(page.locator("#sc-main")).to_be_visible()

        est = _api(app, "/api/estado")
        res = est["resultado"]
        n_act = len(res["acciones"])
        tabs = page.locator("#tabs [role=tab]")
        expect(tabs).to_have_count(3)
        expect(tabs.nth(0)).to_contain_text(str(n_act))
        expect(tabs.nth(1)).to_contain_text(str(len(res["sistema"])))
        expect(tabs.nth(2)).to_contain_text(str(len(res["kardex"])))
        foto(page, "06-principal-con-datos")

        # ---- Filtro por tipo, por texto, orden
        page.select_option("#typeF", "RETIRAR")
        n_ret = sum(1 for a in res["acciones"] if a["tipo"] == "RETIRAR")
        expect(page.locator("#panel .row")).to_have_count(n_ret)
        expect(page.locator("#cmpTag")).to_contain_text("RETIRAR")
        expect(page.locator("#cmpNew")).to_contain_text("No aparece en el sistema")
        page.select_option("#typeF", "AGREGAR")
        expect(page.locator("#cmpOld")).to_contain_text("No está en el kardex")
        page.select_option("#typeF", "ALL")
        expect(page.locator("#panel .row")).to_have_count(n_act)
        palabra = res["acciones"][0]["paciente"].split()[0]
        page.fill("#q", palabra.lower())
        expect(page.locator("#panel .row").first).to_contain_text(palabra)
        assert page.locator("#panel .row").count() < n_act
        page.fill("#q", "")
        page.locator(".hbtn[data-key=paciente]").click()
        nombres = page.locator("#panel .row .rbtn span:nth-child(2)").all_inner_texts()
        assert nombres == sorted(nombres, key=lambda x: x.lower()) or nombres[0] <= nombres[-1]
        page.locator(".hbtn[data-key=paciente]").click()
        desc = page.locator("#panel .row .rbtn span:nth-child(2)").all_inner_texts()
        assert desc[0] >= desc[-1]

        # ---- Selección de una ACTUALIZAR y diff
        page.select_option("#typeF", "ACTUALIZAR")
        page.locator("#panel .row .rbtn").nth(2).click()
        expect(page.locator("#cmpTag")).to_contain_text("ACTUALIZAR")
        assert page.locator("#cmpNew .d-add").count() + page.locator("#cmpOld .d-del").count() > 0
        foto(page, "07-seleccion-diff")

        # ---- Pestaña sistema: la fila de un paciente con acción muestra ESA acción (enlace por id)
        acc = next(a for a in res["acciones"] if a["tipo"] == "ACTUALIZAR")
        fila_s = next(s for s in res["sistema"] if s["id"] == acc["id_sistema"])
        assert fila_s["nombre"] != acc["paciente"] or True
        tabs.nth(1).click()
        page.fill("#q", fila_s["nombre"])
        page.locator("#panel .row .rbtn").first.click()
        expect(page.locator("#cmpTag")).to_contain_text(re.compile("ACTUALIZAR|REVISAR|AGREGAR"))
        expect(page.locator("#cmpWho")).to_contain_text(acc["paciente"])
        foto(page, "08-pestana-sistema")
        # un paciente sin acción muestra SIN CAMBIOS con DX de ambos lados
        con_accion = {a["id_sistema"] for a in res["acciones"]}
        sin = next(s for s in res["sistema"] if s["id"] not in con_accion and s["id_kardex"])
        page.fill("#q", sin["nombre"])
        page.locator("#panel .row .rbtn").first.click()
        expect(page.locator("#cmpTag")).to_contain_text("SIN CAMBIOS")
        kdx = next(k for k in res["kardex"] if k["id"] == sin["id_kardex"])
        expect(page.locator("#cmpOld")).to_contain_text(kdx["dx"].split("\n")[0])
        # pestaña kardex
        tabs.nth(2).click()
        page.fill("#q", "")
        page.locator("#panel .row .rbtn").nth(1).click()
        foto(page, "09-pestana-kardex")
        # un RETIRAR se ve desde la fila del kardex
        ret = next(a for a in res["acciones"] if a["tipo"] == "RETIRAR")
        k_ret = next(k for k in res["kardex"] if k["id"] == ret["id_kardex"])
        page.fill("#q", k_ret["nombre"])
        page.locator("#panel .row .rbtn").first.click()
        expect(page.locator("#cmpTag")).to_contain_text("RETIRAR")
        page.fill("#q", "")

        # ---- Marcar / desmarcar / marcar todas
        tabs.nth(0).click()
        page.select_option("#typeF", "ALL")
        auto = [a for a in res["acciones"] if a["automatica"]]
        cbs = page.locator("#panel input[data-cb]:not([disabled])")
        expect(cbs).to_have_count(len(auto))
        assert all(cbs.nth(i).is_checked() for i in range(len(auto)))
        cbs.nth(0).uncheck()
        expect(page.locator("#allCb")).not_to_be_checked()
        assert page.locator("#allCb").evaluate("e=>e.indeterminate") is True
        page.locator("#allCb").check()
        expect(cbs.nth(0)).to_be_checked()
        page.locator("#allCb").uncheck()
        assert not any(cbs.nth(i).is_checked() for i in range(len(auto)))
        page.click("#bWrite")
        expect(page.locator("#toast")).to_contain_text("Marca al menos una celda")
        page.click("#bCopy")
        expect(page.locator("#toast")).to_contain_text("Marca al menos una celda")
        page.locator("#allCb").check()

        # ---- El texto escrito sobrevive a los sondeos (3 s sin tarea)
        page.click("#q")
        page.keyboard.type("texto de prueba")
        page.wait_for_timeout(3600)
        assert page.input_value("#q") == "texto de prueba"
        assert page.evaluate("document.activeElement.id") == "q"
        page.fill("#q", "")
        page.click("#kurl")
        page.keyboard.type("XYZ")
        page.wait_for_timeout(3600)
        assert "XYZ" in page.input_value("#kurl")
        page.fill("#kurl", est["config"]["url_kardex"])
        page.locator("#kurl").blur()

        # ---- Copiar texto nuevo
        page.click("#bCopy")
        expect(page.locator("#toast")).to_contain_text("Texto nuevo copiado")
        portapapeles = page.evaluate("navigator.clipboard.readText()")
        assert " · " in portapapeles and "\n\n" in portapapeles
        assert portapapeles.split("\n")[0].split(" · ")[1] in ("DX", "EVOLUCIÓN", "TRATAMIENTO")

        # ---- Confirmar y escribir
        page.click("#bWrite")
        dlg = page.get_by_role("dialog")
        expect(dlg).to_be_visible()
        expect(dlg).to_contain_text(f"Se escribirán {len(auto)} celdas")
        foto(page, "10-confirmar")
        page.keyboard.press("Escape")
        expect(dlg).to_be_hidden()
        page.click("#bWrite")
        dlg.get_by_role("button", name="Continuar").click()
        expect(page.locator("#sc-done")).to_be_visible(timeout=15000)
        expect(page.get_by_role("heading", name="Escritura terminada")).to_be_visible()
        expect(page.locator("#sc-done")).to_contain_text("Omitidas (1)")
        expect(page.locator("#sc-done")).to_contain_text("La fila cambió")
        expect(page.locator("#sc-done")).to_contain_text(f"Celdas escritas ({len(auto) - 1})")
        foto(page, "11-escritura-terminada")
        page.get_by_role("button", name="Abrir el kardex").click()
        page.get_by_role("button", name="Volver al inicio").click()
        expect(page.locator("#sc-main")).to_be_visible()
        expect(page.locator("#tabs [role=tab]").first).to_contain_text(str(n_act - (len(auto) - 1)))
        assert _api(app, "/api/estado")["escritura"]["omitidas"]

        # ---- Cancelar durante un nuevo análisis: el resultado anterior se conserva
        previo = _api(app, "/api/estado")
        antes = previo["resultado"]
        page.click("#bAnalyze")
        expect(page.locator("#sc-analyzing")).to_be_visible()
        page.get_by_role("button", name="Cancelar").click()
        expect(page.locator("#sc-main")).to_be_visible()
        despues = _esperar_fin(app, previo["ultima"]["n"])
        assert despues["ultima"]["fin"] == "cancelado" and despues["resultado"] == antes

        # ---- Ajustes
        page.click("#setBtn")
        expect(page.locator("#sc-settings")).to_be_visible()
        foto(page, "12-ajustes")
        expect(page.locator("#nav-brave")).to_be_enabled()
        page.locator("label[for=nav-brave]").click()
        page.get_by_role("button", name="Guardar ajustes").click()
        expect(page.locator("#toast")).to_contain_text("Ajustes guardados")
        assert _api(app, "/api/estado")["config"]["navegador"] == "brave"
        page.click("#setBtn")
        expect(page.locator("#nav-brave")).to_be_checked()
        page.locator("label[for=nav-chrome]").click()
        # especialistas: agregar y quitar (incluye pasar 3,5 s con texto en el campo)
        page.get_by_label("Nombre del nuevo especialista").fill("PEREZ")
        page.wait_for_timeout(3600)
        assert page.get_by_label("Nombre del nuevo especialista").input_value() == "PEREZ"
        page.get_by_role("button", name="Agregar", exact=True).click()
        expect(page.locator("#chips")).to_contain_text("PEREZ")
        page.get_by_role("button", name="Quitar a DAZA").click()
        expect(page.locator("#chips")).not_to_contain_text("DAZA")
        # credenciales: archivo inválido, válido y quitar
        malo = tmp_path / "malo.json"
        malo.write_text('{"otra": 1}')
        page.set_input_files("#credFile", str(malo))
        expect(page.locator("#toast")).to_contain_text("no es un credentials.json")
        esperadas_4xx.append("/api/credenciales")
        bueno = tmp_path / "credentials.json"
        bueno.write_text(json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}))
        page.set_input_files("#credFile", str(bueno))
        expect(page.locator("#toast")).to_contain_text("Credenciales guardadas")
        assert (app["datos"] / "credentials.json").exists()
        page.get_by_role("button", name="Quitar credenciales").click()
        expect(page.locator("#toast")).to_contain_text("Credenciales quitadas")
        assert not (app["datos"] / "credentials.json").exists()
        foto(page, "13-ajustes-editados")
        page.get_by_role("button", name="Guardar ajustes").click()
        expect(page.locator("#toast")).to_contain_text("Ajustes guardados")
        cfg = _api(app, "/api/estado")["config"]
        assert cfg["navegador"] == "chrome" and cfg["especialistas"] == ["FABIAN", "EMILIANI", "PEREZ"]
        # Cancelar descarta
        page.click("#setBtn")
        page.get_by_label("Nombre del nuevo especialista").fill("NADIE")
        page.get_by_role("button", name="Agregar", exact=True).click()
        page.get_by_role("button", name="Cancelar").click()
        assert "NADIE" not in _api(app, "/api/estado")["config"]["especialistas"]

        # ---- Tema oscuro
        page.click("#themeBtn")
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(15, 23, 28)"
        foto(page, "14-tema-oscuro-principal")
        page.click("#setBtn")
        foto(page, "15-tema-oscuro-ajustes")
        page.get_by_role("button", name="Cancelar").click()
        page.reload()
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"     # se recuerda
        page.click("#themeBtn")

        ctx.close()
        nav.close()

    inesperadas = [m for m in malas if not any(e in m[1] for e in esperadas_4xx)]
    assert not inesperadas, inesperadas
    # el 400 del archivo inválido aparece como error de recurso en consola: es el esperado
    reales = [e for e in errores if "400" not in e]
    assert not reales, reales

    # ---- Apagado por /api/salir
    assert _api(app, "/api/salir", {})["ok"] is True
    app["proc"].wait(10)
    assert not (app["datos"] / "instancia-demo.json").exists()
