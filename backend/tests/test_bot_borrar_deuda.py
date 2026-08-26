"""Borrar una deuda por chat cuando el nombre trae más de una.

Hay dos situaciones que se ven parecidas y solo una tiene salida por chat:

- **Acreedores distintos** que coinciden con lo que dijo el operador ("Cuello" y
  "Cuello Hermanos"): precisar el nombre alcanza, así que se pregunta.
- **El mismo acreedor con varias deudas**: todas se llaman igual. Pedir "más
  precisión" ahí es un loop —el operador no tiene nada más preciso que decir— y
  por eso se manda al panel (decisión del dueño, 2026-08-26).
"""

from __future__ import annotations

import pytest

from app.services.whatsapp import dispatcher


class _PasivoFalso:
    def __init__(self, acreedor: str) -> None:
        self.acreedor = acreedor
        self.id = acreedor


class _DbFalsa:
    """Lo único que `_resolver_para_anular` le pide a la sesión es `scalars(...).all()`."""

    def __init__(self, filas: list[_PasivoFalso]) -> None:
        self._filas = filas

    def scalars(self, _stmt):  # noqa: ANN001 - stub de sesión
        return self

    def all(self) -> list[_PasivoFalso]:
        return self._filas

    def first(self) -> _PasivoFalso | None:
        return self._filas[0] if self._filas else None


def _resolver(filas: list[str]):
    return dispatcher._resolver_para_anular(
        _DbFalsa([_PasivoFalso(n) for n in filas]), "PASIVO", "Cuello"
    )


def test_varias_deudas_del_mismo_acreedor_mandan_al_panel() -> None:
    """El caso del loop: "decime cuál con más precisión" cuando las tres se llaman
    Cuello no se puede contestar. Ahora dice que se resuelve en el panel."""
    with pytest.raises(ValueError) as exc:
        _resolver(["Cuello", "Cuello", "Cuello"])
    msg = str(exc.value)
    assert "3 deudas" in msg
    assert "todas se llaman igual" in msg
    assert "desde el panel" in msg
    assert "más precisión" not in msg


def test_acreedores_distintos_si_se_preguntan() -> None:
    """Acá precisar el nombre SÍ resuelve, así que preguntar tiene sentido."""
    with pytest.raises(ValueError) as exc:
        _resolver(["Cuello", "Cuello Hermanos"])
    msg = str(exc.value)
    assert "Cuello Hermanos" in msg
    assert "¿A cuál de todos?" in msg
    assert "panel" not in msg


def test_una_sola_deuda_se_resuelve_sin_preguntar() -> None:
    entidad, pasivo = _resolver(["Cuello"])
    assert entidad == "pasivo"
    assert pasivo.acreedor == "Cuello"


def test_sin_deudas_lo_dice() -> None:
    with pytest.raises(ValueError, match="No encontré esa deuda"):
        _resolver([])
