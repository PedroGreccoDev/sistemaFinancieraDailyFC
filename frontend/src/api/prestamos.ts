import { apiFetch } from './client'
import type { Prestamo } from '../types'

export const getPrestamos = (estado?: string): Promise<Prestamo[]> =>
  apiFetch<Prestamo[]>(`/prestamos${estado ? `?estado=${estado}` : ''}`)
