"""Pruebas de propiedades: en lugar de unos pocos ejemplos, Hypothesis genera cientos de entradas
(textos Unicode raros, fechas extremas, identificadores al azar) y busca una que rompa la regla.
Si la encuentra, la reduce al caso más simple y la muestra.
"""

import string
import unicodedata
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import ValidationError

from auth_service.domain.errors import InvalidToken, WeakPassword
from auth_service.domain.model import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    Session,
    check_password_policy,
    normalize_email,
)
from auth_service.infrastructure.security import JwtTokenService
from auth_service.interfaces.http.auth import RegisterRequest, UpdateProfileRequest

SECRET = "s" * 32
TOKENS = JwtTokenService(SECRET, access_token_minutes=15)

# Fechas con zona horaria entre 2000 y 2100 (las que tiene sentido manejar).
moments = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)
)
uuids = st.uuids()


# ------------------------------------------------------------------ correo y contraseña


@given(st.text())
def test_normalizing_email_is_idempotent(email: str) -> None:
    once = normalize_email(email)

    assert normalize_email(once) == once
    assert once == once.strip()
    assert once == once.lower()


@given(st.emails())
def test_any_casing_and_padding_of_an_email_normalizes_to_the_same(email: str) -> None:
    variant = "  " + email.upper() + "\t"

    assert normalize_email(variant) == normalize_email(email)


@given(st.text(max_size=MAX_PASSWORD_LENGTH + 20))
def test_password_policy_depends_only_on_length(password: str) -> None:
    valid = MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH
    if valid:
        check_password_policy(password)
    else:
        with pytest.raises(WeakPassword):
            check_password_policy(password)


@given(
    st.text(
        alphabet=st.characters(min_codepoint=0x1F300, max_codepoint=0x1FAFF),
        min_size=12,
        max_size=MAX_PASSWORD_LENGTH,
    )
)
def test_emoji_passwords_count_characters_not_bytes(password: str) -> None:
    # 12 emojis son 48 bytes, pero 12 caracteres: deben ser válidos.
    check_password_policy(password)


# ------------------------------------------------------------------ ciclo de vida de una sesión


def make_session(created: datetime, lifetime: timedelta) -> Session:
    return Session(
        id=UUID(int=1),
        user_id=UUID(int=2),
        device_id="d",
        device_name="D",
        refresh_token_hash="a" * 64,
        created_at=created,
        last_used_at=created,
        expires_at=created + lifetime,
    )


@given(
    moments,
    st.timedeltas(min_value=timedelta(seconds=1), max_value=timedelta(days=365)),
    st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=800)),
)
def test_session_is_active_exactly_until_it_expires(created, lifetime, elapsed) -> None:
    session = make_session(created, lifetime)

    assert session.is_active(created + elapsed) == (elapsed < lifetime)


@given(
    moments,
    st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=100)),
    st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=100)),
)
def test_once_revoked_a_session_never_becomes_active_again(created, until_revoke, later) -> None:
    session = make_session(created, timedelta(days=90))
    revoked_at = created + until_revoke

    session.revoke(revoked_at)
    session.revoke(revoked_at + later)

    assert session.revoked_at == revoked_at
    assert not session.is_active(revoked_at + later)


@given(
    moments,
    st.lists(
        st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=60)), min_size=1, max_size=20
    ),
)
def test_rotation_keeps_only_the_previous_hash_and_extends_from_last_use(created, gaps) -> None:
    session = make_session(created, timedelta(days=90))
    now = created
    hashes = ["a" * 64]
    for i, gap in enumerate(gaps):
        now += gap
        new_hash = f"{i:064d}"
        session.rotate(new_hash, now, timedelta(days=90))
        hashes.append(new_hash)

        assert session.refresh_token_hash == hashes[-1]
        assert session.previous_refresh_token_hash == hashes[-2]
        assert session.last_used_at == now
        assert session.expires_at == now + timedelta(days=90)


# ------------------------------------------------------------------ tokens


