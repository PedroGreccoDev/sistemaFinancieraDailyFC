import { useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, Outlet } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Cartera from './pages/Cartera'
import Deudores from './pages/Deudores'
import DeudoresPrestamos from './pages/DeudoresPrestamos'
import Pasivos from './pages/Pasivos'
import Reportes from './pages/Reportes'
import Fiados from './pages/Fiados'
import Movimientos from './pages/Movimientos'
import Configuracion from './pages/Configuracion'
import Usuarios from './pages/Usuarios'
import Login from './pages/auth/Login'
import Recuperar from './pages/auth/Recuperar'
import Registro from './pages/auth/Registro'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './auth/AuthContext'
import { ToastProvider } from './lib/toast'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 15_000,
    },
  },
})

// Shell del panel: navbar + contenido. Las pantallas de autenticación
// (login/recuperar/registro) quedan fuera de este layout (pantalla completa,
// sin navbar). El acceso al shell está protegido por <ProtectedRoute> (ver más
// abajo): sin sesión válida se redirige a /login.
function AppShell() {
  const mainRef = useRef<HTMLElement>(null)

  // Bloquea el scroll del fondo (el contenedor <main>) mientras haya cualquier
  // modal abierto. Detectamos los modales por su clase `.modal-overlay` con un
  // MutationObserver, así cubre todos los modales sin tener que instrumentarlos
  // uno por uno. overflow:hidden conserva el scrollTop, no hay salto al cerrar.
  useEffect(() => {
    const main = mainRef.current
    if (!main) return
    const sync = () => {
      const open = document.querySelector('.modal-overlay') != null
      main.style.overflow = open ? 'hidden' : ''
      document.body.style.overflow = open ? 'hidden' : ''
    }
    const obs = new MutationObserver(sync)
    obs.observe(document.body, { childList: true, subtree: true })
    sync()
    return () => {
      obs.disconnect()
      main.style.overflow = ''
      document.body.style.overflow = ''
    }
  }, [])

  return (
    <div className="min-h-dvh flex flex-col md:flex-row" style={{ background: "var(--bg)" }}>
      <Navbar />
      <main
        ref={mainRef}
        className="flex-1 min-w-0 overflow-y-auto"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
      <BrowserRouter>
        <AuthProvider>
        <Routes>
          {/* Autenticación — pantalla completa, sin navbar (públicas) */}
          <Route path="/login"     element={<Login />} />
          <Route path="/recuperar" element={<Recuperar />} />
          <Route path="/registro"  element={<Registro />} />

          {/* Panel — protegido: sin sesión redirige a /login */}
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route path="/"          element={<Dashboard />} />
              <Route path="/cartera"      element={<Cartera />} />
              <Route path="/deudores" element={<Deudores />}>
                <Route index element={<DeudoresPrestamos />} />
                <Route path="cheques-fiados" element={<Fiados />} />
              </Route>
              <Route path="/pasivos"      element={<Pasivos />} />
              <Route path="/reportes"     element={<Reportes />} />
              <Route path="/movimientos" element={<Movimientos />} />
              {/* Solo admin */}
              <Route element={<ProtectedRoute adminOnly />}>
                <Route path="/configuracion" element={<Configuracion />} />
                <Route path="/usuarios"     element={<Usuarios />} />
              </Route>
            </Route>
          </Route>
        </Routes>
        </AuthProvider>
      </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
