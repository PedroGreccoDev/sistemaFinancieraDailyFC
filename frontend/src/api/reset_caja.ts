import { apiFetch } from './client'

/**
 * Reset de caja: vaciar el libro sin perder lo que se debe.
 *
 * Borra el historial de caja y el stock de dólares para arrancar con saldos
 * contados de verdad. Conserva los cheques en cartera, lo que los clientes
 * deben y lo que el negocio debe.
 *
 * Además mueve la línea de corte: todo lo que quedó vivo pasa a contar como
 * preexistente, así corregirlo después no vuelve a mover la caja. Lo que se
 * cargue a partir de ese momento es operación normal, aunque sea el mismo día.
 */
export interface ResetCajaResumen {
  movimientos_caja: number
  movimientos_efectivo: number
  ajustes_caja: number
  gastos_operativos: number
  /** Cheques que pasan a contar como preexistentes (siguen en cartera). */
  cheques_marcados: number
  /** Dónde queda la línea: el día anterior al reset. */
  fecha_corte: string | null
  conserva: Record<string, number>
}

/** Frase exacta que hay que escribir para ejecutarlo. */
export const CONFIRMACION_RESET = 'RESETEAR CAJA'

/** Qué se borraría y qué queda intacto. No toca nada. */
export const previsualizarReset = (): Promise<ResetCajaResumen> =>
  apiFetch<ResetCajaResumen>('/reset-caja')

/** Ejecuta el reset. Irreversible. */
export const ejecutarReset = (payload: {
  operador_id: string
  confirmacion: string
}): Promise<ResetCajaResumen> =>
  apiFetch<ResetCajaResumen>('/reset-caja', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
