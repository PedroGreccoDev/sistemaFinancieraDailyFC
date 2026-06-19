"""Lógica de negocio de autenticación: usuarios, invitaciones y recuperación.

Las funciones son **síncronas** (operan sobre la sesión SQLAlchemy). El envío
por WhatsApp (async) lo hace el router: estas funciones generan/devuelven el
código o el token en claro y el router se encarga de mandarlo con `send_text`.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth
from app.core.config import get_settings
from app.db.models import Invitacion, Usuario
from app.schemas.auth import InvitacionCreate, UsuarioCreate, UsuarioUpdate
from app.services.exceptions import (
    ConflictError,
    GoneError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Minutos de validez del código de recuperación por WhatsApp.
_RESET_CODE_TTL_MIN = 10
# Horas de validez del enlace de invitación.
_INVITACION_TTL_HORAS = 24


def _norm_username(username: str) -> str:
    return username.strip().lower()


def _norm_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    return digits or None


# ── Bootstrap del admin raíz ─────────────────────────────────────────────────

def bootstrap_admin(db: Session) -> None:
    """Crea el admin raíz desde las env vars si no existe ningún admin.

    Idempotente: no recrea nada si ya hay un admin. Recuperable: cambiando
    `ADMIN_PASSWORD` y reiniciando se resetea la clave del admin existente.
    """
    settings = get_settings()
    if not settings.admin_password:
        return

    username = _norm_username(settings.admin_username)
    existente = db.scalar(select(Usuario).where(Usuario.username == username))

    if existente is not None:
        # Re-sincroniza el admin raíz con las env vars, pero SOLO tocando lo que
        # cambió. Antes incrementábamos token_version en cada arranque, lo que
        # invalidaba la sesión del admin en cada reinicio/cold-start (Railway) y
        # obligaba a re-loguear todo el tiempo. Ahora solo cortamos sesiones (y
        # re-hasheamos) cuando ADMIN_PASSWORD realmente cambió.
        cambios = False
        if not auth.verify_password(settings.admin_password, existente.password_hash):
            existente.password_hash = auth.hash_password(settings.admin_password)
            existente.token_version += 1  # recuperación: corta sesiones viejas
            cambios = True
        if not existente.is_admin:
            existente.is_admin = True
            cambios = True
        if not existente.activo:
            existente.activo = True
            cambios = True
        if cambios:
            db.commit()
            logger.info("Admin raíz '%s' actualizado desde env vars.", username)
        return

    hay_admin = db.scalar(select(Usuario.id).where(Usuario.is_admin.is_(True)).limit(1))
    if hay_admin is not None:
        return

    admin = Usuario(
        username=username,
        password_hash=auth.hash_password(settings.admin_password),
        is_admin=True,
        activo=True,
    )
    db.add(admin)
    db.commit()
    logger.info("Admin raíz '%s' creado desde env vars.", username)


# ── Login ────────────────────────────────────────────────────────────────────

def autenticar(db: Session, username: str, password: str) -> Usuario:
    user = db.scalar(select(Usuario).where(Usuario.username == _norm_username(username)))
    if user is None or not user.activo or not auth.verify_password(password, user.password_hash):
        raise UnauthorizedError("Usuario o contraseña incorrectos.")
    return user


# ── Recuperación de contraseña por WhatsApp ──────────────────────────────────

def preparar_codigo_recuperacion(db: Session, username: str) -> tuple[str, str] | None:
    """Genera y persiste un código OTP si el usuario es elegible.

    Devuelve `(phone, code)` para que el router lo envíe, o `None` si el usuario
    no existe / está inactivo / no tiene teléfono (el router responde genérico).
    """
    user = db.scalar(select(Usuario).where(Usuario.username == _norm_username(username)))
    if user is None or not user.activo or not user.phone:
        return None

    code = auth.generar_codigo_otp()
    user.reset_code_hash = auth.hash_secret(code)
    user.reset_code_expires_at = auth.en_minutos(_RESET_CODE_TTL_MIN)
    db.commit()
    return user.phone, code


def resetear_con_codigo(db: Session, username: str, code: str, new_password: str) -> Usuario:
    user = db.scalar(select(Usuario).where(Usuario.username == _norm_username(username)))
    if (
        user is None
        or not user.activo
        or auth.vencido(user.reset_code_expires_at)
        or not auth.verify_secret(code, user.reset_code_hash)
    ):
        raise UnauthorizedError("El código es inválido o ya venció.")

    user.password_hash = auth.hash_password(new_password)
    user.reset_code_hash = None
    user.reset_code_expires_at = None
    user.must_change_password = False  # la fijó el propio usuario
    user.token_version += 1  # invalida sesiones viejas
    db.commit()
    db.refresh(user)
    return user


def cambiar_password(
    db: Session, user: Usuario, current_password: str, new_password: str
) -> Usuario:
    """Cambio de clave del propio usuario autenticado.

    Verifica la clave actual, fija la nueva y limpia `must_change_password`.
    Incrementa `token_version` (corta otras sesiones); el router debe emitir un
    token nuevo para no dejar sin sesión a quien acaba de cambiarla.
    """
    if not auth.verify_password(current_password, user.password_hash):
        raise UnauthorizedError("La contraseña actual es incorrecta.")
    if auth.verify_password(new_password, user.password_hash):
        raise ValidationError("La nueva contraseña debe ser distinta de la actual.")

    user.password_hash = auth.hash_password(new_password)
    user.must_change_password = False
    user.reset_code_hash = None
    user.reset_code_expires_at = None
    user.token_version += 1
    db.commit()
    db.refresh(user)
    return user


# ── Invitaciones ─────────────────────────────────────────────────────────────

def crear_invitacion(db: Session, payload: InvitacionCreate) -> tuple[Invitacion, str]:
    """Crea una invitación y devuelve `(invitacion, token_en_claro)`."""
    token = auth.generar_token_invitacion()
    inv = Invitacion(
        phone=_norm_phone(payload.phone),
        is_admin=payload.is_admin,
        token_hash=auth.hash_token(token),
        expires_at=auth.en_minutos(_INVITACION_TTL_HORAS * 60),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv, token


def listar_invitaciones_pendientes(db: Session) -> list[Invitacion]:
    stmt = (
        select(Invitacion)
        .where(Invitacion.used_at.is_(None))
        .order_by(Invitacion.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def revocar_invitacion(db: Session, invitacion_id: uuid.UUID) -> None:
    inv = db.get(Invitacion, invitacion_id)
    if inv is None:
        raise NotFoundError("Invitación no encontrada.")
    if inv.used_at is not None:
        raise ConflictError("La invitación ya fue usada.")
    db.delete(inv)
    db.commit()


def validar_invitacion(db: Session, token: str) -> Invitacion:
    """Valida el token del enlace. Lanza 404 si no existe, 410 si usada/vencida."""
    inv = db.scalar(select(Invitacion).where(Invitacion.token_hash == auth.hash_token(token)))
    if inv is None:
        raise NotFoundError("La invitación no existe.")
    if inv.used_at is not None or auth.vencido(inv.expires_at):
        raise GoneError("Este enlace ya no es válido. Pedí una nueva invitación.")
    return inv


def registrar_desde_invitacion(
    db: Session, token: str, username: str, password: str
) -> Usuario:
    inv = validar_invitacion(db, token)

    uname = _norm_username(username)
    if db.scalar(select(Usuario.id).where(Usuario.username == uname)) is not None:
        raise ConflictError("Ese usuario ya existe. Probá con otro.")

    user = Usuario(
        username=uname,
        password_hash=auth.hash_password(password),
        phone=inv.phone,
        is_admin=inv.is_admin,
        activo=True,
    )
    db.add(user)
    inv.used_at = auth.en_minutos(0)  # ahora (un solo uso)
    db.commit()
    db.refresh(user)
    return user


# ── Gestión de usuarios (admin) ──────────────────────────────────────────────

def listar_usuarios(db: Session) -> list[Usuario]:
    return list(db.scalars(select(Usuario).order_by(Usuario.created_at.asc())).all())


def crear_usuario(db: Session, payload: UsuarioCreate) -> tuple[Usuario, str | None]:
    """Alta directa de un usuario (sin invitación). Devuelve `(usuario, temp_password?)`.

    Si el admin no fijó una clave, se genera una temporal y se devuelve en claro
    para que la comunique (misma lógica que el reset de clave).
    """
    uname = _norm_username(payload.username)
    if db.scalar(select(Usuario.id).where(Usuario.username == uname)) is not None:
        raise ConflictError("Ese usuario ya existe. Probá con otro.")

    temp_password: str | None = None
    if payload.password:
        password = payload.password
    else:
        password = auth.generar_password_temporal()
        temp_password = password

    user = Usuario(
        username=uname,
        password_hash=auth.hash_password(password),
        phone=_norm_phone(payload.phone),
        is_admin=payload.is_admin,
        activo=True,
        # Clave temporal generada por el sistema → forzamos el cambio al ingresar.
        must_change_password=temp_password is not None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, temp_password


def actualizar_usuario(
    db: Session, usuario_id: uuid.UUID, payload: UsuarioUpdate, actor: Usuario
) -> tuple[Usuario, str | None]:
    """Aplica cambios admin sobre un usuario. Devuelve `(usuario, temp_password?)`."""
    user = db.get(Usuario, usuario_id)
    if user is None:
        raise NotFoundError("Usuario no encontrado.")

    # Salvaguarda: no permitir quedarse sin ningún admin activo.
    desactiva = payload.activo is False and user.activo
    quita_admin = payload.is_admin is False and user.is_admin
    if user.is_admin and (desactiva or quita_admin):
        otros_admins = db.scalar(
            select(Usuario.id)
            .where(Usuario.is_admin.is_(True), Usuario.activo.is_(True), Usuario.id != user.id)
            .limit(1)
        )
        if otros_admins is None:
            raise ValidationError("No podés dejar el sistema sin ningún administrador activo.")

    if payload.phone is not None:
        user.phone = _norm_phone(payload.phone)
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.activo is not None:
        user.activo = payload.activo

    temp_password: str | None = None
    if payload.reset_password:
        temp_password = auth.generar_password_temporal()
        user.password_hash = auth.hash_password(temp_password)
        user.reset_code_hash = None
        user.reset_code_expires_at = None
        user.must_change_password = True  # al ingresar deberá fijar su propia clave
        user.token_version += 1  # corta sesiones activas

    db.commit()
    db.refresh(user)
    return user, temp_password
