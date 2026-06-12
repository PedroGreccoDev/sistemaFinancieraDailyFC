import { apiFetch } from './client'
import type { Cliente } from '../types'

export const getClientes = (): Promise<Cliente[]> =>
  apiFetch<Cliente[]>('/clientes')

interface ClienteCreate {
  nombre: string
  telefono?: string | null
  cuit?: string | null
}

export const createCliente = (payload: ClienteCreate): Promise<Cliente> =>
  apiFetch<Cliente>('/clientes', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
