import { apiFetch } from './client'
import type { Fiado, FiadoEstado, CobrarConChequeResult } from '../types'

interface CobrarConChequePayload {
  nro_cheque_pago: string
  monto_cheque: number
  porcentaje_compra_cheque: number
  fecha_emision: string | null
  fecha_pago: string | null
  operador_id: string
}

export const getFiados = (estado?: FiadoEstado): Promise<Fiado[]> =>
  apiFetch<Fiado[]>(`/fiados${estado ? `?estado=${estado}` : ''}`)

export const cobrarEfectivo = (id: string, monto_cobrado: number, operador_id: string): Promise<Fiado> =>
  apiFetch<Fiado>(`/fiados/${id}/cobrar-efectivo`, {
    method: 'POST',
    body: JSON.stringify({ monto_cobrado, operador_id }),
  })

export const cobrarConCheque = (id: string, payload: CobrarConChequePayload): Promise<CobrarConChequeResult> =>
  apiFetch<CobrarConChequeResult>(`/fiados/${id}/cobrar-con-cheque`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
