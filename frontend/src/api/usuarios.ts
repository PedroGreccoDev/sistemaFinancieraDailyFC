import { apiFetch } from './client'
import type { AuthUser } from './auth'

export interface Invitacion {
  id: string
  phone: string | null
  is_admin: boolean
  expires_at: string
  created_at: string
}

export interface InvitacionCreada {
  invitacion: Invitacion
  link: string
  enviada_por_whatsapp: boolean
}

export interface UsuarioActualizado {
  usuario: AuthUser
  temp_password: string | null
}

export interface UsuarioUpdatePayload {
  activo?: boolean
  is_admin?: boolean
  phone?: string | null
  reset_password?: boolean
}

// ── Invitaciones ──────────────────────────────────────────────────────────────
export const getInvitaciones = (): Promise<Invitacion[]> => apiFetch<Invitacion[]>('/invitaciones')

export const crearInvitacion = (phone: string | null, is_admin: boolean): Promise<InvitacionCreada> =>
  apiFetch<InvitacionCreada>('/invitaciones', {
    method: 'POST',
    body: JSON.stringify({ phone, is_admin }),
  })

export const revocarInvitacion = (id: string): Promise<void> =>
  apiFetch<void>(`/invitaciones/${id}`, { method: 'DELETE' })

// ── Usuarios ────────────────────────────────────────────────────────────────
export const getUsuarios = (): Promise<AuthUser[]> => apiFetch<AuthUser[]>('/usuarios')

export const actualizarUsuario = (
  id: string,
  payload: UsuarioUpdatePayload,
): Promise<UsuarioActualizado> =>
  apiFetch<UsuarioActualizado>(`/usuarios/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
