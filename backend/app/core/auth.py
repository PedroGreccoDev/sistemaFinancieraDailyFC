"""Núcleo de autenticación: hash de contraseñas, JWT de sesión y dependencias.

La sesión **no caduca por tiempo** (el JWT no lleva `exp`): la revocación real se
logra validando contra la BD en cada request (usuario activo + `token_version`).
Así, resetear/recuperar una clave (que incrementa `token_version`) invalida al
instante todas las sesiones viejas de ese usuario.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Usuario
from app.db.session import get_db

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_ALGORITHM = "HS256"


# ── Contraseñas ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    # bcrypt trunca a 72 bytes; passlib lo maneja, pero recortamos por las dudas.
    return _pwd_context.hash(password[:72])


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password[:72], password_hash)
    except ValueError:
        return False


# ── Códigos / tokens de un solo uso (recuperación e invitaciones) ────────────

def hash_secret(value: str) -> str:
    """Hash de un secreto corto (código OTP o token de invitación)."""
    return _pwd_context.hash(value)


def verify_secret(value: str, value_hash: str | None) -> bool:
    if not value_hash:
        return False
    try:
        return _pwd_context.verify(value, value_hash)
    except ValueError:
        return False


def generar_codigo_otp() -> str:
    """Código numérico de 6 dígitos para recuperación por WhatsApp."""
    return f"{secrets.randbelow(1_000_000):06d}"


def generar_token_invitacion() -> str:
    """Token urlsafe para el enlace de invitación (viaja en la URL)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash determinístico (SHA-256) para buscar invitaciones por su token.

    El token de invitación tiene alta entropía (32 bytes), así que un hash
    determinístico es seguro y permite el lookup directo en BD (a diferencia
    de los códigos OTP de 6 dígitos, que sí usan bcrypt + búsqueda por usuario).
    """
    return hashlib.sha256(token.encode()).hexdigest()


def generar_password_temporal() -> str:
    """Contraseña temporal legible para el reseteo manual por admin."""
    return secrets.token_urlsafe(9)


# ── JWT de sesión ────────────────────────────────────────────────────────────

def create_token(user: Usuario) -> str:
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "ver": user.token_version,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])


# ── Dependencias de FastAPI ──────────────────────────────────────────────────

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="No autenticado",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> Usuario:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED
    token = authorization.split(" ", 1)[1].strip()

    try:
        claims = decode_token(token)
        user_id = UUID(claims["sub"])
        ver = int(claims["ver"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _UNAUTHORIZED

    user = db.get(Usuario, user_id)
    if user is None or not user.activo or user.token_version != ver:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[Usuario, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> Usuario:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere permisos de administrador",
        )
    return user


AdminUser = Annotated[Usuario, Depends(require_admin)]


# ── Helpers de tiempo (vencimientos) ─────────────────────────────────────────

def en_minutos(minutos: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutos)


def vencido(dt: datetime | None) -> bool:
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= dt
