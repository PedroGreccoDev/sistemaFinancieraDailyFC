import { apiFetch } from './client'
import type { MovimientoUnificado, ReporteCaja } from '../types'

export const getMovimientosUnificados = (
  desde: string,
  hasta: string,
): Promise<MovimientoUnificado[]> =>
  apiFetch<MovimientoUnificado[]>(`/reportes/movimientos?desde=${desde}&hasta=${hasta}`)

export const getReporteCaja = (desde: string, hasta: string): Promise<ReporteCaja> =>
  apiFetch<ReporteCaja>(`/reportes/caja?desde=${desde}&hasta=${hasta}`)
