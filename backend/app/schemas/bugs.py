from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BugRead(BaseModel):
    """Un bug en el listado. **Sin el traceback**, a propósito.

    El detalle de un bug ruidoso son miles de caracteres; devolverlo en la lista
    haría que abrir la pantalla se trajera megabytes para mostrar veinte
    renglones. Se pide por `GET /bugs/{id}` cuando se va a mirar uno.
    """

    id: int
    origen: str
    titulo: str
    tipo: str
    ubicacion: str
    ambito: str
    ocurrencias: int
    primera_vez: datetime
    ultima_vez: datetime
    estado: str
    notas: str | None
    sesion_test: str | None
    avisos_enviados: int
    ultimo_aviso_at: datetime | None

    model_config = {"from_attributes": True}


class BugDetalle(BugRead):
    """El bug completo: con el traceback y el contexto."""

    detalle: str
    contexto: dict[str, Any] | None


class BugEstadoUpdate(BaseModel):
    """Cambio de estado de un bug, con el diagnóstico escrito.

    Cerrar no borra nada: si el bug vuelve a ocurrir el registro lo reabre solo
    y lo avisa. Cerrar es decir "creemos que está arreglado".
    """

    estado: Literal["ABIERTO", "EN_CURSO", "CERRADO"]
    notas: str | None = Field(default=None, max_length=4000)


class BugFrontendCreate(BaseModel):
    """Un error que reventó en el navegador del operador.

    Los campos vienen del cliente, así que **son datos y no verdad**: se acotan
    por largo acá y el servidor arma el título y la huella por su cuenta. Lo que
    llega del navegador va al detalle, nunca al texto que viaja a Telegram.
    """

    mensaje: str = Field(min_length=1, max_length=500)
    # Dónde reventó: `archivo.js:línea` sacado del stack, o el componente de React.
    ubicacion: str = Field(default="", max_length=200)
    # En qué pantalla estaba el operador (`/deudores/otras`), no la URL completa.
    ruta: str = Field(default="", max_length=200)
    # El stack completo. Se guarda en la tabla y no sale de casa.
    stack: str = Field(default="", max_length=8000)
    # 'error' (window.onerror), 'promesa' (unhandledrejection), 'render'
    # (ErrorBoundary de React) o 'red' (una llamada a la API que no volvió).
    clase: str = Field(default="error", max_length=30)
    navegador: str = Field(default="", max_length=300)


class BugResumen(BaseModel):
    total: int
    abiertos: int
    en_curso: int
    cerrados: int
    # Suma de las ocurrencias de todos los bugs: cuántas veces falló algo, que
    # no es lo mismo que cuántas cosas distintas están rotas.
    ocurrencias: int
    por_origen: dict[str, int]
