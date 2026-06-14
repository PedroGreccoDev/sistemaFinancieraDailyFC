import { apiFetch, API_BASE } from './client'
import type { Cheque, Fiado } from '../types'

/** URL directa a la foto del cheque (misma-origen: sirve para <img>, descarga y compartir). */
export const chequeFotoUrl = (nro_cheque: string): string =>
  `${API_BASE}/cheques/${encodeURIComponent(nro_cheque)}/foto`

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

export const fiarCheque = (nro_cheque: string, payload: FiarChequePayload): Promise<FiarChequeResult> =>
  apiFetch<FiarChequeResult>(`/cheques/${encodeURIComponent(nro_cheque)}/fiar`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
