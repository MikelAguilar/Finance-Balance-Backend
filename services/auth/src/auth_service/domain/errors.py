class DomainError(Exception):
    """Regla del negocio que no se cumple. La capa HTTP la traduce a un código de estado."""


class EmailAlreadyRegistered(DomainError):
    pass


class WeakPassword(DomainError):
    pass


class InvalidCredentials(DomainError):
    """Correo inexistente o contraseña incorrecta: a propósito no se distingue cuál."""
