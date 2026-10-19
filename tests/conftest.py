import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def datos_temporales(tmp_path, monkeypatch):
    """Ninguna prueba toca la carpeta de datos real."""
    d = tmp_path / "datos"
    monkeypatch.setenv("KARDEX_DATOS", str(d))
    monkeypatch.delenv("KARDEX_CHROME", raising=False)
    return d
