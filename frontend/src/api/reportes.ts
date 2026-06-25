import { apiFetch } from './client'
import type { CuotaCobradaHistorialItem, ReporteCaja } from '../types'

export const getReporteCaja = (desde: string, hasta: string): Promise<ReporteCaja> =>
  apiFetch<ReporteCaja>(`/reportes/caja?desde=${desde}&hasta=${hasta}`)

export const getCobrosHistorial = (desde: string, hasta: string): Promise<CuotaCobradaHistorialItem[]> =>
  apiFetch<CuotaCobradaHistorialItem[]>(`/reportes/cobros-cuotas?desde=${desde}&hasta=${hasta}`)
