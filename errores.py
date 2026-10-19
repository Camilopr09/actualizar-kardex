"""Errores propios de la app (el código lo usa la interfaz para mostrar la pantalla adecuada)."""

CODIGOS = ("sesion", "kardex", "agenda", "navegador", "credenciales", "otro")


class ErrorApp(Exception):
    """Error esperado. codigo: sesion | kardex | agenda | navegador | credenciales | otro."""

    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo = codigo if codigo in CODIGOS else "otro"
        self.mensaje = mensaje


class Cancelado(Exception):
    """La persona canceló la tarea en curso."""
