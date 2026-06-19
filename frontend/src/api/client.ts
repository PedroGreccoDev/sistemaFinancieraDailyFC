export const API_BASE = '/api/v1'

// Clave del token de sesión en localStorage (sobrevive a recargar/cerrar el navegador).
const TOKEN_KEY = 'auth_token'

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string): void => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY)

// Handler de "sesión inválida" (401 en ruta protegida). Lo setea el AuthContext
// para redirigir vía router sin recargar; si nadie lo registró, caemos a un
// redirect duro. Evita el import circular client ↔ AuthContext.
let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: (() => void) | null): void => {
  onUnauthorized = fn
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  // Modo demo: datos falsos locales sin backend (se activa con VITE_MOCK=1).
  if (import.meta.env.VITE_MOCK === '1') {
    const { mockFetch } = await import('./mock')
    return mockFetch<T>(path, options)
  }

  const token = getToken()
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers ?? {}),
    },
  })

  if (!res.ok) {
    // Sesión vencida/revocada en una ruta protegida → desloguear y volver al login.
    // Las rutas públicas de auth (/auth/login, /auth/forgot-password, etc.) manejan
    // su propio 401 (credenciales/código inválidos) y NO deben disparar el redirect.
    if (res.status === 401 && !path.startsWith('/auth/')) {
      clearToken()
      if (onUnauthorized) onUnauthorized()
      else window.location.assign('/login')
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail?: string }).detail ?? 'Error desconocido')
  }

  // 204 No Content (p. ej. DELETE) no trae body.
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}
