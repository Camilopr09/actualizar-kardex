import json

import pytest

import secreto


def test_ida_y_vuelta(tmp_path):
    assert secreto.leer_hospital(tmp_path) is None
    secreto.guardar_hospital(tmp_path, " medico.prueba ", "Clave-Ñandú-123")
    assert secreto.leer_hospital(tmp_path) == {"usuario": "medico.prueba", "clave": "Clave-Ñandú-123"}
    secreto.quitar_hospital(tmp_path)
    assert secreto.leer_hospital(tmp_path) is None
    secreto.quitar_hospital(tmp_path)              # idempotente


def test_el_archivo_no_es_json_en_texto_plano(tmp_path):
    secreto.guardar_hospital(tmp_path, "usuario1", "ClaveSecreta-987")
    crudo = (tmp_path / secreto.NOMBRE_ARCHIVO).read_bytes()
    assert b"ClaveSecreta-987" not in crudo
    with pytest.raises(ValueError):
        json.loads(crudo)


@pytest.mark.parametrize("usuario,clave", [("", "x"), ("  ", "x"), ("u", ""), (None, "x"), ("u", None)])
def test_vacios_no_se_guardan(tmp_path, usuario, clave):
    with pytest.raises(ValueError):
        secreto.guardar_hospital(tmp_path, usuario, clave)
    assert not (tmp_path / secreto.NOMBRE_ARCHIVO).exists()


def test_archivo_ilegible_se_trata_como_sin_guardar(tmp_path):
    (tmp_path / secreto.NOMBRE_ARCHIVO).write_bytes(b"basura")
    assert secreto.leer_hospital(tmp_path) is None
