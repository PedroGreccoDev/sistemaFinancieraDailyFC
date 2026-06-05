import { apiFetch } from './client'
import type { MovimientoEfectivo } from '../types'

export const getMovimientos = (): Promise<MovimientoEfectivo[]> =>
  apiFetch<MovimientoEfectivo[]>('/movimientos-efectivo')
