import { apiFetch } from './client'
import type { Cuota, CuotaCobrarConChequeResult, CuotasLoteCobrarConChequeResult, Frecuencia, MedioPago, Moneda, Prestamo, PrestamoTipo } from '../types'

export const getPrestamos = (estado?: string): Promise<Prestamo[]> =>
  apiFetch<Prestamo[]>(`/prestamos${estado ? `?estado=${estado}` : ''}`)

// Alta en cualquiera de las dos modalidades. El backend rechaza la mezcla: un
// préstamo a interés fijo no lleva cuadro de cuotas y uno normal no lleva
// interés por período.
interface PrestamoCreate {
  cliente_id: string
  tipo_prestamo?: PrestamoTipo
  credito: number
  moneda: Moneda
  fecha_inicio?: string | null
  // Solo NORMAL
  cuotas?: number
  frecuencia?: Frecuencia
  total_a_cobrar?: number
  // Solo INTERES_FIJO
  monto_interes_fijo?: number
  dia_cobro?: string | null
}

export const createPrestamo = (payload: PrestamoCreate): Promise<Prestamo> =>
  apiFetch<Prestamo>('/prestamos', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// Corrección de la carga de un préstamo. Solo permitido si ninguna cuota fue
// cobrada (lo valida el backend); regenera el cuadro de cuotas.
export interface PrestamoUpdatePayload {
  credito?: number
  moneda?: Moneda
  cuotas?: number
  frecuencia?: Frecuencia
  total_a_cobrar?: number
  fecha_inicio?: string | null
}

export const editarPrestamo = (id: string, payload: PrestamoUpdatePayload): Promise<Prestamo> =>
  apiFetch<Prestamo>(`/prestamos/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

// Pago de importe libre (parcial o total) contra un préstamo, en efectivo. Se
// imputa a las cuotas más viejas primero. `moneda_pago` puede diferir de la del
// préstamo; en ese caso `cotizacion` (pesos por 1 USD) es obligatoria.
export interface PrestamoPagoPayload {
  monto_pagado: number
  moneda_pago: Moneda
  /** Por cuál de las dos cajas pasa la plata. Efectivo si no se manda. */
  medio_pago?: MedioPago
  cotizacion?: number | null
  /** Costo ($/USD) con el que los dólares cobrados entran al stock vendible. */
  cotizacion_stock?: number | null
  fecha_cobro?: string | null
}

export const pagarPrestamo = (id: string, payload: PrestamoPagoPayload): Promise<Prestamo> =>
  apiFetch<Prestamo>(`/prestamos/${encodeURIComponent(id)}/pagar`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// ── Préstamo a interés fijo ──────────────────────────────────────────────────
// Las tres operaciones que mueven plata van en la moneda del préstamo: el
// interés se pactó en ella y el capital se devuelve en lo que se prestó.

interface InteresFijoOperacionBase {
  /** Por cuál de las dos cajas pasa la plata. Efectivo si no se manda. */
  medio_pago?: MedioPago
  fecha_cobro?: string | null
  /** Costo ($/USD) con el que los dólares cobrados entran al stock vendible. */
  cotizacion_stock?: number | null
}

export interface CobrarInteresPayload extends InteresFijoOperacionBase {
  /** Períodos puntuales. Sin esto cobra el vigente (el último devengado). */
  cuota_ids?: string[]
  /** Sumar también los períodos viejos impagos, que se acumulan. */
  incluir_mora?: boolean
}

export const cobrarInteres = (id: string, payload: CobrarInteresPayload): Promise<Prestamo> =>
  apiFetch<Prestamo>(`/prestamos/${encodeURIComponent(id)}/interes-fijo/cobrar-interes`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface AbonarCapitalPayload extends InteresFijoOperacionBase {
  monto: number
}

export const abonarCapital = (id: string, payload: AbonarCapitalPayload): Promise<Prestamo> =>
  apiFetch<Prestamo>(`/prestamos/${encodeURIComponent(id)}/interes-fijo/abonar-capital`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface CancelarInteresFijoPayload extends InteresFijoOperacionBase {
  /** Si queda en false, la mora sigue debiéndose y el préstamo NO se cancela. */
  incluir_mora?: boolean
}

export const cancelarInteresFijo = (id: string, payload: CancelarInteresFijoPayload): Promise<Prestamo> =>
  apiFetch<Prestamo>(`/prestamos/${encodeURIComponent(id)}/interes-fijo/cancelar`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface InteresFijoUpdatePayload {
  monto_interes_fijo?: number
  /** Solo se puede mover antes del primer período: es el ancla de los ciclos. */
  dia_cobro?: string | null
  /** Llevar el nuevo interés también al período en curso (si no recibió pagos). */
  aplicar_a_periodo_vigente?: boolean
}

export const editarInteresFijo = (id: string, payload: InteresFijoUpdatePayload): Promise<Prestamo> =>
  apiFetch<Prestamo>(`/prestamos/${encodeURIComponent(id)}/interes-fijo`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const cobrarCuotaEfectivo = (
  prestamoId: string,
  cuotaId: string,
  fechaCobro: string | null,
): Promise<void> =>
  apiFetch(`/prestamos/${prestamoId}/cuotas/${cuotaId}/cobros`, {
    method: 'POST',
    body: JSON.stringify({ fecha_cobro: fechaCobro }),
  })

interface CobrarConChequePayload {
  nro_cheque: string
  banco: string | null
  monto: number
  porcentaje_compra: number
  fecha_emision: string | null
  fecha_pago: string | null
  cliente_origen_id: string | null
  fecha_cobro: string | null
}

export const cobrarCuotaConCheque = (
  prestamoId: string,
  cuotaId: string,
  payload: CobrarConChequePayload,
): Promise<CuotaCobrarConChequeResult> =>
  apiFetch<CuotaCobrarConChequeResult>(
    `/prestamos/${prestamoId}/cuotas/${cuotaId}/cobrar-con-cheque`,
    { method: 'POST', body: JSON.stringify(payload) },
  )

interface CobrarLotePayload {
  cuota_ids: string[]
  fecha_cobro: string | null
}

export const cobrarCuotasLote = (
  prestamoId: string,
  payload: CobrarLotePayload,
): Promise<Cuota[]> =>
  apiFetch<Cuota[]>(`/prestamos/${prestamoId}/cuotas/cobrar-lote`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

interface CobrarConChequeLotePayload {
  cuota_ids: string[]
  nro_cheque: string
  banco: string | null
  monto: number
  porcentaje_compra: number
  fecha_emision: string | null
  fecha_pago: string | null
  cliente_origen_id: string | null
  fecha_cobro: string | null
}

export const cobrarCuotasConChequeLote = (
  prestamoId: string,
  payload: CobrarConChequeLotePayload,
): Promise<CuotasLoteCobrarConChequeResult> =>
  apiFetch<CuotasLoteCobrarConChequeResult>(
    `/prestamos/${prestamoId}/cuotas/cobrar-con-cheque-lote`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