@given(uuids, uuids, moments)
def test_access_token_round_trips_any_user_and_session(user_id, session_id, now) -> None:
    token, expires_at = TOKENS.issue_access_token(user_id, session_id, now)

    assert TOKENS.decode_access_token(token, now) == (user_id, session_id)
    assert TOKENS.decode_access_token(token, expires_at - timedelta(seconds=1)) == (
        user_id,
        session_id,
    )
    with pytest.raises(InvalidToken):
        TOKENS.decode_access_token(token, expires_at)


@given(uuids, uuids, moments, st.text(min_size=32, max_size=64))
def test_a_token_signed_with_any_other_secret_is_rejected(user_id, session_id, now, other) -> None:
    assume(other != SECRET)
    token, _ = JwtTokenService(other, 15).issue_access_token(user_id, session_id, now)

    with pytest.raises(InvalidToken):
        TOKENS.decode_access_token(token, now)


@given(st.text(max_size=500))
def test_decoding_arbitrary_text_only_ever_raises_invalid_token(text: str) -> None:
    # Nunca debe escapar otra excepción (que acabaría en un error 500).
    with pytest.raises(InvalidToken):
        TOKENS.decode_access_token(text, datetime(2026, 1, 1, tzinfo=UTC))


@given(uuids, uuids, moments, st.data())
def test_changing_any_claim_breaks_the_signature(user_id, session_id, now, data) -> None:
    token, _ = TOKENS.issue_access_token(user_id, session_id, now)
    claims = jwt.decode(token, options={"verify_signature": False})
    field = data.draw(st.sampled_from(sorted(claims)))
    claims[field] = data.draw(st.one_of(st.integers(), st.text(), st.none()))
    assume(claims[field] != jwt.decode(token, options={"verify_signature": False})[field])
    header, _, signature = token.split(".")
    forged_payload = jwt.encode(claims, "x" * 32, algorithm="HS256").split(".")[1]

    with pytest.raises(InvalidToken):
        TOKENS.decode_access_token(f"{header}.{forged_payload}.{signature}", now)


@given(
    st.lists(
        st.text(alphabet=string.printable, min_size=1, max_size=60),
        min_size=2,
        max_size=50,
        unique=True,
    )
)
def test_refresh_token_hashes_are_fixed_length_hex_and_distinct(tokens: list[str]) -> None:
    hashes = [TOKENS.hash_refresh_token(t) for t in tokens]

    assert all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in hashes)
    assert len(set(hashes)) == len(tokens)
    assert hashes == [TOKENS.hash_refresh_token(t) for t in tokens]


def test_new_refresh_tokens_do_not_repeat() -> None:
    generated = {TOKENS.new_refresh_token() for _ in range(5000)}

    assert len(generated) == 5000


@given(st.text(max_size=150), st.sampled_from(["first_name", "last_name"]))
def test_accepted_names_are_trimmed_short_and_without_control_characters(
    text: str, field: str
) -> None:
    def has_control(value: str) -> bool:
        return any(unicodedata.category(c) == "Cc" for c in value)

    try:
        name = getattr(UpdateProfileRequest(**{field: text}), field)
    except ValidationError:
        # Solo se rechaza lo que de verdad incumple una regla.
        stripped = text.strip()
        assert not stripped or len(stripped) > 100 or has_control(text)
        return
    assert name == text.strip()
    assert 1 <= len(name) <= 100
    assert not has_control(name)


@given(st.text(max_size=150), st.text(max_size=150))
def test_registration_accepts_names_exactly_when_the_profile_does(first: str, last: str) -> None:
    """Registro y perfil aplican la misma regla: lo que uno acepta, el otro también."""

    def accepted(model, **fields) -> bool:
        try:
            model(**fields)
        except ValidationError:
            return False
        return True

    base = {"email": "luis@example.com", "password": "x" * 12}
    assert accepted(RegisterRequest, **base, first_name=first, last_name=last) == (
        accepted(UpdateProfileRequest, first_name=first)
        and accepted(UpdateProfileRequest, last_name=last)
    )
