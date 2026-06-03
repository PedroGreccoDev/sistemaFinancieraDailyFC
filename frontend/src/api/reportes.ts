import { apiFetch } from './client'
import type { ReporteGanancias } from '../types'

export const getReporteGanancias = (desde: string, hasta: string): Promise<ReporteGanancias> =>
  apiFetch<ReporteGanancias>(`/reportes/ganancias?desde=${desde}&hasta=${hasta}`)
