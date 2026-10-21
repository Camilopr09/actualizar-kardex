"""Documento FALSO de la API de Google Docs v1, en memoria, para probar kardex_doc.aplicar sin red.

Es fiel a lo que la escritura necesita de la API real:
* documents().get() devuelve body.content con sectionBreak, párrafos y tablas (tableRows -> tableCells -> content ->
  paragraph -> elements -> textRun con textStyle) e ÍNDICES en unidades UTF-16: la tabla ocupa 1 (inicio de tabla),
  cada fila 1 y cada celda 1 antes de su primer párrafo; cada celda termina en «\\n»; tras una tabla siempre hay
  un párrafo.
* documents().batchUpdate() aplica los pedidos EN ORDEN (cada uno sobre el documento que dejó el anterior) y de forma
  atómica (si uno falla, no queda nada). Implementa deleteContentRange, insertText, updateTextStyle,
  updateParagraphStyle, insertTableRow y deleteTableRow; cualquier otro pedido es un error.
* Reglas que la API real impone y aquí también se exigen: los índices deben ser posiciones de texto (no marcadores
  de tabla/fila/celda ni el medio de un par sustituto UTF-16), un rango no puede cruzar celdas ni tablas, no se
  puede borrar el último «\\n» de una celda, un rango vacío es un error, updateTextStyle/updateParagraphStyle
  solo cambian los campos de `fields` (lo que está en `fields` y no en el estilo vuelve a su valor por defecto;
  «*» reemplaza todo el estilo), insertTableRow crea celdas con un párrafo vacío.
* Texto insertado: hereda el estilo del carácter anterior; al inicio de un párrafo, el del carácter siguiente.
  Un «\\n» insertado parte el párrafo (los dos conservan el estilo de párrafo). Borrar un salto de párrafo une los
  párrafos y queda el estilo del primero (supuesto: la API real no lo documenta; kardex_doc no depende de eso).
* Opción `herencia_fila_nueva=True`: insertTableRow copia el estilo de texto de la fila de referencia a las celdas
  nuevas (como hace la interfaz de Docs); sirve para comprobar que lo escrito no hereda resaltados ajenos.
"""
import copy
import json


class ErrorFalso(ValueError):
    """Un pedido que la API real rechazaría (HttpError 400)."""


_CAMPOS_TEXTO = {"bold", "italic", "underline", "strikethrough", "smallCaps", "backgroundColor", "foregroundColor",
                 "fontSize", "weightedFontFamily", "baselineOffset", "link"}
_CAMPOS_PARRAFO = {"alignment", "namedStyleType", "lineSpacing", "direction", "spaceAbove", "spaceBelow",
                   "indentFirstLine", "indentStart", "indentEnd", "keepLinesTogether", "keepWithNext"}


def _u(ch):
    return 2 if ord(ch) > 0xFFFF else 1


class Parrafo:
    def __init__(self, chars=None, estilo_p=None):
        self.chars = chars or [["\n", {}]]          # [[carácter, textStyle]]; siempre termina en «\n»
        self.estilo_p = estilo_p or {}

    @property
    def largo(self):
        return sum(_u(c) for c, _ in self.chars)

    @property
    def texto(self):
        return "".join(c for c, _ in self.chars)[:-1]

    def indice_de(self, unidades):
        """Posición en `chars` de un desplazamiento en unidades UTF-16 (error si cae en medio de un par sustituto)."""
        acum = 0
        for i, (c, _) in enumerate(self.chars):
            if acum == unidades:
                return i
            acum += _u(c)
            if acum > unidades:
                raise ErrorFalso("El índice cae en medio de un par sustituto UTF-16")
        if acum == unidades:
            return len(self.chars)
        raise ErrorFalso("Índice fuera del párrafo")


class Celda:
    def __init__(self, parrafos):
        self.parrafos = parrafos or [Parrafo()]


class Fila:
    def __init__(self, celdas):
        self.celdas = celdas


class Tabla:
    def __init__(self, filas):
        self.filas = filas


