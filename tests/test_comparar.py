from comparar import FilaKardex, PacienteSistema, comparar


def _fila(nombre="JUAN PEREZ", hab="H-1", servicio="PISO 3", **kw):
    return FilaKardex(tabla=0, fila=1, servicio=servicio, datos=f"{nombre}\n{hab}", **kw)


def _por_tipo(acciones, tipo):
    return [a for a in acciones if a.tipo == tipo]


def test_actualizar_lleva_servicio_y_habitacion():
    p = PacienteSistema("PEREZ GOMEZ JUAN", "H-1", "Hospitalización", dx="NUEVO", encontrado_detalle=True)
    (a,) = comparar([p], [_fila(dx="VIEJO")])
    assert (a.tipo, a.campo, a.actual, a.nuevo) == ("ACTUALIZAR", "DX", "VIEJO", "NUEVO")
    assert (a.servicio, a.habitacion) == ("PISO 3", "H-1")
    assert a.automatica


def test_agregar_resumen():
    p = PacienteSistema("MORA QUINTERO ESPERANZA", "UCI5-09", "Urgencias", medico="FABIAN",
                        fecha="19/10/2026", dx="CHOQUE SEPTICO")
    (a,) = comparar([p], [])
    assert a.tipo == "AGREGAR" and a.fila is None and not a.automatica
    assert a.actual == "" and a.campo == ""
    assert a.nuevo.splitlines() == ["MORA QUINTERO ESPERANZA · UCI5-09", "DX: CHOQUE SEPTICO",
                                    "Última evolución: 19/10/2026, FABIAN"]
    assert (a.servicio, a.habitacion) == ("Urgencias", "UCI5-09")


def test_agregar_sin_detalle():
    (a,) = comparar([PacienteSistema("ANA LOPEZ RUIZ", "", "Urgencias")], [])
    assert a.nuevo == "ANA LOPEZ RUIZ"


def test_retirar_resumen():
    (a,) = comparar([], [_fila("ROJAS TELLEZ CLARA", "H-5", "PISO 6", dx="HTA")])
    assert a.tipo == "RETIRAR" and a.nuevo == "" and a.campo == ""
    assert a.actual.splitlines() == ["ROJAS TELLEZ CLARA · H-5", "DX: HTA"]
    assert (a.servicio, a.habitacion) == ("PISO 6", "H-5")


def test_revisar_habitacion_y_aviso():
    p = PacienteSistema("PEREZ GOMEZ JUAN", "H-9", "Hospitalización", aviso="Sin hoja de evolución")
    acc = _por_tipo(comparar([p], [_fila()]), "REVISAR")
    assert {a.campo for a in acc} == {"", "HABITACIÓN"}
    hab = next(a for a in acc if a.campo == "HABITACIÓN")
    assert (hab.actual, hab.nuevo) == ("H-1", "H-9")
    assert all(a.servicio == "PISO 3" and a.habitacion == "H-1" and not a.automatica for a in acc)


def test_parsear_identificacion():
    from comparar import parsear_identificacion
    assert parsear_identificacion("CC - 1044618156") == ("CC", "1044618156")
    assert parsear_identificacion("RC -\n1108769206") == ("RC", "1108769206")
    assert parsear_identificacion("CC 63338316") == ("CC", "63338316")
    assert parsear_identificacion("") == ("", "")


def test_misma_habitacion():
    from comparar import misma_habitacion as m
    assert m("607", "6PISO-607") and m("426", "4PISO-426") and m("305B", "3PISO-305B") and m("332A", "3PISO-332A")
    assert m("9", "HOS82-09") and m("09", "HOS82-09") and m("CUB 9", "HOS82-09") and m("CUB 12", "H4CAM-12")
    assert m("PASILLO", "6PISO-607") and m("", "6PISO-607") and m("607", "")      # sin número: no se puede comparar
    assert m("2-01", "2-01") and m("U-03", "U-03")
    assert not m("405", "4PISO-408") and not m("305B", "3PISO-305") and not m("4-05", "4-08")
    assert not m("UCI5-09", "UCI5-02") and not m("2-01", "3-01")


def test_emparejar_por_documento_sin_importar_el_nombre():
    from comparar import buscar_paciente
    a = PacienteSistema("JAIRO ANDRES MONTENEGRO VEGA", "PEDIA-07", "Hospitalización", documento="1020304057")
    b = PacienteSistema("HERNAN DARIO PALACIOS", "6PISO-601", "Hospitalización", documento="1099999999")
    assert buscar_paciente("HERNAN PALACIOS", "1020304057", [b, a]) is a                # el documento manda
    assert buscar_paciente("HERNAN PALACIOS", "", [b, a]) is b                          # sin documento, por nombre
    assert buscar_paciente("HERNAN PALACIOS", "1020300000", [b, a]) is None             # otro documento: otra persona


def test_habitacion_corta_del_kardex_no_genera_revisar():
    p = PacienteSistema("PEREZ GOMEZ JUAN", "6PISO-607", "Hospitalización", encontrado_detalle=True)
    assert not _por_tipo(comparar([p], [_fila(hab="607")]), "REVISAR")
    assert not _por_tipo(comparar([p], [_fila(hab="PASILLO")]), "REVISAR")
    (r,) = _por_tipo(comparar([p], [_fila(hab="608")]), "REVISAR")
    assert (r.campo, r.actual, r.nuevo) == ("HABITACIÓN", "608", "6PISO-607")


def test_modo_preferido():
    from comparar import modo_preferido
    assert modo_preferido("URGENCIAS ( 5 PACIENTES)") == "Urgencias" and modo_preferido("PISO 3") == "Hospitalización"
