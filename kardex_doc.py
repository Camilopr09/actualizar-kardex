"""Lectura del Google Doc (exportación HTML con la sesión del navegador) y
escritura opcional con la API de Google Docs."""
import re
from html.parser import HTMLParser

from comparar import FilaKardex

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


def parsear_kardex_html(html):
    """Devuelve list[FilaKardex] de todas las tablas cuyo encabezado empieza por DATOS."""
    p = _Parser()
    p.feed(html)
    filas = []
    for idx, (titulo, rows) in enumerate(p.tablas):
        if not rows or not rows[0] or not rows[0][0].upper().startswith("DATOS"):
            continue
        for i, r in enumerate(rows[1:], start=1):
            r = r + [""] * (7 - len(r))
            if not any(c.strip() for c in r):
                continue
            filas.append(FilaKardex(tabla=idx, fila=i, servicio=titulo or f"Tabla {idx+1}",
                                    datos=r[0], dx=r[1], evolucion=r[2], tratamiento=r[3]))
    return filas


def id_documento(url_o_id):
    m = re.search(r"/document/d/([A-Za-z0-9_-]+)", url_o_id or "")
    return m.group(1) if m else (url_o_id or "").strip()


def descargar_html(contexto, url):
    """Descarga el HTML exportado usando las cookies del navegador ya iniciado."""
    doc = id_documento(url)
    r = contexto.request.get(f"https://docs.google.com/document/d/{doc}/export?format=html")
    if not r.ok or "accounts.google.com" in r.url:
        raise RuntimeError("No se pudo leer el Google Doc. Usa «Iniciar sesión» y entra a tu cuenta de Google "
                           "(la que tiene acceso al KARDEX).")
    return r.text()


# ---------------------------------------------------------------- escritura (opcional)
SCOPES = ["https://www.googleapis.com/auth/documents"]
_COL = {"DX": 1, "EVOLUCIÓN": 2, "TRATAMIENTO": 3}


def servicio_docs(carpeta):
    """Crea el cliente de la API. Requiere credentials.json en la carpeta de datos."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    cred_file, token_file = carpeta / "credentials.json", carpeta / "token.json"
    if not cred_file.exists():
        raise FileNotFoundError(f"Falta {cred_file}. Ver LEEME.md, sección «Para escribir en el documento».")
    cred = Credentials.from_authorized_user_file(str(token_file), SCOPES) if token_file.exists() else None
    if not cred or not cred.valid:
        if cred and cred.expired and cred.refresh_token:
            cred.refresh(Request())
        else:
            cred = InstalledAppFlow.from_client_secrets_file(str(cred_file), SCOPES).run_local_server(port=0)
        token_file.write_text(cred.to_json())
    return build("docs", "v1", credentials=cred, cache_discovery=False)


def _texto_celda(celda):
    out = []
    for el in celda.get("content", []):
        for e in el.get("paragraph", {}).get("elements", []):
            out.append(e.get("textRun", {}).get("content", ""))
    return "".join(out).rstrip("\n")


def aplicar(servicio, url, acciones):
    """Escribe las acciones ACTUALIZAR. Relee el doc y verifica que la fila siga siendo
    el mismo paciente antes de escribir. Devuelve (escritas, omitidas)."""
    doc_id = id_documento(url)
    doc = servicio.documents().get(documentId=doc_id).execute()
    tablas = [e["table"] for e in doc["body"]["content"] if "table" in e]
    # índice de tabla en la API = posición entre tablas del documento (igual que en el HTML)
    reqs, escritas, omitidas = [], 0, []
    for a in acciones:
        f = a.fila
        try:
            fila = tablas[f.tabla]["tableRows"][f.fila]
            celdas = fila["tableCells"]
            nombre_actual = _texto_celda(celdas[0]).split("\n")[0].strip()
            if nombre_actual.upper() != f.nombre.upper():
                omitidas.append(f"{a.paciente} ({a.campo}): la fila cambió (ahora «{nombre_actual}»)")
                continue
            c = celdas[_COL[a.campo]]
        except (IndexError, KeyError):
            omitidas.append(f"{a.paciente} ({a.campo}): no se encontró la celda")
            continue
        contenido = c["content"]
        ini = contenido[0]["startIndex"]
        fin = contenido[-1]["endIndex"] - 1
        sub = []
        if fin > ini:
            sub.append({"deleteContentRange": {"range": {"startIndex": ini, "endIndex": fin}}})
        sub.append({"insertText": {"location": {"index": ini}, "text": a.nuevo}})
        fin_nuevo = ini + len(a.nuevo)
        sub.append({"updateTextStyle": {
            "range": {"startIndex": ini, "endIndex": fin_nuevo},
            "textStyle": {"bold": False}, "fields": "bold"}})
        sub.append({"updateParagraphStyle": {
            "range": {"startIndex": ini, "endIndex": fin_nuevo},
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "fields": "namedStyleType"}})
        reqs.append((ini, sub))
        escritas += 1
    # de abajo hacia arriba para que los índices no se desplacen
    plano = [r for _, sub in sorted(reqs, key=lambda x: -x[0]) for r in sub]
    if plano:
        servicio.documents().batchUpdate(documentId=doc_id, body={"requests": plano}).execute()
    return escritas, omitidas
