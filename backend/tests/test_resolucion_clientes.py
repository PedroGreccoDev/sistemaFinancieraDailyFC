from __future__ import annotations

import pytest

from app.db.models import Cliente
from app.services.whatsapp.dispatcher import _elegir_cliente_match


def _cli(nombre: str) -> Cliente:
    """Instancia un Cliente en memoria (sin BD); solo nos interesa `.nombre`."""
    return Cliente(nombre=nombre)


# ── Caso reportado: "Rami" vs "Ramiro Velez" ─────────────────────────────────

def test_match_exacto_unico_gana_sobre_substring_mas_largo() -> None:
    # ILIKE '%Rami%' devuelve ambos; el operador tecleó exactamente "Rami".
    rami = _cli("Rami")
    candidatos = [_cli("Ramiro Velez"), rami]
    assert _elegir_cliente_match(candidatos, "Rami") is rami


def test_match_exacto_es_case_insensitive() -> None:
    rami = _cli("Rami")
    candidatos = [_cli("Ramiro Velez"), rami]
    assert _elegir_cliente_match(candidatos, "rami") is rami
    assert _elegir_cliente_match(candidatos, "  RAMI ") is rami


def test_nombre_completo_resuelve_al_cliente_largo() -> None:
    ramiro = _cli("Ramiro Velez")
    candidatos = [ramiro]  # ILIKE '%Ramiro Velez%' solo trae uno
    assert _elegir_cliente_match(candidatos, "Ramiro velez") is ramiro


# ── Se preserva la desambiguación genuina (caso "Bono") ──────────────────────

def test_substring_parcial_sin_match_exacto_sigue_pidiendo_desambiguar() -> None:
    candidatos = [_cli("Ramiro Velez"), _cli("Rami")]
    with pytest.raises(ValueError, match="coinciden con 'Ram'"):
        _elegir_cliente_match(candidatos, "Ram")


def test_dos_matches_exactos_no_ganan_en_silencio() -> None:
    # Caso patológico: dos clientes homónimos exactos → desambiguar igual.
    candidatos = [_cli("Bono"), _cli("Bono")]
    with pytest.raises(ValueError, match="2 clientes que coinciden"):
        _elegir_cliente_match(candidatos, "Bono")


# ── Bordes ───────────────────────────────────────────────────────────────────

def test_sin_resultados_lanza_no_existe() -> None:
    with pytest.raises(ValueError, match="No encontré ningún cliente"):
        _elegir_cliente_match([], "Fulano")


def test_unico_candidato_se_devuelve_sin_chequear_exactitud() -> None:
    juan = _cli("Juan Bono")
    assert _elegir_cliente_match([juan], "Juan") is juan
