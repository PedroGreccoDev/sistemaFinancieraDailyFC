> **Note (EN):** This is the backend + frontend for an internal financial management
> system I built end-to-end for a real client — loan and check-portfolio management,
> with a WhatsApp bot as the primary operator interface and a cascading multi-model
> OCR pipeline for check processing that cut image-processing costs by ~8x. Backed by
> 630+ automated tests and in active production use. Full docs below are in Spanish
> (the client's working language).

---

# Sistema Financiera Daily FC

Monorepo para un sistema interno de gestion financiera y cartera privada.

El backend actua como ERP interno de inventario fisico y control de caja. No incluye
modulos de facturacion fiscal, impuestos ni automatizacion de cotizaciones.

## Backend

Stack:

- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Pydantic

### Instalacion local

Desde la raiz del repo:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Crear un `.env` en `backend/`:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/financiera
CORS_ORIGINS=["http://localhost:5173"]
```

### Migraciones

```powershell
cd backend
alembic upgrade head
```

### Ejecutar API

```powershell
cd backend
uvicorn app.main:app --reload
```

La documentacion interactiva queda disponible en:

```text
http://127.0.0.1:8000/docs
```

### Tests

```powershell
cd backend
pytest
```

## Reglas criticas

- Los cheques se tratan como inventario fisico interno.
- Un cheque nuevo entra siempre en estado `EN_CARTERA`.
- `COBRADO` y `RECHAZADO` son eventos manuales del operador.
- `FIADO` solo se procesa con una transaccion atomica que tambien crea el prestamo y sus cuotas.
- Las operaciones de efectivo usan la cotizacion dictada por el operador.
- No se modelan facturas, impuestos ni campos fiscales.

