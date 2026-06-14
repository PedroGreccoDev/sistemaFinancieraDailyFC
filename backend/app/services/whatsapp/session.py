from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# ── Configuración ────────────────────────────────────────────────────────────
_MAX_PAIRS = 10          # Máximo de pares usuario/asistente a conservar
_TTL_MINUTES = 30        # Tiempo de inactividad antes de expirar la sesión


class _SessionData:
    __slots__ = ("history", "last_active", "pending_intent", "pending_foto")

    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.last_active: datetime = datetime.now(UTC)
        self.pending_intent: Any = None  # IntentResult | None
        self.pending_foto: tuple[bytes, str] | None = None  # (bytes, mime) | None

    def touch(self) -> None:
        self.last_active = datetime.now(UTC)


_sessions: dict[str, _SessionData] = {}


# ── API pública ──────────────────────────────────────────────────────────────

def get_history(phone: str) -> list[dict[str, Any]]:
    """Devuelve el historial actual de la sesión (lista de mensajes Claude)."""
    _purge_expired()
    session = _sessions.get(phone)
    if session is None:
        return []
    session.touch()
    return list(session.history)


def add_user_message(phone: str, text: str) -> None:
    """Agrega un turno de usuario al historial."""
    session = _get_or_create(phone)
    session.history.append({"role": "user", "content": text})
    _trim(session)


def add_assistant_message(phone: str, text: str) -> None:
    """Agrega un turno de asistente al historial."""
    session = _get_or_create(phone)
    session.history.append({"role": "assistant", "content": text})
    _trim(session)


def set_pending_intent(phone: str, intent: Any) -> None:
    """Guarda el intent que espera confirmación del operador."""
    session = _get_or_create(phone)
    session.pending_intent = intent


def get_pending_intent(phone: str) -> Any:
    """Devuelve el intent pendiente de confirmación, o None si no hay."""
    session = _sessions.get(phone)
    return session.pending_intent if session is not None else None


def clear_pending_intent(phone: str) -> None:
    """Elimina el intent pendiente (tras ejecutarlo o cancelarlo)."""
    session = _sessions.get(phone)
    if session is not None:
        session.pending_intent = None
        session.pending_foto = None


def set_pending_foto(phone: str, foto: tuple[bytes, str] | None) -> None:
    """Guarda la foto asociada a un intent pendiente de confirmación."""
    if foto is None:
        return
    session = _get_or_create(phone)
    session.pending_foto = foto


def get_pending_foto(phone: str) -> tuple[bytes, str] | None:
    """Devuelve la foto del intent pendiente, o None si no hay."""
    session = _sessions.get(phone)
    return session.pending_foto if session is not None else None


def clear_session(phone: str) -> None:
    """Limpia la sesión después de una transacción exitosa.

    Esto es la 'Regla de Limpieza' de la arquitectura: evitar que Claude
    arrastre contexto entre operaciones consecutivas distintas.
    """
    _sessions.pop(phone, None)


# ── Helpers privados ─────────────────────────────────────────────────────────

def _get_or_create(phone: str) -> _SessionData:
    _purge_expired()
    if phone not in _sessions:
        _sessions[phone] = _SessionData()
    session = _sessions[phone]
    session.touch()
    return session


def _trim(session: _SessionData) -> None:
    """Mantiene sólo los últimos _MAX_PAIRS pares usuario/asistente."""
    max_len = _MAX_PAIRS * 2
    if len(session.history) > max_len:
        session.history = session.history[-max_len:]


def _purge_expired() -> None:
    """Elimina sesiones inactivas para no acumular memoria."""
    cutoff = datetime.now(UTC) - timedelta(minutes=_TTL_MINUTES)
    expired = [p for p, s in _sessions.items() if s.last_active < cutoff]
    for phone in expired:
        del _sessions[phone]
