import { apiFetch } from './client'
import type { DeudaSimple, DeudaSimpleEstado, Moneda } from '../types'

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
