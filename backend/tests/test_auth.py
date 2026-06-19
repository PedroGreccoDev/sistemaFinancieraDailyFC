from __future__ import annotations

import uuid

import pytest

from app.core import auth
from app.db.models import Usuario
from app.services.exceptions import ServiceError


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeDB:
    """Stand-in mínimo de Session: solo implementa `.get(Model, id)`."""

    def __init__(self, *usuarios: Usuario) -> None:
        self._by_id = {u.id: u for u in usuarios}

    def get(self, _model, pk):  # noqa: ANN001
        return self._by_id.get(pk)


def _usuario(*, is_admin: bool = False, activo: bool = True, ver: int = 0) -> Usuario:
    u = Usuario(
        id=uuid.uuid4(),
        username="tester",
        password_hash=auth.hash_password("secret123"),
        is_admin=is_admin,
        activo=activo,
        token_version=ver,
    )
    return u


# ── Contraseñas ──────────────────────────────────────────────────────────────

def test_hash_password_roundtrip() -> None:
    h = auth.hash_password("mi-clave-segura")
    assert h != "mi-clave-segura"
    assert auth.verify_password("mi-clave-segura", h)
    assert not auth.verify_password("otra", h)


# ── JWT de sesión ────────────────────────────────────────────────────────────

def test_token_roundtrip_lleva_sub_y_ver() -> None:
    user = _usuario(ver=3)
    token = auth.create_token(user)
    claims = auth.decode_token(token)
    assert claims["sub"] == str(user.id)
    assert claims["ver"] == 3
    assert "exp" not in claims  # la sesión no caduca por tiempo


# ── get_current_user ─────────────────────────────────────────────────────────

def test_get_current_user_ok() -> None:
    user = _usuario()
    db = FakeDB(user)
    token = auth.create_token(user)
    assert auth.get_current_user(db, f"Bearer {token}") is user


@pytest.mark.parametrize("header", [None, "", "Token abc", "Bearer ", "Bearer basura"])
def test_get_current_user_rechaza_headers_invalidos(header) -> None:  # noqa: ANN001
    user = _usuario()
    db = FakeDB(user)
    with pytest.raises(Exception):  # HTTPException 401
        auth.get_current_user(db, header)


def test_get_current_user_401_si_inactivo() -> None:
    user = _usuario(activo=False)
    token = auth.create_token(user)
    with pytest.raises(Exception):
        auth.get_current_user(FakeDB(user), f"Bearer {token}")


def test_get_current_user_401_si_token_version_no_coincide() -> None:
    user = _usuario(ver=1)
    token = auth.create_token(user)  # token con ver=1
    user.token_version = 2          # se reseteó la clave → sesión revocada
    with pytest.raises(Exception):
        auth.get_current_user(FakeDB(user), f"Bearer {token}")


# ── require_admin ────────────────────────────────────────────────────────────

def test_require_admin_pasa_admin_y_rechaza_comun() -> None:
    admin = _usuario(is_admin=True)
    comun = _usuario(is_admin=False)
    assert auth.require_admin(admin) is admin
    with pytest.raises(Exception):
        auth.require_admin(comun)


# ── Hash de secretos (OTP / invitación) ──────────────────────────────────────

def test_verify_secret_y_hash_token() -> None:
    code = auth.generar_codigo_otp()
    assert len(code) == 6 and code.isdigit()
    h = auth.hash_secret(code)
    assert auth.verify_secret(code, h)
    assert not auth.verify_secret("000000", h)
    assert not auth.verify_secret(code, None)

    token = auth.generar_token_invitacion()
    assert auth.hash_token(token) == auth.hash_token(token)  # determinístico
    assert auth.hash_token(token) != auth.hash_token(token + "x")
