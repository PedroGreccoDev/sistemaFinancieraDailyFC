import { apiFetch } from './client'
import type { GastoOperativo, MedioPago, Moneda } from '../types'

export const getGastos = (): Promise<GastoOperativo[]> =>
  apiFetch<GastoOperativo[]>('/gastos-operativos')

export interface GastoCreate {
  concepto: string
  monto: number
  moneda?: Moneda
  /** Por cuál de las dos cajas sale. Efectivo si no se manda. */
  medio_pago?: MedioPago
  fecha_operacion?: string | null
  hora_operacion?: string | null
  observaciones?: string | null
}

export const createGasto = (payload: GastoCreate): Promise<GastoOperativo> =>
  apiFetch<GastoOperativo>('/gastos-operativos', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface GastoUpdatePayload {
  concepto?: string
  monto?: number
  moneda?: Moneda
  fecha_operacion?: string | null
  observaciones?: string | null
}

export const editarGasto = (id: string, payload: GastoUpdatePayload): Promise<GastoOperativo> =>
  apiFetch<GastoOperativo>(`/gastos-operativos/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
