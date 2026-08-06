import { apiFetch } from './client'
import type { Cheque, DeudaSimple, DeudaSimpleEstado, Moneda } from '../types'

export interface DeudaSimpleCreatePayload {
  cliente_id: string
  concepto: string
  monto: number
  moneda: Moneda
  fecha: string | null
  observaciones: string | null
}

export const getDeudasSimples = (estado?: DeudaSimpleEstado): Promise<DeudaSimple[]> =>
  apiFetch<DeudaSimple[]>(`/deudas-simples${estado ? `?estado=${estado}` : ''}`)

export const createDeudaSimple = (payload: DeudaSimpleCreatePayload): Promise<DeudaSimple> =>
  apiFetch<DeudaSimple>('/deudas-simples', { method: 'POST', body: JSON.stringify(payload) })

// Corrección de la carga. `monto`/`moneda` solo si está ABIERTA y sin cobros
// parciales (lo valida el backend).
export interface DeudaSimpleUpdatePayload {
  concepto?: string
  monto?: number
  moneda?: Moneda
  fecha?: string | null
  observaciones?: string | null
}

export const editarDeudaSimple = (id: string, payload: DeudaSimpleUpdatePayload): Promise<DeudaSimple> =>
  apiFetch<DeudaSimple>(`/deudas-simples/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })

export interface CobrarDeudaSimplePayload {
  monto_cobrado: number
  moneda_pago: Moneda
  // Requerida solo si moneda_pago difiere de la moneda de la deuda ($/USD).
  cotizacion?: number | null
  fecha_cobro?: string | null
}

export const cobrarDeudaSimple = (id: string, payload: CobrarDeudaSimplePayload): Promise<DeudaSimple> =>
  apiFetch<DeudaSimple>(`/deudas-simples/${id}/cobrar`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

/**
 * Cobro de una deuda libre entregando un cheque en vez de efectivo.
 *
 * El cheque entra a cartera a nombre del cliente y salda por su valor neto
 * (`monto × (1 − %compra)`), no por su nominal. No mueve la caja: la plata se
 * reconoce recién cuando ese cheque se venda o se cobre.
 */
export interface CobrarDeudaSimpleConChequePayload {
  nro_cheque_pago: string
  banco_pago?: string | null
  monto_cheque: number
  porcentaje_compra_cheque: number
  fecha_emision?: string | null
  fecha_pago?: string | null
  // Requerida solo si la deuda es en USD (el cheque siempre entra en pesos).
  cotizacion?: number | null
  fecha_cobro?: string | null
}

export interface CobrarConChequeResult {
  deuda: DeudaSimple
  cheque_ingresado: Cheque
  /** En la moneda de la deuda: > 0 el negocio le queda debiendo al cliente. */
  diferencia: string
}

export const cobrarDeudaSimpleConCheque = (
  id: string,
  payload: CobrarDeudaSimpleConChequePayload,
): Promise<CobrarConChequeResult> =>
  apiFetch<CobrarConChequeResult>(`/deudas-simples/${id}/cobrar-con-cheque`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
