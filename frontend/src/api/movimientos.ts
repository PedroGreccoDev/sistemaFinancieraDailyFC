import { apiFetch } from './client'
import type { MovimientoEfectivo } from '../types'

export const getMovimientos = (): Promise<MovimientoEfectivo[]> =>
  apiFetch<MovimientoEfectivo[]>('/movimientos-efectivo')

// Alta de una operación de divisas (equivale al MOVIMIENTO_EFECTIVO del bot).
// La cotización SIEMPRE la dicta el operador: el sistema no la consulta ni la asume.
export interface MovimientoCreatePayload {
  tipo: 'COMPRA' | 'VENTA'
  moneda: 'ARS' | 'USD'
  monto: number
  cotizacion_aplicada: number
  cliente_id?: string | null
  observaciones?: string | null
  // Solo en COMPRA. Omitir = se pagó todo (la operación normal). Menos que
  // monto × cotización deja el resto a deber: no descuenta la caja y genera la
  // deuda con el vendedor, que pasa a ser obligatorio (§Comprar sin abonar).
  monto_abonado?: number
}

export const crearMovimiento = (
  payload: MovimientoCreatePayload,
): Promise<MovimientoEfectivo> =>
  apiFetch<MovimientoEfectivo>('/movimientos-efectivo', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

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