# ------------------------------------------------------------------ constructores para las pruebas
def P(*runs, estilo=None, alineacion=None):
    """Párrafo con runs: cada uno es un texto o (texto, textStyle). `estilo` se aplica a los runs sin estilo propio."""
    chars = []
    for r in runs:
        texto, est = (r, estilo) if isinstance(r, str) else r
        chars.extend([c, copy.deepcopy(est or {})] for c in texto)
    chars.append(["\n", copy.deepcopy(estilo or {})])
    return Parrafo(chars, {"alignment": alineacion} if alineacion else {})


def celda(texto="", estilo=None, parrafos=None):
    """Celda: `texto` con un párrafo por renglón (todos con `estilo`), o `parrafos` (lista de P(...))."""
    if parrafos is None:
        parrafos = [P(t, estilo=estilo) for t in texto.split("\n")]
    return Celda(parrafos)


def tabla(filas):
    """filas: lista de listas de celdas (Celda o texto)."""
    return Tabla([Fila([c if isinstance(c, Celda) else celda(c) for c in f]) for f in filas])


ENC7 = ["DATOS", "DX", "EVOLUCIÓN", "TRATAMIENTO", "LABORATORIOS", "IMÁGENES / NOTAS", "PENDIENTES"]
ENC6 = ["DATOS", "DX", "EVOLUCIÓN", "LABORATORIOS", "IMÁGENES / NOTAS", "PENDIENTES"]       # UCI 1: sin TRATAMIENTO


def tabla_kardex(titulo, pacientes=(), vacias=1, encabezado=ENC7):
    """Tabla como la del kardex: fila de título (celda combinada), encabezado, pacientes y `vacias` filas vacías."""
    n = len(encabezado)
    filas = [[titulo] + [""] * (n - 1), list(encabezado)]
    filas += [list(p) + [""] * (n - len(p)) for p in pacientes]
    filas += [[""] * n for _ in range(vacias)]
    return tabla(filas)


