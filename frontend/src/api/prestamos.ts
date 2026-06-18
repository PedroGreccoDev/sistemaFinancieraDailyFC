import { apiFetch } from './client'
import type { Prestamo, Moneda, Frecuencia } from '../types'

export const getPrestamos = (estado?: string): Promise<Prestamo[]> =>
  apiFetch<Prestamo[]>(`/prestamos${estado ? `?estado=${estado}` : ''}`)

interface PrestamoCreate {
  cliente_id: string
  credito: number
  moneda: Moneda
  cuotas: number
  frecuencia: Frecuencia
  total_a_cobrar: number
  fecha_inicio?: string | null
}

export const createPrestamo = (payload: PrestamoCreate): Promise<Prestamo> =>
  apiFetch<Prestamo>('/prestamos', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
