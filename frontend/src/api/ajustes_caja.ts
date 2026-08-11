import { apiFetch } from './client'
import type { AjusteCaja, AjusteCajaMotivo, Moneda } from '../types'

export interface AjusteCajaCreate {
  fecha: string
  moneda: Moneda
  /** INGRESO suma efectivo a la caja, EGRESO lo resta. */
  tipo: 'INGRESO' | 'EGRESO'
  motivo: AjusteCajaMotivo
  monto: number
  /** Obligatoria cuando el ajuste SUMA dólares: costo ($/USD) del lote FIFO. */
  cotizacion_usd?: number | null
  descripcion?: string | null
  operador_id: string
}

export const getAjustesCaja = (desde?: string, hasta?: string): Promise<AjusteCaja[]> => {
  const qs = new URLSearchParams()
  if (desde) qs.set('desde', desde)
  if (hasta) qs.set('hasta', hasta)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return apiFetch<AjusteCaja[]>(`/ajustes-caja${suffix}`)
}

export const crearAjusteCaja = (payload: AjusteCajaCreate): Promise<AjusteCaja> =>
  apiFetch<AjusteCaja>('/ajustes-caja', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
