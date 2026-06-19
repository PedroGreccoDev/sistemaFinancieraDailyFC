// Usuario actual — STUB temporal de UI.
//
// Todavía NO existe autenticación real (ni backend ni sesión). Este módulo
// expone un usuario fijo para que el Navbar y la pantalla /usuarios puedan
// renderizar el rol, las iniciales y el botón de cerrar sesión tal como los
// define el diseño. Reemplazar por el estado de sesión real cuando se cablee
// el backend de auth.
// TODO: cablear backend de auth (leer usuario de la sesión / token).

export type Rol = 'admin' | 'usuario'

export interface CurrentUser {
  username: string
  initials: string
  rol: Rol
}

const MOCK_USER: CurrentUser = {
  username: 'm.gonzalez',
  initials: 'MG',
  rol: 'admin',
}

export function useCurrentUser(): CurrentUser {
  return MOCK_USER
}

/** Iniciales (máx. 2) a partir de un usuario tipo "nombre.apellido" o "n.perez". */
export function iniciales(username: string): string {
  const partes = username.split(/[.\s_-]+/).filter(Boolean)
  const ini = partes.slice(0, 2).map((p) => p[0] ?? '').join('')
  return (ini || username.slice(0, 2)).toUpperCase()
}
