import { apiFetch } from './client'
import type { CuotaCobradaHistorialItem, MovimientoUnificado, ReporteCaja } from '../types'

export const getMovimientosUnificados = (
  desde: string,
  hasta: string,
): Promise<MovimientoUnificado[]> =>
  apiFetch<MovimientoUnificado[]>(`/reportes/movimientos?desde=${desde}&hasta=${hasta}`)

export const getReporteCaja = (desde: string, hasta: string): Promise<ReporteCaja> =>
  apiFetch<ReporteCaja>(`/reportes/caja?desde=${desde}&hasta=${hasta}`)

export const getCobrosHistorial = (desde: string, hasta: string): Promise<CuotaCobradaHistorialItem[]> =>
  apiFetch<CuotaCobradaHistorialItem[]>(`/reportes/cobros-cuotas?desde=${desde}&hasta=${hasta}`)