# ------------------------------------------------------------------ el documento
class DocumentoFalso:
    def __init__(self, cuerpo, herencia_fila_nueva=False):
        """cuerpo: lista de Parrafo y Tabla (siempre debe terminar en un párrafo)."""
        self.cuerpo = list(cuerpo)
        if not self.cuerpo or isinstance(self.cuerpo[-1], Tabla):
            self.cuerpo.append(Parrafo())
        self.herencia_fila_nueva = herencia_fila_nueva
        self.lotes = []             # lista de pedidos de cada batchUpdate exitoso
        self.lecturas = 0

    # ---- lectura (JSON de la API)
    def a_json(self):
        contenido = [{"endIndex": 1, "sectionBreak": {"sectionStyle": {}}}]
        i = 1
        for el in self.cuerpo:
            if isinstance(el, Parrafo):
                e, i = self._json_parrafo(el, i)
                contenido.append(e)
            else:
                ini = i
                i += 1
                filas = []
                for f in el.filas:
                    fini = i
                    i += 1
                    celdas = []
                    for c in f.celdas:
                        cini = i
                        i += 1
                        pars = []
                        for p in c.parrafos:
                            e, i = self._json_parrafo(p, i)
                            pars.append(e)
                        celdas.append({"startIndex": cini, "endIndex": i, "content": pars, "tableCellStyle": {}})
                    filas.append({"startIndex": fini, "endIndex": i, "tableCells": celdas, "tableRowStyle": {}})
                contenido.append({"startIndex": ini, "endIndex": i,
                                  "table": {"rows": len(el.filas), "columns": len(el.filas[0].celdas),
                                            "tableRows": filas, "tableStyle": {}}})
        return {"documentId": "DOC", "title": "KARDEX", "body": {"content": contenido}}

    @staticmethod
    def _json_parrafo(p, i):
        elementos, pos = [], i
        for c, est in p.chars:
            if elementos and elementos[-1]["textRun"]["textStyle"] == est:
                elementos[-1]["textRun"]["content"] += c
                elementos[-1]["endIndex"] += _u(c)
            else:
                elementos.append({"startIndex": pos, "endIndex": pos + _u(c),
                                  "textRun": {"content": c, "textStyle": copy.deepcopy(est)}})
            pos += _u(c)
        return {"startIndex": i, "endIndex": pos,
                "paragraph": {"elements": elementos, "paragraphStyle": copy.deepcopy(p.estilo_p)}}, pos

    # ---- recorrido con índices
    def _parrafos_con_indices(self):
        """[(inicio, fin, parrafo, contenedor)] de TODOS los párrafos; contenedor = la lista que los contiene."""
        out, i = [], 1
        for el in self.cuerpo:
            if isinstance(el, Parrafo):
                out.append((i, i + el.largo, el, self.cuerpo))
                i += el.largo
            else:
                i += 1
                for f in el.filas:
                    i += 1
                    for c in f.celdas:
                        i += 1
                        for p in c.parrafos:
                            out.append((i, i + p.largo, p, c.parrafos))
                            i += p.largo
        return out

    def _tablas_con_indice(self):
        out, i = [], 1
        for el in self.cuerpo:
            if isinstance(el, Parrafo):
                i += el.largo
            else:
                out.append((i, el))
                i += 1
                for f in el.filas:
                    i += 1
                    for c in f.celdas:
                        i += 1 + sum(p.largo for p in c.parrafos)
        return out

    def _rango(self, ini, fin):
        """Párrafos cubiertos por [ini, fin) -> (lista [(inicio, fin, parrafo)], contenedor); valida el rango."""
        if ini >= fin:
            raise ErrorFalso(f"Rango vacío o invertido [{ini}, {fin})")
        todos = self._parrafos_con_indices()
        cubiertos = [(a, b, p, c) for a, b, p, c in todos if a < fin and b > ini]
        if not cubiertos or cubiertos[0][0] > ini or cubiertos[-1][1] < fin:
            raise ErrorFalso(f"El rango [{ini}, {fin}) incluye marcadores de tabla o está fuera del documento")
        cont = cubiertos[0][3]
        if any(c is not cont for *_, c in cubiertos):
            raise ErrorFalso(f"El rango [{ini}, {fin}) cruza celdas o tablas")
        for (a1, b1, *_), (a2, *_r) in zip(cubiertos, cubiertos[1:]):
            if b1 != a2:
                raise ErrorFalso(f"El rango [{ini}, {fin}) cruza una tabla")
        return [(a, b, p) for a, b, p, _ in cubiertos], cont

    def _posicion(self, indice):
        """(párrafo, contenedor, desplazamiento en unidades) de un índice de inserción (dentro de un párrafo)."""
        for a, b, p, c in self._parrafos_con_indices():
            if a <= indice < b:                       # b - 1 es justo antes del «\n»
                return p, c, indice - a
        raise ErrorFalso(f"El índice {indice} no es una posición de texto (marcador de tabla/fila/celda o fuera)")

    # ---- pedidos
    def batch_update(self, pedidos):
        if not pedidos:
            raise ErrorFalso("batchUpdate sin pedidos")
        respaldo = copy.deepcopy(self.cuerpo)
        try:
            for r in pedidos:
                if len(r) != 1:
                    raise ErrorFalso("Cada pedido debe tener exactamente una clave")
                (nombre, args), = r.items()
                metodo = getattr(self, "_p_" + nombre, None)
                if metodo is None:
                    raise ErrorFalso(f"El documento falso no implementa el pedido {nombre}")
                metodo(**args)
        except Exception:
            self.cuerpo = respaldo                    # atómico: si uno falla no queda ninguno
            raise
        self.lotes.append(copy.deepcopy(pedidos))

    def _p_insertText(self, location, text):
        if not text:
            raise ErrorFalso("insertText con texto vacío")
        if "segmentId" in location:
            raise ErrorFalso("segmentId no implementado")
        p, cont, desp = self._posicion(location["index"])
        k = p.indice_de(desp)
        est = copy.deepcopy(p.chars[k - 1][1] if k > 0 else p.chars[k][1])    # hereda del anterior; al inicio, del siguiente
        piezas = text.split("\n")
        cola = p.chars[k:]
        nuevos = []
        for j, pieza in enumerate(piezas):
            chars = ([] if j else p.chars[:k]) + [[c, copy.deepcopy(est)] for c in pieza]
            if j < len(piezas) - 1:
                chars.append(["\n", copy.deepcopy(est)])
            else:
                chars += cola
            nuevos.append(Parrafo(chars, copy.deepcopy(p.estilo_p)))
        pos = cont.index(p)
        cont[pos:pos + 1] = nuevos

    def _p_deleteContentRange(self, range):
        ini, fin = range["startIndex"], range["endIndex"]
        cubiertos, cont = self._rango(ini, fin)
        # el último «\n» de la celda (o del cuerpo) no se puede borrar
        a_l, b_l, ultimo = cubiertos[-1]
        if fin == b_l and cont[-1] is ultimo:
            raise ErrorFalso("No se puede borrar el último salto de línea de la celda/documento")
        a0, _, primero = cubiertos[0]
        k0 = primero.indice_de(ini - a0)
        k1 = ultimo.indice_de(fin - a_l)
        nuevos = primero.chars[:k0] + ultimo.chars[k1:]
        pos = cont.index(primero)
        resto = cont.index(ultimo) - pos
        del cont[pos + 1:pos + 1 + resto]
        if not nuevos or nuevos[-1][0] != "\n":     # se borró el «\n» del último: se une con el párrafo siguiente
            sig = cont[pos + 1] if pos + 1 < len(cont) else None
            if not isinstance(sig, Parrafo):
                raise ErrorFalso("No se puede borrar el salto de línea que está antes de una tabla")
            nuevos += sig.chars
            del cont[pos + 1]
        primero.chars = nuevos

    def _p_updateTextStyle(self, range, textStyle, fields):
        cubiertos, _ = self._rango(range["startIndex"], range["endIndex"])
        campos = [f.strip() for f in fields.split(",") if f.strip()]
        if not campos:
            raise ErrorFalso("fields vacío")
        if campos != ["*"] and not set(campos) <= _CAMPOS_TEXTO:
            raise ErrorFalso(f"Campos de texto desconocidos: {set(campos) - _CAMPOS_TEXTO}")
        for a, b, p in cubiertos:
            pos = a
            for ch in p.chars:
                if range["startIndex"] <= pos < range["endIndex"]:
                    if campos == ["*"]:
                        ch[1] = copy.deepcopy(textStyle)
                    else:
                        for f in campos:
                            if f in textStyle:
                                ch[1][f] = copy.deepcopy(textStyle[f])
                            else:
                                ch[1].pop(f, None)
                pos += _u(ch[0])

    def _p_updateParagraphStyle(self, range, paragraphStyle, fields):
        cubiertos, _ = self._rango(range["startIndex"], range["endIndex"])
        campos = [f.strip() for f in fields.split(",") if f.strip()]
        if not campos:
            raise ErrorFalso("fields vacío")
        if campos != ["*"] and not set(campos) <= _CAMPOS_PARRAFO:
            raise ErrorFalso(f"Campos de párrafo desconocidos: {set(campos) - _CAMPOS_PARRAFO}")
        for _, _, p in cubiertos:
            if campos == ["*"]:
                p.estilo_p = copy.deepcopy(paragraphStyle)
            else:
                for f in campos:
                    if f in paragraphStyle:
                        p.estilo_p[f] = copy.deepcopy(paragraphStyle[f])
                    else:
                        p.estilo_p.pop(f, None)

    def _tabla_de(self, tableCellLocation):
        ini = tableCellLocation["tableStartLocation"]["index"]
        for i, t in self._tablas_con_indice():
            if i == ini:
                f, c = tableCellLocation["rowIndex"], tableCellLocation["columnIndex"]
                if not (0 <= f < len(t.filas) and 0 <= c < len(t.filas[f].celdas)):
                    raise ErrorFalso("Fila o columna fuera de la tabla")
                return t, f
        raise ErrorFalso(f"El índice {ini} no es el inicio de una tabla")

    def _p_insertTableRow(self, tableCellLocation, insertBelow):
        t, f = self._tabla_de(tableCellLocation)
        ref = t.filas[f]
        celdas = []
        for c in ref.celdas:
            nueva = Parrafo()
            if self.herencia_fila_nueva:
                nueva.chars[0][1] = copy.deepcopy(c.parrafos[0].chars[0][1])      # estilo del texto de la referencia
            celdas.append(Celda([nueva]))
        t.filas.insert(f + 1 if insertBelow else f, Fila(celdas))

    def _p_deleteTableRow(self, tableCellLocation):
        t, f = self._tabla_de(tableCellLocation)
        if len(t.filas) == 1:
            raise ErrorFalso("No se puede borrar la única fila de la tabla")
        del t.filas[f]

    # ---- ayudas para las pruebas
    def tablas(self):
        return [t for _, t in self._tablas_con_indice()]

    def texto(self, t, f, c):
        """Texto de la celda (un renglón por párrafo, sin el «\\n» final)."""
        return "\n".join(p.texto for p in self.tablas()[t].filas[f].celdas[c].parrafos)

    def fila(self, t, f):
        return [self.texto(t, f, c) for c in range(len(self.tablas()[t].filas[f].celdas))]

    def titulo(self, t):
        return self.texto(t, 0, 0)

    def estilos(self, t, f, c):
        """[(texto, textStyle)] de la celda agrupando caracteres vecinos con el mismo estilo (sin los «\\n» finales)."""
        out = []
        for j, p in enumerate(self.tablas()[t].filas[f].celdas[c].parrafos):
            if j:
                out.append(("\n", None))
            for ch, est in p.chars[:-1]:
                if out and out[-1][1] == est:
                    out[-1] = (out[-1][0] + ch, est)
                else:
                    out.append((ch, est))
        return out

    def estilo_de(self, t, f, c, fragmento):
        """textStyle de la primera aparición de `fragmento` en la celda (debe tener un solo estilo)."""
        ests = {json.dumps(e, sort_keys=True) for e in self._estilos_de(t, f, c, fragmento)}
        assert len(ests) == 1, f"{fragmento!r} tiene {len(ests)} estilos distintos: {ests}"
        return json.loads(next(iter(ests)))

    def _estilos_de(self, t, f, c, fragmento):
        todo = [ch_est for p in self.parrafos(t, f, c) for ch_est in p.chars]
        s = "".join(ch for ch, _ in todo)
        k = s.index(fragmento)
        return [est for _, est in todo[k:k + len(fragmento)]]

    def parrafos_cuerpo(self):
        return [el for el in self.cuerpo if isinstance(el, Parrafo)]

    def parrafos(self, t, f, c):
        return self.tablas()[t].filas[f].celdas[c].parrafos

    def alineaciones(self, t, f, c):
        return [p.estilo_p.get("alignment") for p in self.parrafos(t, f, c)]

    def servicio(self):
        return ServicioFalso(self)


