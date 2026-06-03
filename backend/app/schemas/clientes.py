from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClienteBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=160)
    cuit: str | None = Field(default=None, max_length=20)
    telefono: str | None = Field(default=None, max_length=40)


class ClienteCreate(ClienteBase):
    pass


class ClienteRead(ClienteBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime

