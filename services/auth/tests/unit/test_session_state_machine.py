"""Máquina de estados: Hypothesis combina acciones al azar (iniciar sesión en varios dispositivos,
renovar, reutilizar tokens viejos, cerrar sesión, cerrar otro dispositivo desde la lista, cambiar
la contraseña, cambiar el nombre, fallar contraseñas y dejar pasar el tiempo) y, después de cada
paso, comprueba que las reglas del negocio sigan cumpliéndose. Es la forma de encontrar
combinaciones que a nadie se le ocurriría escribir a mano.
"""

from datetime import timedelta

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from auth_service.application.use_cases import (
    Authenticate,
    ChangePassword,
    GetProfile,
    ListSessions,
    LogIn,
    LogOut,
    RefreshSession,
    RegisterUser,
    RevokeSession,
    UpdateProfile,
)
from auth_service.domain.errors import (
    InvalidCredentials,
    InvalidToken,
    TooManyAttempts,
    WeakPassword,
    WrongCurrentPassword,
)

from .fakes import FakeClock, FakeHasher, FakeTokens, FakeUnitOfWork

EMAIL = "luis@example.com"
DEVICES = st.sampled_from(["telefono", "tableta", "laptop"])
PASSWORDS = ["contraseña número uno", "contraseña número dos", "contraseña número tres"]