class _Solicitud:
    def __init__(self, f):
        self._f = f

    def execute(self):
        return self._f()


class ServicioFalso:
    """Lo que devuelve googleapiclient.discovery.build('docs', 'v1'): servicio.documents().get / batchUpdate."""

    def __init__(self, doc):
        self.doc = doc

    def documents(self):
        return self

    def get(self, documentId, **_):
        def ejecutar():
            self.doc.lecturas += 1
            return self.doc.a_json()
        return _Solicitud(ejecutar)

    def batchUpdate(self, documentId, body):
        def ejecutar():
            self.doc.batch_update(body["requests"])
            return {"documentId": documentId, "replies": [{} for _ in body["requests"]]}
        return _Solicitud(ejecutar)


# ------------------------------------------------------------------ exportación HTML (como la de Google)
def a_html(doc):
    """HTML parecido a la exportación de Google: un <p> por párrafo y <table> por tabla (kardex_doc lo lee igual)."""
    def celda_html(c):
        return "<td>" + "".join(f"<p>{p.texto}</p>" if p.texto else "<p></p>" for p in c.parrafos) + "</td>"
    partes = ["<html><body>"]
    for el in doc.cuerpo:
        if isinstance(el, Parrafo):
            if el.texto:
                partes.append(f"<p>{el.texto}</p>")
        else:
            partes.append("<table>" + "".join("<tr>" + "".join(celda_html(c) for c in f.celdas) + "</tr>"
                                              for f in el.filas) + "</table>")
    partes.append("</body></html>")
    return "".join(partes)
