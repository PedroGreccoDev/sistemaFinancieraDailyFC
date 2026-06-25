import { apiFetch } from './client'
import type { Cuota, Prestamo, Moneda, Frecuencia, CuotaCobrarConChequeResult, CuotasLoteCobrarConChequeResult } from '../types'

export const getPrestamos = (estado?: string): Promise<Prestamo[]> =>
  apiFetch<Prestamo[]>(`/prestamos${estado ? `?estado=${estado}` : ''}`)

interface PrestamoCreate {
  cliente_id: string
  credito: number
  moneda: Moneda
  cuotas: number
  frecuencia: Frecuencia
  total_a_cobrar: number
  fecha_inicio?: string | null
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
