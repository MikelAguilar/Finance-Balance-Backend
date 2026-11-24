class DomainError(Exception):
    """Regla del negocio que no se cumple. La capa HTTP la traduce a un código de estado."""


class EmailAlreadyRegistered(DomainError):
    pass


class WeakPassword(DomainError):
    pass


class InvalidCredentials(DomainError):
    """Correo inexistente o contraseña incorrecta: a propósito no se distingue cuál."""


class InvalidToken(DomainError):
    """Token de acceso o refresh token inválido, vencido, o de una sesión revocada."""


class WrongCurrentPassword(DomainError):
    pass


class SessionNotFound(DomainError):
    """La sesión no existe o es de otro usuario: a propósito no se distingue cuál."""


class TooManyAttempts(DomainError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Demasiados intentos. Intenta de nuevo en {retry_after_seconds} s.")
        self.retry_after_seconds = retry_after_seconds
