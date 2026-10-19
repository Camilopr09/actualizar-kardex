"""Lectura del Google Doc (exportación HTML con la sesión del navegador) y
escritura opcional con la API de Google Docs."""
import re
from html.parser import HTMLParser

from comparar import FilaKardex, interpretar_datos
from errores import ErrorApp
import navegador
from notas import normalizar

_BLOQUE = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div"}


class _Parser(HTMLParser):
    """Extrae (titulo_previo, [filas]) por cada tabla del documento."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tablas = []          # [(titulo, [[celda, ...], ...])]
        self._prof = 0
        self._tabla = None
        self._fila = None
        self._celda = None
        self._ultimo_texto = ""
        self._buf = []
        self._ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._ignorar += 1
        elif tag == "table":
            self._prof += 1
            if self._prof == 1:
                self._tabla = (self._ultimo_texto, [])
        elif tag == "tr" and self._prof == 1:
            self._fila = []
        elif tag in ("td", "th") and self._prof == 1:
            self._celda = []
        elif tag == "br" and self._celda is not None:
            self._celda.append("\n")
        elif tag in _BLOQUE:
            self._cierre_bloque()

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._ignorar -= 1
        elif tag == "table":
            if self._prof == 1 and self._tabla:
                self.tablas.append(self._tabla)
                self._tabla = None
            self._prof -= 1
        elif tag == "tr" and self._prof == 1 and self._fila is not None:
            if self._tabla:
                self._tabla[1].append(self._fila)
            self._fila = None
        elif tag in ("td", "th") and self._prof == 1 and self._celda is not None:
            texto = "".join(self._celda)
            texto = re.sub(r"[ \t\xa0]+", " ", texto)
            texto = "\n".join(l.strip() for l in texto.split("\n"))
            texto = re.sub(r"\n{2,}", "\n", texto).strip()
            if self._fila is not None:
                self._fila.append(texto)
            self._celda = None
        elif tag in _BLOQUE:
            self._cierre_bloque()

    def _cierre_bloque(self):
        if self._celda is not None:
            if self._celda and self._celda[-1] != "\n":
                self._celda.append("\n")
        elif self._prof == 0 and self._buf:
            t = " ".join("".join(self._buf).split())
            if t:
                self._ultimo_texto = t
            self._buf = []

    def handle_data(self, data):
        if self._ignorar:
            return
        if self._celda is not None:
            self._celda.append(data)
        elif self._prof == 0:
            self._buf.append(data)


def _limpiar_titulo(texto):
    """«PISO 4A ( 4 PACIENTES) 422 - 430» -> «PISO 4A»; «UCI 1  (2 PACIENTES)» -> «UCI 1»;
    «PISO 5 (  PACIENTES)» -> «PISO 5». Quita el paréntesis de pacientes (con o sin número) y el
    rango de habitaciones del final."""
    t = re.sub(r"\(\s*\d*\s*PACIENTES?\s*\)", " ", texto or "", flags=re.I)
    t = re.sub(r"\s+\d+[A-Z]?\s*-\s*\d+[A-Z]?\s*$", "", " ".join(t.split()), flags=re.I)
    return t.strip()


def _es_encabezado(fila):
    return bool(fila) and " ".join(fila[0].split()).upper().startswith("DATOS")


def columnas_por_encabezado(encabezado):
    """{'DX': i, 'EVOLUCIÓN': i, 'TRATAMIENTO': i}; los que la tabla no tiene quedan en None."""
    cols = {"DX": None, "EVOLUCIÓN": None, "TRATAMIENTO": None}
    for i, c in enumerate(encabezado):
        n = normalizar(c)
        for campo, clave in (("DX", "DX"), ("EVOLUCIÓN", "EVOLUCION"), ("TRATAMIENTO", "TRATAMIENTO")):
            if cols[campo] is None and n.startswith(clave):
                cols[campo] = i
    return cols


def parsear_kardex_html(html):
    """Devuelve list[FilaKardex] de todas las tablas cuyo encabezado empieza por DATOS.
    El encabezado puede ser la fila 0 o venir tras una fila de título (celda combinada) dentro
    de la tabla; el servicio sale de ese título o, si no hay, del párrafo previo a la tabla.
    Las columnas DX/EVOLUCIÓN/TRATAMIENTO se leen POR NOMBRE del encabezado (None si no existen).
    FilaKardex.fila es el índice ABSOLUTO de la fila en la tabla (cuenta título y encabezado).
    Se saltan las filas vacías; una fila con solo el nombre cuenta como paciente."""
    p = _Parser()
    p.feed(html)
    filas = []
    for idx, (previo, rows) in enumerate(p.tablas):
        enc = next((i for i, r in enumerate(rows[:3]) if _es_encabezado(r)), None)
        if enc is None:
            continue
        titulo = ""
        for r in rows[:enc]:
            celdas = [c for c in r if c.strip()]
            if len(celdas) == 1:
                titulo = celdas[0]
        servicio = _limpiar_titulo(titulo) or _limpiar_titulo(previo) or f"Tabla {idx+1}"
        cols = columnas_por_encabezado(rows[enc])

        def celda(r, campo):
            c = cols[campo]
            return r[c] if c is not None and c < len(r) else ""
        for i, r in enumerate(rows[enc + 1:], start=enc + 1):
            if not any(c.strip() for c in r):
                continue
            filas.append(FilaKardex(tabla=idx, fila=i, servicio=servicio, datos=r[0],
                                    dx=celda(r, "DX"), evolucion=celda(r, "EVOLUCIÓN"),
                                    tratamiento=celda(r, "TRATAMIENTO"),
                                    col_dx=cols["DX"], col_evolucion=cols["EVOLUCIÓN"],
                                    col_tratamiento=cols["TRATAMIENTO"]))
    return filas


def describir_tablas(html):
    """(cantidad de tablas, texto de la primera celda de la primera tabla, máx. 60 caracteres)."""
    p = _Parser()
    p.feed(html)
    primera = ""
    if p.tablas and p.tablas[0][1] and p.tablas[0][1][0]:
        primera = " ".join(p.tablas[0][1][0][0].split())[:60]
    return len(p.tablas), primera


def id_documento(url_o_id):
    m = re.search(r"/document/d/([A-Za-z0-9_-]+)", url_o_id or "")
    return m.group(1) if m else (url_o_id or "").strip()


def _pestana(url):
    """«t.0» de una URL con `tab=t.0`, o ''."""
    m = re.search(r"[?&#]tab=(t\.[A-Za-z0-9_]+)", url or "")
    return m.group(1) if m else ""


def descargar_html(contexto, url):
    """Descarga el HTML exportado usando las cookies del navegador ya iniciado.
    Si la URL trae `tab=t.xxx` (documento con pestañas) se pide esa pestaña añadiendo
    `&tab=t.xxx` a la URL de exportación. NO está verificado contra Google: si la exportación
    con tab falla con error HTTP, se reintenta sin tab (que exporta la primera pestaña)."""
    if url.startswith(("http://127.0.0.1", "http://localhost")):
        r = contexto.request.get(url)          # simulador de pruebas: se descarga tal cual
    else:
        doc = id_documento(url)
        base = f"https://docs.google.com/document/d/{doc}/export?format=html"
        tab = _pestana(url)
        r = contexto.request.get(f"{base}&tab={tab}" if tab else base)
        if tab and not r.ok and "accounts.google.com" not in r.url:
            r = contexto.request.get(base)
    if "accounts.google.com" in r.url:
        raise ErrorApp("sesion", "Google pide iniciar sesión. Entra a la cuenta que tiene acceso al KARDEX.")
    if not r.ok:
        raise ErrorApp("kardex", f"No se pudo leer el Google Doc (respuesta {r.status}). Revisa el enlace del KARDEX.")
    return r.text()


# ---------------------------------------------------------------- escritura (opcional)
SCOPES = ["https://www.googleapis.com/auth/documents"]


def servicio_docs(carpeta, preferido="chrome"):
    """Crea el cliente de la API. Requiere credentials.json en la carpeta de datos."""
    cred_file, token_file = carpeta / "credentials.json", carpeta / "token.json"
    if not cred_file.exists():
        raise ErrorApp("credenciales", "Falta credentials.json. Cárgalo en Ajustes (ver LEEME.md, "
                                       "sección «Para escribir en el documento»).")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    cred = Credentials.from_authorized_user_file(str(token_file), SCOPES) if token_file.exists() else None
    if not cred or not cred.valid:
        if cred and cred.expired and cred.refresh_token:
            cred.refresh(Request())
        else:
            flujo = InstalledAppFlow.from_client_secrets_file(str(cred_file), SCOPES)
            nav = "kardex" if navegador.registrar_webbrowser(preferido) else None   # el consentimiento se abre ahí
            cred = flujo.run_local_server(port=0, browser=nav)
        token_file.write_text(cred.to_json())
    return build("docs", "v1", credentials=cred, cache_discovery=False)


def _texto_celda(celda):
    out = []
    for el in celda.get("content", []):
        for e in el.get("paragraph", {}).get("elements", []):
            out.append(e.get("textRun", {}).get("content", ""))
    return "".join(out).rstrip("\n")


def _utf16(texto):
    """Longitud en unidades UTF-16 (los índices de la API de Docs se miden así)."""
    return len(texto.encode("utf-16-le")) // 2


def _columnas_api(filas):
    """Columnas por nombre leyendo el encabezado de ESA tabla (fila que empieza por DATOS entre las 3 primeras)."""
    for fila in filas[:3]:
        textos = [_texto_celda(c) for c in fila.get("tableCells", [])]
        if textos and " ".join(textos[0].split()).upper().startswith("DATOS"):
            return columnas_por_encabezado(textos)
    return None


def aplicar(servicio, url, acciones):
    """Escribe las acciones ACTUALIZAR. Relee el doc y verifica que la fila siga siendo
    el mismo paciente antes de escribir. La columna se elige por el ENCABEZADO de la tabla.
    No toca el formato: el texto hereda el estilo de la celda; solo la primera línea de EVOLUCIÓN
    (fecha - DR. médico) se pone en negrita.
    Devuelve (escritas: list[Accion], omitidas: list[(Accion, motivo)])."""
    doc_id = id_documento(url)
    doc = servicio.documents().get(documentId=doc_id).execute()
    tablas = [e["table"] for e in doc["body"]["content"] if "table" in e]
    # índice de tabla en la API = posición entre tablas del documento (igual que en el HTML)
    reqs, escritas, omitidas = [], [], []
    for a in acciones:
        f = a.fila
        try:
            filas = tablas[f.tabla]["tableRows"]
            celdas = filas[f.fila]["tableCells"]
            nombre_actual = interpretar_datos(_texto_celda(celdas[0]))["nombre"]
            if normalizar(nombre_actual) != normalizar(f.nombre):
                omitidas.append((a, f"La fila cambió (ahora dice «{nombre_actual}»)"))
                continue
            cols = _columnas_api(filas)
            col = (cols or {"DX": 1, "EVOLUCIÓN": 2, "TRATAMIENTO": 3}).get(a.campo)
            if col is None:
                omitidas.append((a, f"La tabla no tiene la columna {a.campo}"))
                continue
            c = celdas[col]
        except (IndexError, KeyError):
            omitidas.append((a, "No se encontró la celda"))
            continue
        contenido = c["content"]
        ini = contenido[0]["startIndex"]
        fin = contenido[-1]["endIndex"] - 1
        sub = []
        if fin > ini:
            sub.append({"deleteContentRange": {"range": {"startIndex": ini, "endIndex": fin}}})
        sub.append({"insertText": {"location": {"index": ini}, "text": a.nuevo}})
        if a.campo == "EVOLUCIÓN" and a.nuevo.strip():
            primera = a.nuevo.split("\n")[0]
            fin_primera, fin_todo = ini + _utf16(primera), ini + _utf16(a.nuevo)
            sub.append({"updateTextStyle": {"range": {"startIndex": ini, "endIndex": fin_primera},
                                            "textStyle": {"bold": True}, "fields": "bold"}})
            if fin_todo > fin_primera:   # el texto de la nota va sin negrita, como en el kardex
                sub.append({"updateTextStyle": {"range": {"startIndex": fin_primera, "endIndex": fin_todo},
                                                "textStyle": {"bold": False}, "fields": "bold"}})
        reqs.append((ini, sub))
        escritas.append(a)
    # de abajo hacia arriba para que los índices no se desplacen
    plano = [r for _, sub in sorted(reqs, key=lambda x: -x[0]) for r in sub]
    if plano:
        servicio.documents().batchUpdate(documentId=doc_id, body={"requests": plano}).execute()
    return escritas, omitidas
