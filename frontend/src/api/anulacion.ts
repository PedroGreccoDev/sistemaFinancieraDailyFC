import { apiFetch } from './client'

/** Tipos de entidad que acepta el motor de anulación (backend `_ENTIDADES`). */
export type EntidadAnulable =
  | 'cheque'
  | 'prestamo'
  | 'movimiento_efectivo'
  | 'fiado'
  | 'deuda_simple'
  | 'pasivo'
  | 'gasto'
  | 'ajuste_caja'

/** Una línea del libro de caja que la anulación va a revertir. */
export interface LineaImpacto {
  fecha: string
  moneda: string
  tipo: 'INGRESO' | 'EGRESO'
  categoria: string
  monto: string
  detalle: string | null
}

/**
 * Qué pasa (o pasaría) al anular. Se pide ANTES de mostrar la confirmación para
 * que el operador vea qué movimientos de caja se deshacen, en vez de apretar
 * "Eliminar" a ciegas.
 */
export interface Impacto {
  entidad: EntidadAnulable
  entidad_id: string
  descripcion: string
  puede_anular: boolean
  bloqueo: string | null
  lineas: LineaImpacto[]
  arrastra: string[]
}

export const previsualizarAnulacion = (
  entidad: EntidadAnulable,
  id: string,
): Promise<Impacto> =>
  apiFetch<Impacto>(`/anulaciones/${entidad}/${encodeURIComponent(id)}`)

export const anular = (
  entidad: EntidadAnulable,
  id: string,
  payload: { operador_id: string; motivo: string },
): Promise<Impacto> =>
  apiFetch<Impacto>(`/anulaciones/${entidad}/${encodeURIComponent(id)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

/**
 * Devuelve un cheque terminal a EN_CARTERA. No lo elimina: queda disponible para
 * volver a venderse o fiarse.
 */
export const revertirCheque = (
  id: string,
  payload: { operador_id: string; motivo: string },
): Promise<unknown> =>
  apiFetch(`/cheques/${encodeURIComponent(id)}/revertir`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
