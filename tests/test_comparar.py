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
