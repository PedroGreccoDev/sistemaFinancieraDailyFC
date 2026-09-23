"""El día que elige el operador, llevado a un timestamp (`momento_en`).

Varias operaciones se registran en un timestamp UTC pero el operador elige a qué
día pertenecen ("esto lo pagué el jueves"). Traducir ese día a un momento no es
`datetime.combine` a secas: hay que pasar por la zona local, o la operación cae
en el día equivocado justo en las horas que más importan —las de la noche—.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.core.fechas import TZ_LOCAL, fecha_local, momento_en


def _ahora(dia: date, hora: int, minuto: int = 0) -> datetime:
    """Un instante en hora local de Argentina."""
    return datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=TZ_LOCAL)


def test_el_dia_de_hoy_devuelve_el_instante_exacto() -> None:
    """El caso normal —la operación es de hoy— no inventa una hora: es ahora."""
    ahora = _ahora(date(2026, 9, 22), 15, 30)
    assert momento_en(date(2026, 9, 22), ahora) == ahora.astimezone(UTC)


def test_un_dia_pasado_cae_en_ese_dia_local() -> None:
    ahora = _ahora(date(2026, 9, 22), 15, 30)
    assert fecha_local(momento_en(date(2026, 9, 19), ahora)) == date(2026, 9, 19)


def test_conserva_la_hora_de_carga() -> None:
    """Solo mueve el día: de la hora sale el orden de las operaciones dentro de
    la jornada, y mandarlas todas a medianoche las dejaría empatadas."""
    ahora = _ahora(date(2026, 9, 22), 15, 30)
    movido = momento_en(date(2026, 9, 19), ahora).astimezone(TZ_LOCAL)
    assert (movido.hour, movido.minute) == (15, 30)


def test_una_carga_nocturna_no_se_corre_al_dia_siguiente() -> None:
    """A las 21:17 ART ya es el día siguiente en UTC. Si el día elegido se
    combinara con la hora sin pasar por la zona local, la operación saltaría de
    día y quedaría fuera del cierre de caja — el mismo pozo del que cuida
    `hoy_local`."""
    ahora = _ahora(date(2026, 9, 22), 21, 17)
    momento = momento_en(date(2026, 9, 20), ahora)
    assert momento.astimezone(UTC).date() == date(2026, 9, 21)  # en UTC ya es otro día
    assert fecha_local(momento) == date(2026, 9, 20)  # pero el día local es el pedido


def test_sirve_para_cualquier_dia_del_mes_anterior() -> None:
    """Un pago viejo cargado ahora: el día tiene que ser el que dijo el operador,
    sin que el mes ni el año se muevan."""
    ahora = _ahora(date(2026, 9, 1), 9, 5)
    elegido = date(2026, 8, 31)
    assert fecha_local(momento_en(elegido, ahora)) == elegido


def test_la_ida_y_vuelta_cierra_para_todo_un_mes() -> None:
    """`fecha_local(momento_en(d)) == d` para cada día, a cualquier hora: es la
    propiedad que hace que la operación se impute al período correcto."""
    for hora in (0, 3, 12, 21, 23):
        ahora = _ahora(date(2026, 9, 22), hora)
        for delta in range(0, 31):
            dia = date(2026, 9, 22) - timedelta(days=delta)
            assert fecha_local(momento_en(dia, ahora)) == dia
