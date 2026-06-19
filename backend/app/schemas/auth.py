from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Usuario (lectura, sin exponer hash) ──────────────────────────────────────

class UsuarioRead(BaseModel):
    id: UUID
    username: str
    phone: str | None
    is_admin: bool
    activo: bool
    # True → el usuario debe definir su propia clave antes de poder operar.
    must_change_password: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Login / sesión ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    token: str
    user: UsuarioRead


# ── Recuperación de contraseña por WhatsApp ──────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)


class ResetPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=4, max_length=10)
    new_password: str = Field(min_length=8, max_length=200)


class MensajeResponse(BaseModel):
    detail: str


# ── Cambio de contraseña (usuario autenticado) ───────────────────────────────

class CambiarPasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


# ── Invitación / registro ────────────────────────────────────────────────────

class InvitacionValidaResponse(BaseModel):
    """Respuesta de validación del enlace; `phone` sugerido para el alta."""
    phone: str | None


class RegistrarRequest(BaseModel):
    token: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)


class InvitacionCreate(BaseModel):
    phone: str | None = Field(default=None, max_length=40)
    is_admin: bool = False


class InvitacionRead(BaseModel):
    id: UUID
    phone: str | None
    is_admin: bool
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitacionCreatedResponse(BaseModel):
    """Devuelta al admin tras crear una invitación; incluye el enlace en claro."""
    invitacion: InvitacionRead
    link: str
    enviada_por_whatsapp: bool


# ── Gestión de usuarios (admin) ──────────────────────────────────────────────

class UsuarioCreate(BaseModel):
    """Alta directa de un usuario desde el panel (sin enlace de invitación)."""
    username: str = Field(min_length=1, max_length=80)
    # Si se omite, el backend genera una clave temporal y la devuelve al admin.
    password: str | None = Field(default=None, min_length=8, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    is_admin: bool = False


class UsuarioCreatedResponse(BaseModel):
    usuario: UsuarioRead
    # Solo presente cuando el admin no fijó una clave: la temporal a comunicar.
    temp_password: str | None = None


class UsuarioUpdate(BaseModel):
    activo: bool | None = None
    is_admin: bool | None = None
    phone: str | None = None
    # Si es True, genera una contraseña temporal nueva (e invalida sesiones).
    reset_password: bool = False


class UsuarioUpdatedResponse(BaseModel):
    usuario: UsuarioRead
    # Solo presente cuando se pidió reset_password: la clave temporal a comunicar.
    temp_password: str | None = None
