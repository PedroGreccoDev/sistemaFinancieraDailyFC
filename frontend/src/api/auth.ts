import { apiFetch } from './client'

export interface AuthUser {
  id: string
  username: string
  phone: string | null
  is_admin: boolean
  activo: boolean
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
