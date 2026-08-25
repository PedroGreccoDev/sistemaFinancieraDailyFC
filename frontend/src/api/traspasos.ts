import { apiFetch } from './client'
import type { Traspaso, TraspasoCreate } from '../types'

/**
 * Traspaso entre cajas: depositar en la cuenta o extraer de ella.
 *
 * No cambia lo que el negocio tiene —la misma plata cambia de bolsillo— pero sí
 * mueve los dos saldos, en sentidos opuestos. Sin esta operación las dos cajas
 * se despegan de la realidad el día del primer depósito.
 */
export const listarTraspasos = (params?: {
  desde?: string
  hasta?: string
}): Promise<Traspaso[]> => {
  const q = new URLSearchParams()
  if (params?.desde) q.set('desde', params.desde)
  if (params?.hasta) q.set('hasta', params.hasta)
  const qs = q.toString()
  return apiFetch<Traspaso[]>(`/traspasos${qs ? `?${qs}` : ''}`)
}

export const crearTraspaso = (payload: TraspasoCreate): Promise<Traspaso> =>
  apiFetch<Traspaso>('/traspasos', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

/** Deshace el traspaso entero: las dos líneas o ninguna. */
export const anularTraspaso = (id: string): Promise<void> =>
  apiFetch<void>(`/traspasos/${id}`, { method: 'DELETE' })
