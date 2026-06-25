import { apiFetch } from './client'
import type { MovimientoEfectivo } from '../types'

export const getMovimientos = (): Promise<MovimientoEfectivo[]> =>
  apiFetch<MovimientoEfectivo[]>('/movimientos-efectivo')

// Corrección de una operación de divisas. `monto`/`cotizacion_aplicada` solo se
// aceptan si la operación no está trabada en la cadena FIFO (lo valida el backend).
export interface MovimientoUpdatePayload {
  monto?: number
  cotizacion_aplicada?: number
  cliente_id?: string | null
  observaciones?: string | null
}

export const editarMovimiento = (
  id: string,
  payload: MovimientoUpdatePayload,
): Promise<MovimientoEfectivo> =>
  apiFetch<MovimientoEfectivo>(`/movimientos-efectivo/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
