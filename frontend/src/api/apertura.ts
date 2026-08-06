import { apiFetch } from './client'

/**
 * Apertura del sistema: los saldos con los que el negocio arrancó a usarlo.
 *
 * Cuando el sistema se puso en marcha el negocio ya venía funcionando: había
 * efectivo en el cajón y cheques en cartera comprados tiempo atrás. Los dos son
 * saldos de apertura, no operaciones del día.
 */
export interface ConfiguracionApertura {
  /** Hasta este día inclusive, los cheques cargados son cartera preexistente. */
  fecha_corte_carga_inicial: string | null
  saldo_inicial_ars: string | null
  saldo_inicial_usd: string | null
  /** Día al que corresponde el efectivo, no el día en que se cargó. */
  fecha_saldo_inicial: string | null
  definido_por: string | null
  definido_at: string | null
  saldo_definido: boolean
}

export interface FechaCorteResponse {
  fecha_corte: string
  cheques_marcados: number
  lineas_revertidas: number
}

export const getApertura = (): Promise<ConfiguracionApertura> =>
  apiFetch<ConfiguracionApertura>('/apertura')

export const definirFechaCorte = (payload: {
  fecha_corte: string
  operador_id: string
}): Promise<FechaCorteResponse> =>
  apiFetch<FechaCorteResponse>('/apertura/fecha-corte', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const definirSaldoInicial = (payload: {
  saldo_ars: number
  saldo_usd: number
  fecha: string
  operador_id: string
  forzar?: boolean
}): Promise<ConfiguracionApertura> =>
  apiFetch<ConfiguracionApertura>('/apertura/saldo-inicial', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
