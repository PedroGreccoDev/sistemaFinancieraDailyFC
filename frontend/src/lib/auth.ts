// Usuario actual derivado de la sesión real (AuthContext). Mantiene la misma
// forma {username, initials, rol} que consumen Navbar y la pantalla /usuarios.

import { useAuth } from '../auth/AuthContext'

export type Rol = 'admin' | 'usuario'

export interface CurrentUser {
  username: string
  initials: string
  rol: Rol
}

/** Iniciales (máx. 2) a partir de un usuario tipo "nombre.apellido" o "n.perez". */
export function iniciales(username: string): string {
  const partes = username.split(/[.\s_-]+/).filter(Boolean)
  const ini = partes.slice(0, 2).map((p) => p[0] ?? '').join('')
  return (ini || username.slice(0, 2)).toUpperCase()
}

/** Usuario actual de la sesión. Asume que hay sesión (rutas protegidas). */
export function useCurrentUser(): CurrentUser {
  const { user } = useAuth()
  const username = user?.username ?? ''
  return {
    username,
    initials: iniciales(username || '?'),
    rol: user?.is_admin ? 'admin' : 'usuario',
  }
}
