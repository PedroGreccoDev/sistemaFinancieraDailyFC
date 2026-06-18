import { apiFetch } from './client'
import type { CuotaCobradaHistorialItem, ReporteGanancias } from '../types'

export const getReporteGanancias = (desde: string, hasta: string): Promise<ReporteGanancias> =>
  apiFetch<ReporteGanancias>(`/reportes/ganancias?desde=${desde}&hasta=${hasta}`)

export const getCobrosHistorial = (desde: string, hasta: string): Promise<CuotaCobradaHistorialItem[]> =>
  apiFetch<CuotaCobradaHistorialItem[]>(`/reportes/cobros-cuotas?desde=${desde}&hasta=${hasta}`)
