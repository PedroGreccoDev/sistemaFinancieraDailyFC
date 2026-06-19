import { apiFetch } from './client'

export interface AuthUser {
  id: string
  username: string
  phone: string | null
  is_admin: boolean
  activo: boolean
  must_change_password: boolean
  created_at: string
}

export interface TokenResponse {
  token: string
  user: AuthUser
}

export const loginReq = (username: string, password: string): Promise<TokenResponse> =>
  apiFetch<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })

export const getMe = (): Promise<AuthUser> => apiFetch<AuthUser>('/auth/me')

export const cambiarPasswordReq = (
  current_password: string,
  new_password: string,
): Promise<TokenResponse> =>
  apiFetch<TokenResponse>('/auth/cambiar-password', {
    method: 'POST',
    body: JSON.stringify({ current_password, new_password }),
  })

// Cambio obligatorio tras ingresar con una clave temporal: no reenvía la temporal,
// solo la nueva (el login con la temporal ya probó que la conoce).
export const definirPasswordReq = (
  new_password: string,
): Promise<TokenResponse> =>
  apiFetch<TokenResponse>('/auth/definir-password', {
    method: 'POST',
    body: JSON.stringify({ new_password }),
  })

export const forgotPassword = (username: string): Promise<{ detail: string }> =>
  apiFetch<{ detail: string }>('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ username }),
  })

export const resetPassword = (
  username: string,
  code: string,
  new_password: string,
): Promise<{ detail: string }> =>
  apiFetch<{ detail: string }>('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ username, code, new_password }),
  })

export const validarInvitacion = (token: string): Promise<{ phone: string | null }> =>
  apiFetch<{ phone: string | null }>(`/auth/invitacion/${encodeURIComponent(token)}`)

export const registrarReq = (
  token: string,
  username: string,
  password: string,
): Promise<TokenResponse> =>
  apiFetch<TokenResponse>('/auth/registrar', {
    method: 'POST',
    body: JSON.stringify({ token, username, password }),
  })
