from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import backup as svc

router = APIRouter(prefix="/backup", tags=["backup"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/exportar")
def exportar(db: DbSession) -> StreamingResponse:
    data = svc.exportar_json(db)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    fecha = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="backup_{fecha}.json"'},
    )


@router.post("/importar")
async def importar(file: UploadFile, db: DbSession) -> dict:
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Archivo JSON inválido: {exc}") from exc
    try:
        conteos = svc.importar_json(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "tablas": conteos}


@router.get("/exportar-excel")
def exportar_excel(db: DbSession) -> StreamingResponse:
    content = svc.exportar_excel(db)
    fecha = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="datos_{fecha}.xlsx"'},
    )
