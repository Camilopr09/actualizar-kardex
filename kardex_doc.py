"""Lectura del Google Doc del kardex y de los documentos de ENTREGAS (exportación HTML con la sesión del
navegador; los de entregas solo se leen) y escritura del kardex con la API de Google Docs."""
import re
from html.parser import HTMLParser

from comparar import FilaKardex, PacienteEntrega, TablaKardex, interpretar_datos
from errores import ErrorApp
import navegador
from notas import lineas_titulo_imagen, normalizar, punto_insercion_imagenes

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
    «PISO 5 (  PACIENTES)» -> «PISO 5»; «PISO 4B ( 3 PACIENTES) 430 EN ADELANTE» -> «PISO 4B». Quita el paréntesis
    de pacientes (con o sin número) y el rango de habitaciones del final."""
    t = re.sub(r"\(\s*\d*\s*PACIENTES?\s*\)", " ", texto or "", flags=re.I)
    t = " ".join(t.split())
    t = re.sub(r"\s*\(\s*\d+[A-Z]?\s*(?:-\s*\d+[A-Z]?|EN\s+ADELANTE)\s*\)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+\d+[A-Z]?\s*-\s*\d+[A-Z]?\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+\d+[A-Z]?\s+EN\s+ADELANTE\s*$", "", t, flags=re.I)
    return t.strip()


def _rango_titulo(titulo):
    """Habitaciones de la tabla según su título: «… 422 - 430» -> (422, 430); «… 430 EN ADELANTE» -> (430, None);
    sin rango -> None."""
    t = " ".join(re.sub(r"\(\s*\d*\s*PACIENTES?\s*\)", " ", titulo or "", flags=re.I).split())
    m = re.search(r"(\d{3,4})[A-Z]?\s*-\s*(\d{3,4})[A-Z]?\)?\s*$", t, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{3,4})[A-Z]?\s+EN\s+ADELANTE\)?\s*$", t, re.I)
    return (int(m.group(1)), None) if m else None


def _es_encabezado(fila):
    return bool(fila) and " ".join(fila[0].split()).upper().startswith("DATOS")


# nombre de cada columna del kardex y con qué empieza su encabezado (normalizado, sin tildes)
_CLAVES_COLUMNA = (("DATOS", "DATOS"), ("DX", "DX"), ("EVOLUCIÓN", "EVOLUCION"), ("TRATAMIENTO", "TRATAMIENTO"),
                   ("LABORATORIOS", "LABORATORIO"), ("IMÁGENES / NOTAS", "IMAGENES"), ("PENDIENTES", "PENDIENTE"))


def columnas_todas(encabezado):
    """{nombre de columna: índice} por el texto del encabezado (la primera que coincida). Las columnas conocidas
    usan su nombre canónico («IMÁGENES / NOTAS»); las otras, su texto normalizado."""
    cols = {}
    for i, c in enumerate(encabezado):
        n = normalizar(c)
        nombre = next((campo for campo, clave in _CLAVES_COLUMNA if n.startswith(clave)), n)
        if n:
            cols.setdefault(nombre, i)
    return cols


def columnas_por_encabezado(encabezado):
    """{'DX': i, 'EVOLUCIÓN': i, 'TRATAMIENTO': i, 'IMÁGENES / NOTAS': i}; las que la tabla no tiene quedan en None."""
    todas = columnas_todas(encabezado)
    return {campo: todas.get(campo) for campo in ("DX", "EVOLUCIÓN", "TRATAMIENTO", "IMÁGENES / NOTAS")}


def _tablas_con_encabezado(html):
    """Tablas del documento cuyo encabezado empieza por DATOS (puede ser la fila 0 o venir tras una fila de título):
    list[dict(indice, servicio, titulo, rows, enc, cols)]. `indice` es la posición entre TODAS las tablas del
    documento (igual que en la API); el servicio sale del título de la tabla o, si no hay, del párrafo previo."""
    p = _Parser()
    p.feed(html)
    out = []
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
        out.append(dict(indice=idx, servicio=servicio, titulo=titulo or previo, rows=rows, enc=enc,
                        cols=columnas_por_encabezado(rows[enc])))
    return out


def parsear_kardex_html(html):
    """Devuelve list[FilaKardex] de todas las tablas cuyo encabezado empieza por DATOS.
    El encabezado puede ser la fila 0 o venir tras una fila de título (celda combinada) dentro
    de la tabla; el servicio sale de ese título o, si no hay, del párrafo previo a la tabla.
    Las columnas DX/EVOLUCIÓN/TRATAMIENTO/IMÁGENES se leen POR NOMBRE del encabezado (None si no existen).
    FilaKardex.fila es el índice ABSOLUTO de la fila en la tabla (cuenta título y encabezado).
    Se saltan las filas vacías; una fila con solo el nombre cuenta como paciente."""
    filas = []
    for t in _tablas_con_encabezado(html):
        cols = t["cols"]

        def celda(r, campo):
            c = cols[campo]
            return r[c] if c is not None and c < len(r) else ""
        for i, r in enumerate(t["rows"][t["enc"] + 1:], start=t["enc"] + 1):
            if not any(c.strip() for c in r):
                continue
            filas.append(FilaKardex(tabla=t["indice"], fila=i, servicio=t["servicio"], datos=r[0],
                                    dx=celda(r, "DX"), evolucion=celda(r, "EVOLUCIÓN"),
                                    tratamiento=celda(r, "TRATAMIENTO"), imagenes=celda(r, "IMÁGENES / NOTAS"),
                                    col_dx=cols["DX"], col_evolucion=cols["EVOLUCIÓN"],
                                    col_tratamiento=cols["TRATAMIENTO"], col_imagenes=cols["IMÁGENES / NOTAS"]))
    return filas


def tablas_kardex(html):
    """list[TablaKardex] de todas las tablas del kardex con encabezado DATOS (también las que no tienen pacientes):
    servicio limpio, título tal cual, rango de habitaciones del título y cuántas filas con contenido hay."""
    return [TablaKardex(indice=t["indice"], servicio=t["servicio"], titulo=t["titulo"], rango=_rango_titulo(t["titulo"]),
                        filas_pacientes=sum(1 for r in t["rows"][t["enc"] + 1:] if any(c.strip() for c in r)))
            for t in _tablas_con_encabezado(html)]


def parsear_entregas_html(html, nombre_doc):
    """list[PacienteEntrega] de un documento «ENTREGAS CRC» (SOLO lectura): una entrada por fila con nombre.
    Tolerante: si la tabla tiene encabezado DATOS esa es la 1.ª columna; si no, también se usa la 1.ª columna
    cuando interpretar_datos saca un nombre de ella. Las filas de título («PISO 6 (5 PACIENTES)»), de encabezado y
    vacías se saltan. `texto` junta todas las celdas de la fila (para buscar «valoración por cirugía»)."""
    p = _Parser()
    p.feed(html)
    out = []
    for previo, rows in p.tablas:
        enc = next((i for i, r in enumerate(rows[:3]) if _es_encabezado(r)), None)
        titulo = ""
        for r in rows[:enc if enc is not None else 3]:
            celdas = [c for c in r if c.strip()]
            if len(celdas) == 1 and (enc is not None or re.search(r"PACIENTES?\b", celdas[0], re.I)):
                titulo = celdas[0]
        servicio = _limpiar_titulo(titulo) or _limpiar_titulo(previo)
        for r in rows[enc + 1 if enc is not None else 0:]:
            celdas = [c for c in r if c.strip()]
            if not celdas or _es_encabezado(r) or (len(celdas) == 1 and celdas[0] == titulo):
                continue
            d = interpretar_datos(r[0])
            if d["nombre"]:
                out.append(PacienteEntrega(nombre=d["nombre"], documento=d["documento"],
                                           tipo_documento=d["tipo_documento"], edad=d["edad"],
                                           habitacion=d["habitacion"], datos=r[0], texto="\n".join(celdas),
                                           doc=nombre_doc, servicio=servicio))
    return out


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
            try:   # si la persona cierra la ventana de Google, no esperar para siempre
                cred = flujo.run_local_server(port=0, browser=nav, timeout_seconds=300)
            except Exception as e:  # noqa: BLE001
                raise ErrorApp("credenciales", "No se completó el permiso de Google en 5 minutos. Vuelve a pulsar "
                                               "«3. Escribir en el kardex» y acepta el permiso en la ventana que se abre "
                                               "(si dice «Google no verificó esta app»: Configuración avanzada → "
                                               "Ir a Actualizar Kardex).") from e
            if not cred or not getattr(cred, "token", None):
                raise ErrorApp("credenciales", "Google no devolvió el permiso. Vuelve a intentarlo.")
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


def _parrafos(celda):
    """[(inicio, fin, texto)] de cada párrafo de la celda; `texto` sin el salto de párrafo final."""
    out = []
    for el in celda.get("content", []):
        par = el.get("paragraph")
        if par is not None:
            texto = "".join(e.get("textRun", {}).get("content", "") for e in par.get("elements", []))
            out.append((el["startIndex"], el["endIndex"], texto[:-1] if texto.endswith("\n") else texto))
    return out


class _Omitida(Exception):
    """Una acción que no se puede escribir (el mensaje es el motivo que ve la persona)."""


class _TablaApi:
    """Vista de una tabla del documento de la API: encabezado, columnas por nombre y utilidades de filas."""

    def __init__(self, elemento, indice, previo=None):
        self.indice = indice
        self.inicio = elemento.get("startIndex")
        self.filas = elemento["table"]["tableRows"]
        self.previo = previo                    # (inicio, texto) del párrafo justo antes de la tabla, si lo hay
        self.enc, self.cols = None, {}
        for i, fila in enumerate(self.filas[:3]):          # el encabezado es la fila que empieza por DATOS
            textos = [_texto_celda(c) for c in fila.get("tableCells", [])]
            if textos and " ".join(textos[0].split()).upper().startswith("DATOS"):
                self.enc, self.cols = i, columnas_todas(textos)
                break

    def celdas(self, i):
        return self.filas[i].get("tableCells", [])

    def texto(self, i, col):
        c = self.celdas(i)
        return _texto_celda(c[col]) if col < len(c) else ""

    def vacia(self, i):
        return not any(_texto_celda(c).strip() for c in self.celdas(i))

    @property
    def primera_fila_de_pacientes(self):
        return self.enc + 1 if self.enc is not None else 0

    def filas_con_contenido(self):
        return [i for i in range(self.primera_fila_de_pacientes, len(self.filas)) if not self.vacia(i)]


def _tablas_api(doc):
    """list[_TablaApi]: el índice de tabla es la posición entre las tablas del cuerpo (igual que en el HTML)."""
    out, previo = [], None
    for el in doc["body"]["content"]:
        if "table" in el:
            out.append(_TablaApi(el, len(out), previo))
        if "paragraph" in el:
            texto = "".join(e.get("textRun", {}).get("content", "") for e in el["paragraph"].get("elements", []))
            previo = (el.get("startIndex"), texto.rstrip("\n"))
        else:
            previo = None
    return out


def _mismo_paciente(texto_datos, nombre, documento):
    """La celda DATOS es del paciente: por documento si ambos lo tienen; si no, por nombre."""
    d = interpretar_datos(texto_datos)
    doc = re.sub(r"\D", "", documento or "")
    if doc and d["documento"]:
        return re.sub(r"\D", "", d["documento"]) == doc
    return bool(nombre) and normalizar(d["nombre"]) == normalizar(nombre)


def _buscar_fila(t, nombre, documento, preferida=None):
    """Índices de las filas de la tabla que son de este paciente (la preferida primero si es una de ellas)."""
    hallas = [i for i in range(t.primera_fila_de_pacientes, len(t.filas))
              if t.celdas(i) and _mismo_paciente(_texto_celda(t.celdas(i)[0]), nombre, documento)]
    if preferida in hallas:
        hallas.remove(preferida)
        hallas.insert(0, preferida)
    return hallas


def _fila_del_paciente(t, fila, nombre, documento):
    """Fila de la tabla donde está el paciente. Se vuelve a buscar POR PACIENTE (si se movieron filas desde que se
    leyó el documento); el índice de la lectura solo desempata. _Omitida si ya no está o es ambiguo."""
    hallas = _buscar_fila(t, nombre, documento, fila)
    if hallas and (hallas[0] == fila or len(hallas) == 1):
        return hallas[0]
    if len(hallas) > 1:
        raise _Omitida("Hay más de una fila de este paciente en la tabla; revísala a mano")
    if t.primera_fila_de_pacientes <= fila < len(t.filas):
        ahora = interpretar_datos(t.texto(fila, 0))["nombre"]
        raise _Omitida(f"La fila cambió (ahora dice «{ahora}»)")
    raise _Omitida("No se encontró la celda")


# ---- pedidos de la API
def _p_insertar(indice, texto):
    return {"insertText": {"location": {"index": indice}, "text": texto}}


def _p_borrar(ini, fin):
    return {"deleteContentRange": {"range": {"startIndex": ini, "endIndex": fin}}}


def _p_estilo(ini, fin, estilo, campos):
    return {"updateTextStyle": {"range": {"startIndex": ini, "endIndex": fin}, "textStyle": estilo, "fields": campos}}


def _p_parrafo(ini, fin, estilo, campos):
    return {"updateParagraphStyle": {"range": {"startIndex": ini, "endIndex": fin}, "paragraphStyle": estilo,
                                     "fields": campos}}


def _p_celda(t, fila, col=0):
    return {"tableCellLocation": {"tableStartLocation": {"index": t.inicio}, "rowIndex": fila, "columnIndex": col}}


VERDE = {"color": {"rgbColor": {"red": 0.0, "green": 1.0, "blue": 0.0}}}      # resaltado de los títulos (#00FF00)
_COPIADOS = ("weightedFontFamily", "fontSize", "bold", "foregroundColor")      # lo que se copia a una fila nueva
# campos que se fijan en todo lo escrito en una fila nueva: lo que no se copia queda en su valor por defecto
# (así no se hereda un resaltado, cursiva o subrayado del texto vecino)
_CAMPOS_FILA_NUEVA = "weightedFontFamily,fontSize,bold,foregroundColor,backgroundColor,italic,underline"
_EDITABLES = ("DX", "EVOLUCIÓN", "TRATAMIENTO", "IMÁGENES / NOTAS")


def _edicion_texto(celda, texto, campo):
    """Reemplaza el contenido de la celda (DX / EVOLUCIÓN / TRATAMIENTO). El texto hereda el estilo de la celda;
    solo la primera línea de EVOLUCIÓN (fecha - DR. médico) va en negrita y el resto sin negrita."""
    contenido = celda["content"]
    ini = contenido[0]["startIndex"]
    fin = contenido[-1]["endIndex"] - 1
    sub = []
    if fin > ini:
        sub.append(_p_borrar(ini, fin))
    sub.append(_p_insertar(ini, texto))
    if campo == "EVOLUCIÓN" and texto.strip():
        primera = texto.split("\n")[0]
        fin_primera, fin_todo = ini + _utf16(primera), ini + _utf16(texto)
        sub.append(_p_estilo(ini, fin_primera, {"bold": True}, "bold"))
        if fin_todo > fin_primera:   # el texto de la nota va sin negrita, como en el kardex
            sub.append(_p_estilo(fin_primera, fin_todo, {"bold": False}, "bold"))
    return ini, sub


def _edicion_imagenes(celda, insertar):
    """Inserta los estudios nuevos en IMÁGENES / NOTAS sin borrar nada: arriba de la celda, o justo debajo del
    subtítulo «IMÁGENES…» si lo tiene. Un renglón vacío los separa de lo que ya había. Lo insertado NO hereda el
    verde ni la negrita del texto vecino: todo va con bold=False y sin resaltado (fields «bold,backgroundColor»
    sin backgroundColor = valor por defecto) y solo el renglón título de cada bloque va en negrita + verde."""
    parrafos = _parrafos(celda)
    textos = [t for _, _, t in parrafos]
    k = punto_insercion_imagenes(textos)
    texto = insertar + ("\n\n" if any(t.strip() for t in textos[k:]) else "")
    al_final = k >= len(parrafos)            # el subtítulo es el último párrafo: se agrega debajo de él
    if al_final:
        indice, texto = parrafos[-1][1] - 1, "\n" + texto
    else:
        indice = parrafos[k][0]
    base = indice + (1 if al_final else 0)
    sub = [_p_insertar(indice, texto)]
    if al_final:     # el párrafo nuevo se parte del subtítulo (centrado/subrayado): no heredar eso
        sub.append(_p_estilo(base, base + _utf16(texto) - 1, {"bold": False, "underline": False},
                             "bold,backgroundColor,underline"))
        sub.append(_p_parrafo(base, base + _utf16(texto) - 1, {"alignment": "START"}, "alignment"))
    elif k:          # debajo del subtítulo: tampoco subrayado (lo que se hereda del renglón de arriba no importa)
        sub.append(_p_estilo(indice, indice + _utf16(texto), {"bold": False, "underline": False},
                             "bold,backgroundColor,underline"))
    else:
        sub.append(_p_estilo(indice, indice + _utf16(texto), {"bold": False}, "bold,backgroundColor"))
    titulos, pos = lineas_titulo_imagen(insertar), base
    for i, linea in enumerate(insertar.split("\n")):
        n = _utf16(linea)
        if i in titulos and n:
            sub.append(_p_estilo(pos, pos + n, {"bold": True, "backgroundColor": VERDE}, "bold,backgroundColor"))
        pos += n + 1
    return indice, sub


def _edicion_habitacion(celda, vieja, nueva):
    """Cambia solo el renglón de la habitación en DATOS. El texto nuevo se inserta DENTRO del viejo (después de su
    primera letra) y luego se borra lo viejo: así hereda su estilo sin depender de cómo trate la API un texto
    insertado al inicio de un párrafo. Si DATOS no tiene renglón de habitación, se inserta «COD\\n» al inicio."""
    parrafos = _parrafos(celda)
    objetivo = " ".join((vieja or "").split())
    if not objetivo:
        return parrafos[0][0], [_p_insertar(parrafos[0][0], nueva + "\n")]
    for ini, _, texto in parrafos:
        if " ".join(texto.split()) == objetivo:
            c = _utf16(texto[0])
            sub = [_p_insertar(ini + c, nueva), _p_borrar(ini, ini + c)]
            if _utf16(texto) > c:
                sub.append(_p_borrar(ini + _utf16(nueva), ini + _utf16(nueva) + _utf16(texto) - c))
            return ini, sub
    raise _Omitida("No encontré el renglón de la habitación en DATOS")


# ---- filas nuevas y movidas
def _primer_texto(celda):
    """textStyle del primer textRun con texto de la celda, o None."""
    for el in celda.get("content", []):
        for e in el.get("paragraph", {}).get("elements", []):
            run = e.get("textRun")
            if run and run.get("content", "").strip():
                return run.get("textStyle", {})
    return None


def _plantilla(t, fila, col):
    """Estilo (fuente, tamaño, negrita, color; SIN resaltado ni enlace) del primer texto de esa columna en la fila con
    paciente más cercana de la tabla (la de arriba si empatan)."""
    cercanas = sorted((i for i in t.filas_con_contenido() if i != fila), key=lambda i: (abs(i - fila), i))
    for i in cercanas:
        c = t.celdas(i)
        estilo = _primer_texto(c[col]) if col < len(c) else None
        if estilo is not None:
            return {k: v for k, v in estilo.items() if k in _COPIADOS}
    return {}


def _fila_libre(servicio_docs, doc_id, leer, indice):
    """Prepara dónde escribir en la tabla destino: la primera fila vacía después del encabezado; si no hay, inserta
    una fila debajo de la última (insertTableRow) y relee. Devuelve (_TablaApi con el documento releído, fila)."""
    tablas = _tablas_api(leer())
    if not 0 <= indice < len(tablas):
        raise _Omitida("No se encontró la tabla destino")
    t = tablas[indice]
    if t.enc is None:
        raise _Omitida("La tabla destino no tiene encabezado DATOS")
    libre = next((i for i in range(t.enc + 1, len(t.filas)) if t.vacia(i)), None)
    if libre is None:
        _lote(servicio_docs, doc_id, [{"insertTableRow": {**_p_celda(t, len(t.filas) - 1), "insertBelow": True}}])
        t = _tablas_api(leer())[indice]
        libre = len(t.filas) - 1
        if not t.vacia(libre):
            raise _Omitida("No pude agregar una fila vacía en la tabla destino")
    return t, libre


def _lote(servicio_docs, doc_id, pedidos):
    if pedidos:
        servicio_docs.documents().batchUpdate(documentId=doc_id, body={"requests": pedidos}).execute()


def _escribir_fila_nueva(t, fila, textos):
    """Pedidos que escriben `textos` (columna -> texto) en la fila vacía `fila`, cada columna por su ENCABEZADO.
    Estilo copiado de la fila con paciente más cercana; EVOLUCIÓN: 1.ª línea en negrita y el resto no;
    IMÁGENES / NOTAS: títulos en negrita + verde y el resto sin negrita. Las columnas que la tabla no tiene
    (p. ej. TRATAMIENTO en UCI 1) se saltan."""
    por_celda = []
    for campo, texto in textos.items():
        col = t.cols.get(campo)
        if col is None or not texto or col >= len(t.celdas(fila)):
            continue
        ini = t.celdas(fila)[col]["content"][0]["startIndex"]
        fin = ini + _utf16(texto)
        estilo = _plantilla(t, fila, col)
        if campo in ("EVOLUCIÓN", "IMÁGENES / NOTAS"):
            estilo.pop("bold", None)                     # solo van en negrita sus títulos
        sub = [_p_insertar(ini, texto), _p_estilo(ini, fin, estilo, _CAMPOS_FILA_NUEVA)]
        if campo == "EVOLUCIÓN":
            sub.append(_p_estilo(ini, ini + _utf16(texto.split("\n")[0]), {"bold": True}, "bold"))
        elif campo == "IMÁGENES / NOTAS":
            titulos, pos = lineas_titulo_imagen(texto), ini
            for i, linea in enumerate(texto.split("\n")):
                n = _utf16(linea)
                if i in titulos and n:
                    sub.append(_p_estilo(pos, pos + n, {"bold": True, "backgroundColor": VERDE}, "bold,backgroundColor"))
                pos += n + 1
        por_celda.append((ini, sub))
    return [r for _, sub in sorted(por_celda, key=lambda x: -x[0]) for r in sub]     # de abajo hacia arriba


def _contenido(celda):
    """Párrafos de la celda para copiarlos: [{"runs": [(texto, textStyle)], "alineacion": ...}] sin el salto de
    párrafo final. _Omitida si trae algo que no se puede reproducir (imágenes, tablas dentro de la celda…)."""
    out = []
    for el in celda.get("content", []):
        par = el.get("paragraph")
        if par is None:
            raise _Omitida("La fila trae una tabla dentro de una celda; muévela a mano")
        runs = []
        for e in par.get("elements", []):
            run = e.get("textRun")
            if run is None:
                raise _Omitida("La fila trae imágenes u otros objetos que no se pueden copiar; muévela a mano")
            runs.append([run.get("content", ""), run.get("textStyle", {})])
        if runs and runs[-1][0].endswith("\n"):
            runs[-1][0] = runs[-1][0][:-1]
        out.append({"runs": [(t, e) for t, e in runs if t], "alineacion": par.get("paragraphStyle", {}).get("alignment")})
    return out


def _texto_parrafo(par):
    return "".join(t for t, _ in par["runs"])


def _con_habitacion(parrafos, vieja, nueva):
    """En la copia de DATOS cambia el renglón de la habitación (conserva su estilo) o, si no tiene, pone uno al inicio."""
    objetivo = " ".join((vieja or "").split())
    if objetivo:
        for par in parrafos:
            if " ".join(_texto_parrafo(par).split()) == objetivo:
                par["runs"] = [(nueva, par["runs"][0][1])]
                return
        raise _Omitida("No encontré el renglón de la habitación en DATOS")
    primero = parrafos[0] if parrafos else {"runs": [], "alineacion": None}
    estilo = primero["runs"][0][1] if primero["runs"] else {}
    parrafos.insert(0, {"runs": [(nueva, estilo)], "alineacion": primero["alineacion"]})


def _escribir_copia(ini, parrafos):
    """Pedidos que escriben `parrafos` (de _contenido) al inicio de una celda vacía reproduciendo el estilo de cada
    textRun (updateTextStyle con el textStyle del run y fields «*») y la alineación de cada párrafo."""
    texto = "\n".join(_texto_parrafo(p) for p in parrafos)
    if not texto:
        return []
    sub, pos, grupos = [_p_insertar(ini, texto)], ini, []
    for par in parrafos:
        inicio = pos
        for t, estilo in par["runs"]:
            sub.append(_p_estilo(pos, pos + _utf16(t), estilo, "*"))
            pos += _utf16(t)
        pos += 1                            # su salto de párrafo (el del último es el que ya tenía la celda)
        if grupos and grupos[-1][2] == par["alineacion"]:
            grupos[-1][1] = pos
        else:
            grupos.append([inicio, pos, par["alineacion"]])
    for desde, hasta, alineacion in grupos:
        sub.append(_p_parrafo(desde, hasta, {"alignment": alineacion} if alineacion else {}, "alignment"))
    return sub


# ---- conteo «( N PACIENTES)» del título
_RE_CONTEO = re.compile(r"(\(\s*)(\d*)(\s*)(?=PACIENTES?\b)", re.I)


def _pedidos_conteo(t, cambio):
    """Pedidos que ajustan el «( N PACIENTES)» del título de la tabla: N + cambio; si el título no trae número,
    la cantidad de filas con paciente. (posición, pedidos) o None si no hay título con ese paréntesis."""
    sitios = [(ini, texto) for fila in t.filas[:t.enc if t.enc is not None else 1]
              for c in fila.get("tableCells", []) for ini, _, texto in _parrafos(c)]
    if t.previo:
        sitios.append(t.previo)
    for ini, texto in sitios:
        m = _RE_CONTEO.search(texto or "")
        if not m:
            continue
        if m.group(2):
            fin = ini + _utf16(texto[:m.end(2)])
            nuevo = str(max(0, int(m.group(2)) + cambio))
            # se inserta al final de los dígitos viejos (hereda su estilo) y luego se borran los viejos
            return fin, [_p_insertar(fin, nuevo), _p_borrar(fin - _utf16(m.group(2)), fin)]
        return ini + _utf16(texto[:m.end()]), [_p_insertar(ini + _utf16(texto[:m.end()]),
                                                           f"{len(t.filas_con_contenido())} ")]
    return None


def aplicar(servicio, url, acciones):
    """Escribe las acciones aprobadas en el KARDEX con la API de Google Docs. Orden:
    1. Ediciones de celda (un solo lote, de abajo hacia arriba): ACTUALIZAR de DX / EVOLUCIÓN / TRATAMIENTO
       (reemplazo), IMÁGENES / NOTAS (inserta los estudios nuevos arriba, sin borrar) y HABITACIÓN (solo el renglón
       de la habitación en DATOS).
    2. AGREGAR: fila nueva en la tabla destino (la primera fila vacía tras el encabezado; si no hay, insertTableRow
       debajo de la última), cada columna por ENCABEZADO, con el estilo de la fila con paciente más cercana.
    3. MOVER: copia la fila completa (texto, estilo de cada textRun y alineación) a la tabla destino con la
       habitación nueva, verifica la copia y borra la fila origen (deleteTableRow).
    4. Sube/baja en 1 el «( N PACIENTES)» de los títulos de las tablas que cambiaron.
    Entre pasos estructurales se relee el documento (documents.get) y las filas se vuelven a encontrar POR PACIENTE
    (nombre o documento de DATOS), nunca solo por el índice: si la fila ya no es ese paciente, la acción se omite.
    Devuelve (escritas: list[Accion], omitidas: list[(Accion, motivo)])."""
    doc_id = id_documento(url)
    docs = servicio.documents()

    def leer():
        return docs.get(documentId=doc_id).execute()
    escritas, omitidas, cambios = set(), [], {}
    pendientes = [a for a in acciones if a.tipo == "ACTUALIZAR" and a.fila is not None]
    for a in acciones:
        if a.tipo not in ("ACTUALIZAR", "AGREGAR", "MOVER") or (a.tipo == "ACTUALIZAR" and a.fila is None):
            omitidas.append((a, "No es una acción que se escriba sola"))

    # 1. ediciones de celda
    if pendientes:
        tablas = _tablas_api(leer())
        ediciones = []
        for a in pendientes:
            f = a.fila
            try:
                if not 0 <= f.tabla < len(tablas):
                    raise _Omitida("No se encontró la celda")
                t = tablas[f.tabla]
                i = _fila_del_paciente(t, f.fila, f.nombre, f.documento)
                if a.campo == "HABITACIÓN":
                    nueva = a.habitacion_nueva or a.nuevo
                    vieja = interpretar_datos(t.texto(i, 0))["habitacion"]
                    if vieja and normalizar(vieja) == normalizar(nueva):
                        raise _Omitida(f"La habitación ya dice «{vieja}»")
                    ediciones.append((a, _edicion_habitacion(t.celdas(i)[0], vieja, nueva)))
                    continue
                if a.campo not in _EDITABLES:
                    raise _Omitida(f"No sé escribir el campo {a.campo}")
                if not (a.insertar if a.campo == "IMÁGENES / NOTAS" else a.nuevo).strip():
                    raise _Omitida("No hay texto para escribir")
                cols = t.cols if t.enc is not None else {"DX": 1, "EVOLUCIÓN": 2, "TRATAMIENTO": 3}
                col = cols.get(a.campo)
                if col is None or col >= len(t.celdas(i)):
                    raise _Omitida(f"La tabla no tiene la columna {a.campo}")
                celda = t.celdas(i)[col]
                ediciones.append((a, _edicion_imagenes(celda, a.insertar) if a.campo == "IMÁGENES / NOTAS"
                                  else _edicion_texto(celda, a.nuevo, a.campo)))
            except _Omitida as e:
                omitidas.append((a, str(e)))
            except (IndexError, KeyError):
                omitidas.append((a, "No se encontró la celda"))
        # de abajo hacia arriba para que los índices no se desplacen
        _lote(servicio, doc_id, [r for _, (_, sub) in sorted(ediciones, key=lambda x: -x[1][0]) for r in sub])
        escritas.update(id(a) for a, _ in ediciones)

    # 2. filas nuevas
    for a in (x for x in acciones if x.tipo == "AGREGAR"):
        try:
            if a.tabla_destino is None or not a.fila_nueva.get("DATOS"):
                raise _Omitida("No se sabe en qué tabla va; agrégalo a mano")
            d = interpretar_datos(a.fila_nueva["DATOS"])
            if any(_buscar_fila(t, d["nombre"], d["documento"]) for t in _tablas_api(leer())):
                raise _Omitida("Ya está en el kardex")
            t, fila = _fila_libre(servicio, doc_id, leer, a.tabla_destino)
            _lote(servicio, doc_id, _escribir_fila_nueva(t, fila, a.fila_nueva))
            escritas.add(id(a))
            cambios[a.tabla_destino] = cambios.get(a.tabla_destino, 0) + 1
        except _Omitida as e:
            omitidas.append((a, str(e)))

    # 3. cambios de piso
    for a in (x for x in acciones if x.tipo == "MOVER"):
        try:
            _mover(servicio, doc_id, leer, a)
            escritas.add(id(a))
            cambios[a.fila.tabla] = cambios.get(a.fila.tabla, 0) - 1
            cambios[a.tabla_destino] = cambios.get(a.tabla_destino, 0) + 1
        except _Omitida as e:
            omitidas.append((a, str(e)))

    # 4. conteo de pacientes de los títulos
    if any(cambios.values()):
        tablas, pedidos = _tablas_api(leer()), []
        for indice, cambio in cambios.items():
            r = _pedidos_conteo(tablas[indice], cambio) if cambio and 0 <= indice < len(tablas) else None
            if r:
                pedidos.append(r)
        _lote(servicio, doc_id, [r for _, sub in sorted(pedidos, key=lambda x: -x[0]) for r in sub])
    return [a for a in acciones if id(a) in escritas], omitidas


def _mover(servicio, doc_id, leer, a):
    """Mueve la fila del paciente a la tabla destino (ver aplicar). _Omitida si no se puede, sin borrar nada."""
    f = a.fila
    tablas = _tablas_api(leer())
    if not (0 <= f.tabla < len(tablas) and a.tabla_destino is not None and 0 <= a.tabla_destino < len(tablas)):
        raise _Omitida("No se encontró la tabla")
    if f.tabla == a.tabla_destino:
        raise _Omitida("La tabla origen y la destino son la misma")
    origen, destino = tablas[f.tabla], tablas[a.tabla_destino]
    i = _fila_del_paciente(origen, f.fila, f.nombre, f.documento)
    if destino.enc is None:
        raise _Omitida("La tabla destino no tiene encabezado DATOS")
    if _buscar_fila(destino, f.nombre, f.documento):
        raise _Omitida("El paciente ya está en la tabla destino")
    copias = {}                             # columna destino -> párrafos; todo se valida antes de tocar el documento
    for campo, col in origen.cols.items():
        if col >= len(origen.celdas(i)):
            continue
        parrafos = _contenido(origen.celdas(i)[col])
        if not any(_texto_parrafo(p) for p in parrafos):
            continue
        if campo not in destino.cols:
            raise _Omitida(f"La tabla destino no tiene la columna {campo} y la fila tiene contenido ahí; muévela a mano")
        if campo == "DATOS" and a.habitacion_nueva:
            _con_habitacion(parrafos, interpretar_datos(origen.texto(i, col))["habitacion"], a.habitacion_nueva)
        copias[campo] = parrafos
    if "DATOS" not in copias:
        raise _Omitida("La fila no tiene DATOS")
    destino, fila = _fila_libre(servicio, doc_id, leer, a.tabla_destino)
    por_celda = [(destino.celdas(fila)[destino.cols[c]]["content"][0]["startIndex"], c) for c in copias]
    pedidos = [r for ini, c in sorted(por_celda, key=lambda x: -x[0]) for r in _escribir_copia(ini, copias[c])]
    _lote(servicio, doc_id, pedidos)
    tablas = _tablas_api(leer())            # la copia debe estar antes de borrar el original
    if not _buscar_fila(tablas[a.tabla_destino], f.nombre, f.documento, fila):
        raise _Omitida("No pude verificar la copia en la tabla destino; no borré la fila original")
    origen = tablas[f.tabla]
    i = _fila_del_paciente(origen, i, f.nombre, f.documento)
    _lote(servicio, doc_id, [{"deleteTableRow": _p_celda(origen, i)}])
