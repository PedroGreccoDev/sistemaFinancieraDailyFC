import { apiFetch } from './client'
import type { Cheque, Moneda } from '../types'
import type { VueltoModo } from './deudas_simples'

/**
 * Cobro consolidado de la deuda de un cliente (pestaña General).
 *
 * Un cliente puede deber por tres caminos a la vez —un cheque fiado, una deuda
 * libre y las cuotas de un préstamo— y cuando entrega plata no está pagando una
 * de esas: está pagando lo que debe. El importe se imputa de la operación más
 * vieja a la más nueva (por su fecha de origen), cruzando tipos.
 *
 * `moneda_deuda` dice contra qué deuda se cobra: ARS y USD son cajas distintas
 * y no se suman. Los cheques fiados son siempre en pesos, así que en USD solo
 * entran deudas libres y préstamos en dólares. El pago sí puede venir en la otra
 * moneda con su cotización.
 */
export type RenglonTipo = 'fiado' | 'deuda_simple' | 'prestamo'

/** Una deuda alcanzada por el cobro, y cuánto le tocó. */
export interface RenglonImputado {
  tipo: RenglonTipo
  id: string
  detalle: string
  fecha: string
  imputado: string
  saldo_restante: string
  cancelado: boolean
}

export interface CobroClienteResult {
  cliente_id: string
  cliente_nombre: string
  moneda_deuda: Moneda
  /** Las operaciones alcanzadas, en el orden en que se imputaron. */
  renglones: RenglonImputado[]
  /** Cuánto bajó la deuda en total, en la moneda de la deuda. */
  imputado: string
  canceladas: number
  saldo_restante: string
}

export interface CobrarClientePayload {
  cliente_id: string
  moneda_deuda: Moneda
  monto_cobrado: number
  moneda_pago: Moneda
  // Requerida solo si moneda_pago difiere de moneda_deuda ($/USD).
  cotizacion?: number | null
  /** Costo ($/USD) con el que los dólares cobrados entran al stock vendible. */
  cotizacion_stock?: number | null
  fecha_cobro?: string | null
}

export const cobrarCliente = (payload: CobrarClientePayload): Promise<CobroClienteResult> =>
  apiFetch<CobroClienteResult>('/deudores/cobrar-cliente', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

/**
 * El cliente cancela su deuda entregando un cheque.
 *
 * Salda por el valor neto del cheque (`monto × (1 − %compra)`), imputado de la
 * operación más vieja a la más nueva igual que el efectivo, y no mueve la caja:
 * el cheque entra a cartera a su nombre y la plata se reconoce al venderlo o
 * cobrarlo. Si cubre todo y sobra, `vuelto_modo` decide qué se hace con la
 * diferencia —que va en pesos, porque el cheque es un instrumento en pesos—.
 */
export interface CobrarClienteConChequePayload {
  cliente_id: string
  moneda_deuda: Moneda
  nro_cheque_pago: string
  banco_pago?: string | null
  monto_cheque: number
  porcentaje_compra_cheque: number
  fecha_emision?: string | null
  fecha_pago?: string | null
  // Requerida solo si la deuda es en USD (el cheque siempre entra en pesos).
  cotizacion?: number | null
  /** Costo ($/USD) con el que los dólares cobrados entran al stock vendible. */
  cotizacion_stock?: number | null
  // Obligatorio solo si el cheque cubre todo y sobra.
  vuelto_modo?: VueltoModo | null
  fecha_cobro?: string | null
}

export interface CobroClienteChequeResult extends CobroClienteResult {
  cheque_ingresado: Cheque
  /** En ARS: > 0 el cheque cubrió todo y sobró esto. */
  vuelto_ars: string
  vuelto_modo: VueltoModo | null
}

export const cobrarClienteConCheque = (
  payload: CobrarClienteConChequePayload,
): Promise<CobroClienteChequeResult> =>
  apiFetch<CobroClienteChequeResult>('/deudores/cobrar-cliente-con-cheque', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
