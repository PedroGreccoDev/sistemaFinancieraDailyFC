// Estado de sesión real del panel. Guarda el token en localStorage (dura hasta
// cerrar sesión, sobrevive a recargar/cerrar el navegador) y expone el usuario
// actual (con `is_admin`). En modo demo (VITE_MOCK=1) cortocircuita con un admin
// mock para que el frontend siga navegable sin backend.

import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  clearToken, getCachedUser, getToken, setCachedUser, setToken, setUnauthorizedHandler,
} from '../api/client'
import { getMe, loginReq } from '../api/auth'
import type { AuthUser } from '../api/auth'

const MOCK = import.meta.env.VITE_MOCK === '1'

const MOCK_USER: AuthUser = {
  id: 'mock-admin', username: 'm.gonzalez', phone: null,
  is_admin: true, activo: true, created_at: new Date().toISOString(),
}

interface AuthState {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  // Con token, arrancamos con el usuario cacheado (rehidratación instantánea, sin
  // parpadeo al login) y revalidamos contra /auth/me en segundo plano.
  const cached = MOCK ? MOCK_USER : (getToken() ? getCachedUser<AuthUser>() : null)
  const [user, setUser] = useState<AuthUser | null>(cached)
  // Solo bloqueamos con spinner si hay token pero todavía no tenemos usuario cacheado.
  const [loading, setLoading] = useState<boolean>(MOCK ? false : (Boolean(getToken()) && !cached))

  // Hidratación inicial: con token guardado, revalidar el usuario actual.
  useEffect(() => {
    if (MOCK) return
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    let vivo = true
    getMe()
      .then((u) => { if (vivo) { setUser(u); setCachedUser(u) } })
      .catch(() => {
        // apiFetch limpia el token ante 401 (sesión revocada/inválida) → desloguear.
        // Si el token sigue presente, fue un error de red o el backend dormido: NO
        // borramos la sesión, conservamos el usuario cacheado para no echar al operador.
        if (!getToken() && vivo) setUser(null)
      })
      .finally(() => { if (vivo) setLoading(false) })
    return () => { vivo = false }
  }, [])

  // 401 en ruta protegida (sesión vencida/revocada) → limpiar y volver al login.
  useEffect(() => {
    if (MOCK) return
    setUnauthorizedHandler(() => {
      setUser(null)
      navigate('/login', { replace: true })
    })
    return () => setUnauthorizedHandler(null)
  }, [navigate])

  async function login(username: string, password: string) {
    if (MOCK) { setUser(MOCK_USER); return }
    const { token, user: u } = await loginReq(username, password)
    setToken(token)
    setCachedUser(u)
    setUser(u)
  }

  function logout() {
    clearToken()
    setUser(null)
    navigate('/login', { replace: true })
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth debe usarse dentro de <AuthProvider>')
  return ctx
}
