"""E-cheq: el cheque que no tiene lámina (§E-cheq, migraciones 0029 y 0030).

El cliente reenvía el comprobante del home banking y hay dos formatos: el de
**endoso** trae el número del e-cheq, el de **emisión** no. El operador no elige
cuál le mandan, así que "sin número" no es una excepción rara.

Estilo del proyecto: unitarios puros, sin BD.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.db.models import Cheque, ChequeEstado, ChequeTipo
from app.schemas.cheques import ChequeCreate
from app.services.cheques import describir
from app.services.ia.claude import _SYSTEM_PROMPT
from app.services.whatsapp.dispatcher import _tipo_cheque


def _cheque(
    nro: str | None = "13332",
    banco: str | None = "Galicia",
    tipo: ChequeTipo = ChequeTipo.PAPEL,
    monto: str = "5550280.00",
) -> Cheque:
    return Cheque(
        id=uuid.uuid4(),
        nro_cheque=nro,
        banco=banco,
        monto=Decimal(monto),
        porcentaje_compra=Decimal("10"),
        estado=ChequeEstado.EN_CARTERA,
        tipo=tipo,
        created_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )


# ── Cómo se nombra un cheque que puede no tener número ────────────────

def test_con_numero_se_nombra_por_el_numero() -> None:
    assert describir(_cheque()) == "cheque Nº 13332 — Galicia"


def test_un_echeq_se_nombra_como_echeq() -> None:
    """El operador tiene que reconocer en la línea de caja qué compró."""
    assert describir(_cheque(tipo=ChequeTipo.ELECTRONICO)) == "e-cheq Nº 13332 — Galicia"


def test_sin_numero_se_nombra_por_el_monto() -> None:
    """"cheque Nº None" no le sirve a nadie: sin número, lo que identifica el
    cheque en el panel es cuánto es."""
    texto = describir(_cheque(nro=None, banco=None, tipo=ChequeTipo.ELECTRONICO))
    assert texto == "e-cheq sin número ($5,550,280.00)"


def test_sin_numero_pero_con_banco_lo_menciona() -> None:
    assert describir(_cheque(nro=None)) == "cheque sin número ($5,550,280.00) — Galicia"


# ── El alta acepta que falte el número, no que falte la plata ─────────

def test_se_puede_crear_un_cheque_sin_numero() -> None:
    payload = ChequeCreate(monto=Decimal("3000000"), porcentaje_compra=Decimal("15"))
    assert payload.nro_cheque is None
    assert payload.tipo == ChequeTipo.PAPEL  # default: lo que era todo hasta acá


def test_el_numero_vacio_no_pasa_como_numero() -> None:
    """Un string vacío no es "sin número": es un dato mal armado, y dejarlo entrar
    haría que el cheque parezca tener número cuando no lo tiene."""
    with pytest.raises(PydanticValidationError):
        ChequeCreate(nro_cheque="", monto=Decimal("1000"), porcentaje_compra=Decimal("10"))


def test_el_monto_sigue_siendo_obligatorio() -> None:
    """Lo que se aflojó es la identificación, no la plata."""
    with pytest.raises(PydanticValidationError):
        ChequeCreate(nro_cheque="13332", porcentaje_compra=Decimal("10"))


# ── Cómo llega el tipo desde el modelo ────────────────────────────────

@pytest.mark.parametrize(
    "valor",
    ["ELECTRONICO", "electronico", "echeq", "e-cheq", "E-Cheque", "electrónico", "DIGITAL"],
)
def test_las_formas_de_decir_echeq_se_entienden_todas(valor: str) -> None:
    """El contrato pide "ELECTRONICO", pero mandarlo en castellano es el error
    probable —y equivocarse acá etiqueta mal sin que nadie lo note—."""
    assert _tipo_cheque({"tipo": valor}) == ChequeTipo.ELECTRONICO


@pytest.mark.parametrize("valor", [None, "", "PAPEL", "cualquier cosa"])
def test_lo_que_no_es_echeq_es_papel(valor: object) -> None:
    """Mismo criterio que `_medio`: el caso normal se asume en vez de frenar la
    operación entera por una palabra que no se reconoce."""
    assert _tipo_cheque({"tipo": valor}) == ChequeTipo.PAPEL


def test_sin_el_campo_es_papel() -> None:
    assert _tipo_cheque({}) == ChequeTipo.PAPEL


# ── Lo que el prompt tiene que decirle al modelo ──────────────────────

def test_el_prompt_prohibe_usar_la_palabra_echeq_como_numero() -> None:
    """El bug que originó todo esto: quedaron tres cheques cuyo número era la
    palabra "echeq", y el número real se perdió."""
    assert "NO ES UN NÚMERO DE CHEQUE" in _SYSTEM_PROMPT


def test_el_prompt_separa_las_dos_fechas_del_comprobante() -> None:
    """El error caro: confundir la fecha de la operación con la de pago carga un
    cheque a 15 días cuando vence a 60."""
    assert "Fecha de ejecución" in _SYSTEM_PROMPT
    assert "MÁS LEJANA en el futuro" in _SYSTEM_PROMPT


def test_el_prompt_manda_ignorar_al_beneficiario() -> None:
    """El beneficiario es el intermediario a cuyo nombre entra el cheque, no el
    cliente que se lo vendió al negocio: usarlo crearía un cliente fantasma."""
    assert "Persona beneficiaria" in _SYSTEM_PROMPT
    assert "NUNCA lo uses como cliente_nombre" in _SYSTEM_PROMPT


def test_el_prompt_contempla_los_dos_formatos_de_comprobante() -> None:
    assert "ENDOSO" in _SYSTEM_PROMPT
    assert "EMISIÓN" in _SYSTEM_PROMPT
    assert "Nro ECHEQ" in _SYSTEM_PROMPT
