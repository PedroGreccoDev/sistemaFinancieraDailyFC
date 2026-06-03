import { apiFetch } from './client'
import type { Cliente } from '../types'

export const getClientes = (): Promise<Cliente[]> =>
  apiFetch<Cliente[]>('/clientes')
