// Guard de rutas. Sin sesión → redirige a /login. Con `adminOnly`, además exige
// rol admin (si no, redirige a / ). Mientras se hidrata la sesión (GET /auth/me)
// muestra un placeholder para no parpadear hacia el login.

import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function ProtectedRoute({ adminOnly = false }: { adminOnly?: boolean }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
        <svg className="spin" width={26} height={26} viewBox="0 0 24 24" fill="none" stroke="#818cf8" strokeWidth="2.5" strokeLinecap="round">
          <path d="M21 12a9 9 0 1 1-6.2-8.5" opacity="0.85" />
        </svg>
      </div>
    )
  }

  if (!user) return <Navigate to="/login" replace />
  if (adminOnly && !user.is_admin) return <Navigate to="/" replace />

  return <Outlet />
}
