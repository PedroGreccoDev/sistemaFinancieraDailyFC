import { apiFetch } from './client'
import type { Prestamo, Moneda, Frecuencia, CuotaCobrarConChequeResult } from '../types'

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
