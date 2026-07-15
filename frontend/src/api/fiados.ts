import { apiFetch } from './client'
import type { Fiado, FiadoEstado, CobrarConChequeResult, Moneda } from '../types'

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

// La deuda del fiado es siempre en ARS; el cobro puede hacerse en otra moneda
// (`extra.moneda_pago`), en cuyo caso `extra.cotizacion` (pesos por 1 USD) es
// obligatoria e imputa cuánto del saldo ARS queda saldado.
export const cobrarEfectivo = (
  id: string,
  monto_cobrado: number,
  operador_id: string,
  extra?: { moneda_pago?: Moneda; cotizacion?: number | null },
): Promise<Fiado> =>
  apiFetch<Fiado>(`/fiados/${id}/cobrar-efectivo`, {
    method: 'POST',
    body: JSON.stringify({
      monto_cobrado,
      operador_id,
      moneda_pago: extra?.moneda_pago ?? 'ARS',
      cotizacion: extra?.cotizacion ?? null,
    }),
  })

export const cobrarConCheque = (id: string, payload: CobrarConChequePayload): Promise<CobrarConChequeResult> =>
  apiFetch<CobrarConChequeResult>(`/fiados/${id}/cobrar-con-cheque`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
