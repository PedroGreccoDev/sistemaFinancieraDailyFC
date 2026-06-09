import { apiFetch } from './client'
import type { Pasivo, PasivoEstado } from '../types'

export const getPasivos = (estado?: PasivoEstado): Promise<Pasivo[]> => {
  const qs = estado ? `?estado=${estado}` : ''
  return apiFetch<Pasivo[]>(`/pasivos${qs}`)
}

export const cancelarPasivo = (id: string): Promise<Pasivo> =>
  apiFetch<Pasivo>(`/pasivos/${id}/cancelar`, { method: 'POST', body: JSON.stringify({}) })
