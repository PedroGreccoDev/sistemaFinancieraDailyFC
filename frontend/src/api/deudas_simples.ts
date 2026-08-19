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
 * Cobro de un importe libre contra TODAS las deudas abiertas de un cliente.
 *
 * Es el cobro de la fila del cliente: el importe se imputa de la deuda más
 * vieja a la más nueva, sin que el operador elija a cuál va. `moneda_deuda`
 * dice contra qué deudas se cobra (ARS y USD no se suman entre sí); el pago
 * puede venir en la otra moneda con su cotización, como en el cobro suelto.
 */
export interface CobrarDeudasClientePayload {
  cliente_id: string
  moneda_deuda: Moneda
  monto_cobrado: number
  moneda_pago: Moneda
  // Requerida solo si moneda_pago difiere de moneda_deuda ($/USD).
  cotizacion?: number | null
  fecha_cobro?: string | null
}

export interface CobroClienteResult {
  /** Las deudas que recibieron parte del importe, la más vieja primero. */
  deudas_afectadas: DeudaSimple[]
  /** Cuánto bajó la deuda en total, en la moneda de las deudas. */
  imputado: string
  canceladas: number
  saldo_restante: string
}

export const cobrarDeudasCliente = (payload: CobrarDeudasClientePayload): Promise<CobroClienteResult> =>
  apiFetch<CobroClienteResult>('/deudas-simples/cobrar-cliente', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

/**
 * Cobro de TODAS las deudas abiertas de un cliente con un solo cheque.
 *
 * Salda por el valor neto del cheque, de la deuda más vieja a la más nueva. Si
 * cubre todo y sobra, `vuelto_modo` decide qué se hace con la diferencia (que
 * va en pesos, porque el cheque es un instrumento en pesos): pagarla en
 * efectivo —lo único que mueve la caja acá— o quedar debiéndola, que crea un
 * pasivo a favor del cliente. Mismo mecanismo que el vuelto de un pasivo.
 */
export type VueltoModo = 'SALDAR_EFECTIVO' | 'QUEDA_DEBIENDO'

export interface CobrarDeudasClienteConChequePayload {
  cliente_id: string
  moneda_deuda: Moneda
  nro_cheque_pago: string
  banco_pago?: string | null
  monto_cheque: number
  porcentaje_compra_cheque: number
  fecha_emision?: string | null
  fecha_pago?: string | null
  // Requerida solo si las deudas son en USD (el cheque siempre entra en pesos).
  cotizacion?: number | null
  // Obligatorio solo si el cheque cubre todo y sobra.
  vuelto_modo?: VueltoModo | null
  fecha_cobro?: string | null
}

export interface CobroClienteChequeResult {
  deudas_afectadas: DeudaSimple[]
  cheque_ingresado: Cheque
  imputado: string
  canceladas: number
  saldo_restante: string
  /** En ARS: > 0 el cheque cubrió todo y el negocio le queda debiendo esto. */
  diferencia: string
  vuelto_modo: VueltoModo | null
}

export const cobrarDeudasClienteConCheque = (
  payload: CobrarDeudasClienteConChequePayload,
): Promise<CobroClienteChequeResult> =>
  apiFetch<CobroClienteChequeResult>('/deudas-simples/cobrar-cliente-con-cheque', {
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
