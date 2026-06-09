import { apiFetch } from './client'
import type { GastoOperativo } from '../types'

export const getGastos = (): Promise<GastoOperativo[]> =>
  apiFetch<GastoOperativo[]>('/gastos-operativos')