class SessionLifecycle(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.uow = FakeUnitOfWork()
        self.clock = FakeClock()
        hasher, tokens = FakeHasher(), FakeTokens()
        factory = lambda: self.uow  # noqa: E731
        self.log_in = LogIn(
            factory, hasher, tokens, self.clock, 90, max_attempts=5, window_minutes=15
        )
        self.refresh = RefreshSession(factory, tokens, self.clock, 90)
        self.authenticate = Authenticate(factory, tokens, self.clock)
        self.change = ChangePassword(factory, hasher, self.clock)
        self.log_out = LogOut(factory, self.clock)
        self.list_sessions = ListSessions(factory, self.clock)
        self.revoke = RevokeSession(factory, self.clock)
        self.update_profile = UpdateProfile(factory)
        self.get_profile = GetProfile(factory)
        self.user_id = RegisterUser(factory, hasher, self.clock).execute(EMAIL, PASSWORDS[0]).id
        self.password = PASSWORDS[0]
        self.name: str | None = None
        # Lo que el cliente de cada dispositivo cree tener: tokens vigentes y tokens ya cambiados.
        self.current: dict[str, tuple[str, str]] = {}  # dispositivo -> (acceso, refresh)
        self.stale: dict[str, list[str]] = {}  # dispositivo -> refresh tokens ya rotados

    # ------------------------------------------------------------------ acciones

    @rule(device=DEVICES)
    def log_in_on(self, device: str) -> None:
        try:
            result = self.log_in.execute(EMAIL, self.password, device, device.title())
        except TooManyAttempts:
            return
        self.current[device] = (result.access_token, result.refresh_token)

    @rule(device=DEVICES)
    def fail_password(self, device: str) -> None:
        try:
            self.log_in.execute(EMAIL, "contraseña equivocada", device, device)
        except (InvalidCredentials, TooManyAttempts):
            return
        raise AssertionError("Una contraseña equivocada nunca debe iniciar sesión.")

    @precondition(lambda self: self.current)
    @rule(data=st.data())
    def refresh_current(self, data) -> None:
        device = data.draw(st.sampled_from(sorted(self.current)))
        access, refresh = self.current[device]
        session = self._session_of(refresh)
        should_work = session is not None and session.is_active(self.clock.now())
        try:
            result = self.refresh.execute(refresh)
        except InvalidToken:
            assert not should_work, "Un refresh token vigente de una sesión activa fue rechazado."
            del self.current[device]
            return
        assert should_work, "Se renovó una sesión que no estaba activa."
        self.stale.setdefault(device, []).append(refresh)
        self.current[device] = (result.access_token, result.refresh_token)

    @precondition(lambda self: any(self.stale.values()))
    @rule(data=st.data())
    def reuse_stale_token(self, data) -> None:
        device = data.draw(st.sampled_from(sorted(d for d, t in self.stale.items() if t)))
        old = data.draw(st.sampled_from(self.stale[device]))
        # ¿Es el refresh token inmediatamente anterior de una sesión todavía abierta?
        victim = self.uow.sessions.get_by_previous_refresh_hash(f"sha:{old}")
        victim = victim if victim is not None and victim.revoked_at is None else None
        try:
            self.refresh.execute(old)
        except InvalidToken:
            pass
        else:
            raise AssertionError("Un refresh token ya usado nunca debe servir.")
        if victim is not None:
            assert victim.revoked_at == self.clock.now(), "La reutilización no revocó la sesión."
        # Si la sesión quedó revocada, el cliente de ese dispositivo la pierde.
        if device in self.current:
            session = self._session_of(self.current[device][1])
            if session is None or session.revoked_at is not None:
                del self.current[device]

    @precondition(lambda self: self.current)
    @rule(data=st.data())
    def log_out_one(self, data) -> None:
        device = data.draw(st.sampled_from(sorted(self.current)))
        access, _ = self.current.pop(device)
        try:
            context = self.authenticate.execute(access)
        except InvalidToken:
            return
        self.log_out.execute(context.session_id)
        try:
            self.authenticate.execute(access)
        except InvalidToken:
            return
        raise AssertionError("El token de una sesión cerrada siguió sirviendo.")

    @precondition(lambda self: self.current)
    @rule(data=st.data(), new_password=st.sampled_from(PASSWORDS + ["corta"]))
    def change_password(self, data, new_password: str) -> None:
        device = data.draw(st.sampled_from(sorted(self.current)))
        try:
            context = self.authenticate.execute(self.current[device][0])
        except InvalidToken:
            return
        try:
            self.change.execute(context.user_id, context.session_id, self.password, new_password)
        except WeakPassword:
            assert len(new_password) < 12
            return
        except WrongCurrentPassword:
            raise AssertionError("La contraseña actual correcta fue rechazada.") from None
        self.password = new_password
        # Los demás dispositivos quedan fuera.
        self.current = {device: self.current[device]}

    @precondition(lambda self: len(self.current) >= 1)
    @rule(data=st.data())
    def revoke_from_device_list(self, data) -> None:
        """Desde un dispositivo, cierra otro (o el mismo) usando la lista de dispositivos."""
        actor = data.draw(st.sampled_from(sorted(self.current)))
        try:
            self.authenticate.execute(self.current[actor][0])
        except InvalidToken:
            return
        listed = self.list_sessions.execute(self.user_id)
        # Orden por dispositivo: los id son aleatorios y Hypothesis necesita repetir la elección.
        target = data.draw(st.sampled_from(sorted(listed, key=lambda s: s.device_id)))
        self.revoke.execute(self.user_id, target.id)
        for access, _ in self.current.values():
            try:
                context = self.authenticate.execute(access)
            except InvalidToken:
                continue
            assert context.session_id != target.id, "La sesión cerrada siguió sirviendo."
        self.current = {
            d: t for d, t in self.current.items() if self._session_of(t[1]) is not target
        }

    @rule(name=st.one_of(st.none(), st.sampled_from(["Luis", "María José", "📱"])))
    def rename(self, name: str | None) -> None:
        self.update_profile.execute(self.user_id, name)
        self.name = name

    @rule(minutes=st.integers(min_value=1, max_value=60 * 24 * 40))
    def time_passes(self, minutes: int) -> None:
        self.clock.advance(timedelta(minutes=minutes))

    # ------------------------------------------------------- reglas que siempre se cumplen

    @invariant()
    def at_most_one_active_session_per_device(self) -> None:
        now = self.clock.now()
        active = [s.device_id for s in self.uow.sessions.items if s.revoked_at is None]
        assert len(active) == len(set(active))
        assert all(s.revoked_at is None or s.revoked_at <= now for s in self.uow.sessions.items)

    @invariant()
    def access_tokens_only_work_for_active_sessions(self) -> None:
        now = self.clock.now()
        for access, _ in self.current.values():
            try:
                context = self.authenticate.execute(access)
            except InvalidToken:
                continue
            session = self.uow.sessions.get(context.session_id)
            assert session is not None and session.is_active(now)

    @invariant()
    def device_list_shows_exactly_the_active_sessions(self) -> None:
        now = self.clock.now()
        listed = self.list_sessions.execute(self.user_id)
        active = {s.id for s in self.uow.sessions.items if s.is_active(now)}
        assert {s.id for s in listed} == active
        uses = [s.last_used_at for s in listed]
        assert uses == sorted(uses, reverse=True)

    @invariant()
    def name_survives_every_other_action(self) -> None:
        assert self.get_profile.execute(self.user_id).name == self.name

    @invariant()
    def never_more_than_five_recent_failures_without_blocking(self) -> None:
        window_start = self.clock.now() - timedelta(minutes=15)
        recent = self.uow.login_attempts.list_failures_since(EMAIL, window_start)
        assert len(recent) <= 5

    @invariant()
    def refresh_tokens_are_never_stored_in_plain_text(self) -> None:
        stored = {s.refresh_token_hash for s in self.uow.sessions.items}
        stored |= {s.previous_refresh_token_hash for s in self.uow.sessions.items}
        for _, refresh in self.current.values():
            assert refresh not in stored

    def _session_of(self, refresh_token: str):
        return self.uow.sessions.get_by_refresh_hash(f"sha:{refresh_token}")


TestSessionLifecycle = SessionLifecycle.TestCase
