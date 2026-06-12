import { apiFetch } from './client'
import type { Moneda, Pasivo, PasivoEstado } from '../types'

export interface PasivoCreatePayload {
  acreedor: string
  concepto: string
  monto: number
  moneda: Moneda
  fecha_vencimiento: string | null
  observaciones: string | null
}

export const getPasivos = (estado?: PasivoEstado): Promise<Pasivo[]> => {
  const qs = estado ? `?estado=${estado}` : ''
  return apiFetch<Pasivo[]>(`/pasivos${qs}`)
}

export const createPasivo = (payload: PasivoCreatePayload): Promise<Pasivo> =>
  apiFetch<Pasivo>('/pasivos', { method: 'POST', body: JSON.stringify(payload) })

export const cancelarPasivo = (id: string): Promise<Pasivo> =>
  apiFetch<Pasivo>(`/pasivos/${id}/cancelar`, { method: 'POST', body: JSON.stringify({}) })

export const cancelarPasivoEfectivo = (
  id: string,
  payload: { monto_cobrado: number; fecha_cancelacion?: string | null },
): Promise<Pasivo> =>
  apiFetch<Pasivo>(`/pasivos/${id}/cancelar-efectivo`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface CancelarConChequePayload {
  nro_cheque: string
  porcentaje_venta: number
  operador_id: string
  motivo: string
  fecha_cancelacion?: string | null
}

export const cancelarPasivoConCheque = (
  id: string,
  payload: CancelarConChequePayload,
): Promise<Pasivo> =>
  apiFetch<Pasivo>(`/pasivos/${id}/cancelar-con-cheque`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
