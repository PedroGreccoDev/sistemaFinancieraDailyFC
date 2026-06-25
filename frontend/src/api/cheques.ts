import { apiFetch, API_BASE } from './client'
import type { Cheque, Fiado } from '../types'

/** URL directa a la foto del cheque (misma-origen: sirve para <img>, descarga y compartir). */
export const chequeFotoUrl = (cheque_id: string): string =>
  `${API_BASE}/cheques/${encodeURIComponent(cheque_id)}/foto`

export const getChequeCartera = (): Promise<Cheque[]> =>
  apiFetch<Cheque[]>('/cheques/cartera')

export const getCheques = (estado?: string): Promise<Cheque[]> =>
  apiFetch<Cheque[]>(`/cheques${estado ? `?estado=${estado}` : ''}`)

interface FiarChequePayload {
  cliente_destino_id: string
  porcentaje_venta: number
  motivo: string
  operador_id: string
}

export interface FiarChequeResult {
  cheque: Cheque
  fiado: Fiado
}

export const fiarCheque = (cheque_id: string, payload: FiarChequePayload): Promise<FiarChequeResult> =>
  apiFetch<FiarChequeResult>(`/cheques/${encodeURIComponent(cheque_id)}/fiar`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// Corrección de la carga de un cheque. Solo se mandan los campos a cambiar.
export interface ChequeUpdatePayload {
  nro_cheque?: string
  banco?: string | null
  monto?: number
  fecha_emision?: string | null
  fecha_pago?: string | null
  porcentaje_compra?: number
  porcentaje_venta?: number
  cliente_origen_id?: string | null
  cliente_destino_id?: string | null
}

export const editarCheque = (cheque_id: string, payload: ChequeUpdatePayload): Promise<Cheque> =>
  apiFetch<Cheque>(`/cheques/${encodeURIComponent(cheque_id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
