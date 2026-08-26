import { apiFetch } from './client'
import type { MedioPago, Moneda, Pasivo, PasivoEstado } from '../types'

export interface PasivoCreatePayload {
  acreedor: string
  concepto: string
  monto: number
  moneda: Moneda
  fecha_vencimiento: string | null
  observaciones: string | null
  // Solo cuando le prestaron plata al negocio: además de anotar la deuda, asienta
  // el ingreso del efectivo que entró al cajón.
  ingreso_caja?: boolean
  fecha_ingreso?: string | null
  // Obligatoria si le prestaron DÓLARES: costo ($/USD) del lote de stock que se
  // crea, sin el cual esos dólares no se pueden vender.
  cotizacion_ingreso_usd?: number | null
}

export const getPasivos = (estado?: PasivoEstado): Promise<Pasivo[]> => {
  const qs = estado ? `?estado=${estado}` : ''
  return apiFetch<Pasivo[]>(`/pasivos${qs}`)
}

export const createPasivo = (payload: PasivoCreatePayload): Promise<Pasivo> =>
  apiFetch<Pasivo>('/pasivos', { method: 'POST', body: JSON.stringify(payload) })

// Corrección de la carga de una deuda. `monto`/`moneda` solo si está PENDIENTE y
// sin pagos parciales (lo valida el backend).
export interface PasivoUpdatePayload {
  acreedor?: string
  concepto?: string
  monto?: number
  moneda?: Moneda
  fecha_vencimiento?: string | null
  observaciones?: string | null
  ingreso_caja?: boolean
  fecha_ingreso?: string | null
  cotizacion_ingreso_usd?: number | null
}

export const editarPasivo = (id: string, payload: PasivoUpdatePayload): Promise<Pasivo> =>
  apiFetch<Pasivo>(`/pasivos/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })

export interface PagarPasivoPayload {
  monto_pagado: number
  moneda_pago: Moneda
  medio_pago: MedioPago
  // Requerida solo si moneda_pago difiere de la moneda de la deuda ($/USD).
  cotizacion?: number | null
  fecha_cancelacion?: string | null
}

export const pagarPasivo = (id: string, payload: PagarPasivoPayload): Promise<Pasivo> =>
  apiFetch<Pasivo>(`/pasivos/${id}/pagar`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export type VueltoModo = 'SALDAR_EFECTIVO' | 'QUEDA_DEBIENDO'

export interface CancelarConChequePayload {
  cheque_id: string
  porcentaje_venta: number
  operador_id: string
  motivo: string
  fecha_cancelacion?: string | null
  // Requerido solo si el cheque cubre de más (diferencia > 0).
  vuelto_modo?: VueltoModo | null
}

export const cancelarPasivoConCheque = (
  id: string,
  payload: CancelarConChequePayload,
): Promise<Pasivo> =>
  apiFetch<Pasivo>(`/pasivos/${id}/cancelar-con-cheque`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

/**
 * Pago consolidado a un acreedor — el espejo del cobro por cliente (§2.c).
 *
 * El negocio le puede deber varias veces a la misma persona: le compró un lote
 * de dólares sin pagarlo, después un cheque, y encima le pidió plata prestada.
 * Cuando le paga **no está pagando una de esas deudas: está pagando lo que le
 * debe**. El importe se imputa de la deuda más vieja a la más nueva y todo entra
 * en una sola transacción, con su propia línea de caja por deuda.
 *
 * El acreedor es **texto libre** (no un cliente con id) y el backend lo matchea
 * exacto, sin distinguir mayúsculas. Agrupá con el mismo criterio o la pantalla
 * va a mostrar un total y el botón va a pagar otro.
 */

/** Una deuda alcanzada por el pago, y cuánto le tocó. */
export interface PasivoImputado {
  id: string
  concepto: string
  imputado: string
  saldo_restante: string
  cancelo: boolean
}

export interface PagoAcreedorResult {
  acreedor: string
  moneda_deuda: Moneda
  /** Las deudas alcanzadas, de la más vieja a la más nueva. */
  imputaciones: PasivoImputado[]
  /** Cuánto bajó la deuda en total, en `moneda_deuda`. */
  imputado: string
  saldo_restante: string
  cancelados: number
}

export interface PagarAcreedorPayload {
  acreedor: string
  /** Contra cuál de las dos colas se imputa: ARS y USD no se suman. */
  moneda_deuda: Moneda
  monto_pagado: number
  moneda_pago: Moneda
  medio_pago: MedioPago
  // Requerida solo si moneda_pago difiere de moneda_deuda ($/USD).
  cotizacion?: number | null
  fecha?: string | null
}

export const pagarAcreedor = (payload: PagarAcreedorPayload): Promise<PagoAcreedorResult> =>
  apiFetch<PagoAcreedorResult>('/pasivos/acreedores/pagar', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

/**
 * Entrega un cheque de cartera contra todas las deudas **en pesos** del acreedor.
 *
 * El cheque vale su neto (nominal menos el descuento pactado) y con eso se van
 * llenando las deudas, de la más vieja a la más nueva. No mueve efectivo: el
 * desembolso ocurrió al comprar el cheque, acá solo cambia de manos el papel.
 * Un cheque es un instrumento en pesos, así que las deudas en dólares no entran.
 */
export interface CancelarAcreedorChequePayload {
  acreedor: string
  cheque_id: string
  porcentaje_venta: number
  operador_id: string
  motivo: string
  fecha?: string | null
  // Requerido solo si el neto del cheque cubre de más.
  vuelto_modo?: VueltoModo | null
}

export const cancelarAcreedorConCheque = (
  payload: CancelarAcreedorChequePayload,
): Promise<PagoAcreedorResult> =>
  apiFetch<PagoAcreedorResult>('/pasivos/acreedores/cancelar-con-cheque', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
