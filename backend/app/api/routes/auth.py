from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.auth import AdminUser, CurrentUser
from app.core.auth import create_token
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    InvitacionCreate,
    InvitacionCreatedResponse,
    InvitacionRead,
    InvitacionValidaResponse,
    LoginRequest,
    MensajeResponse,
    RegistrarRequest,
    ResetPasswordRequest,
    TokenResponse,
    UsuarioRead,
    UsuarioUpdate,
    UsuarioUpdatedResponse,
)
from app.services import usuarios as service
from app.services.whatsapp import client as wa_client

router = APIRouter(tags=["auth"])

DbSession = Annotated[Session, Depends(get_db)]

# Respuesta genérica de forgot-password: nunca revela si el usuario existe.
_MSG_RECUPERACION = (
    "Si el usuario existe y tiene un teléfono cargado, te enviamos un código por WhatsApp."
)


def _link_invitacion(token: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/registro?token={token}" if base else f"/registro?token={token}"


# ── Público ──────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = service.autenticar(db, payload.username, payload.password)
    return TokenResponse(token=create_token(user), user=UsuarioRead.model_validate(user))


@router.post("/auth/forgot-password", response_model=MensajeResponse)
async def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> MensajeResponse:
    datos = service.preparar_codigo_recuperacion(db, payload.username)
    if datos is not None:
        phone, code = datos
        await wa_client.send_text(
            phone,
            f"*Daily FC* — Recuperación de contraseña.\n\n"
            f"Tu código es: *{code}*\n\nVence en 10 minutos. Si no lo pediste, ignorá este mensaje.",
        )
    return MensajeResponse(detail=_MSG_RECUPERACION)


@router.post("/auth/reset-password", response_model=MensajeResponse)
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> MensajeResponse:
    service.resetear_con_codigo(db, payload.username, payload.code, payload.new_password)
    return MensajeResponse(detail="Contraseña actualizada. Ya podés ingresar.")


@router.get("/auth/invitacion/{token}", response_model=InvitacionValidaResponse)
def validar_invitacion(token: str, db: DbSession) -> InvitacionValidaResponse:
    inv = service.validar_invitacion(db, token)
    return InvitacionValidaResponse(phone=inv.phone)


@router.post("/auth/registrar", response_model=TokenResponse)
def registrar(payload: RegistrarRequest, db: DbSession) -> TokenResponse:
    user = service.registrar_desde_invitacion(db, payload.token, payload.username, payload.password)
    return TokenResponse(token=create_token(user), user=UsuarioRead.model_validate(user))


# ── Autenticado ──────────────────────────────────────────────────────────────

@router.get("/auth/me", response_model=UsuarioRead)
def me(user: CurrentUser) -> UsuarioRead:
    return UsuarioRead.model_validate(user)


# ── Solo admin ───────────────────────────────────────────────────────────────

@router.post("/invitaciones", response_model=InvitacionCreatedResponse, status_code=201)
async def crear_invitacion(
    payload: InvitacionCreate, db: DbSession, _admin: AdminUser
) -> InvitacionCreatedResponse:
    inv, token = service.crear_invitacion(db, payload)
    link = _link_invitacion(token)

    enviada = False
    if inv.phone:
        enviada = await wa_client.send_text(
            inv.phone,
            f"*Daily FC* — Te invitaron al sistema.\n\n"
            f"Creá tu cuenta acá (el enlace vence en 24 h):\n{link}",
            link_preview=True,
        )

    return InvitacionCreatedResponse(
        invitacion=InvitacionRead.model_validate(inv),
        link=link,
        enviada_por_whatsapp=enviada,
    )


@router.get("/invitaciones", response_model=list[InvitacionRead])
def listar_invitaciones(db: DbSession, _admin: AdminUser) -> list[InvitacionRead]:
    return [InvitacionRead.model_validate(i) for i in service.listar_invitaciones_pendientes(db)]


@router.delete("/invitaciones/{invitacion_id}", status_code=status.HTTP_204_NO_CONTENT)
def revocar_invitacion(invitacion_id: UUID, db: DbSession, _admin: AdminUser) -> Response:
    service.revocar_invitacion(db, invitacion_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/usuarios", response_model=list[UsuarioRead])
def listar_usuarios(db: DbSession, _admin: AdminUser) -> list[UsuarioRead]:
    return [UsuarioRead.model_validate(u) for u in service.listar_usuarios(db)]


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioUpdatedResponse)
def actualizar_usuario(
    usuario_id: UUID, payload: UsuarioUpdate, db: DbSession, admin: AdminUser
) -> UsuarioUpdatedResponse:
    user, temp_password = service.actualizar_usuario(db, usuario_id, payload, admin)
    return UsuarioUpdatedResponse(
        usuario=UsuarioRead.model_validate(user),
        temp_password=temp_password,
    )
