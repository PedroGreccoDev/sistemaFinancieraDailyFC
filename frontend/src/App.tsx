import { useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
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
import { ToastProvider } from './lib/toast'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 15_000,
    },
  },
})

export default function App() {
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
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
      <BrowserRouter>
        <div className="min-h-dvh flex flex-col md:flex-row" style={{ background: "var(--bg)" }}>
          <Navbar />
          <main ref={mainRef} className="flex-1 min-w-0 overflow-y-auto pb-40 md:pb-0">
            <Routes>
              <Route path="/"          element={<Dashboard />} />
              <Route path="/cartera"      element={<Cartera />} />
              <Route path="/deudores" element={<Deudores />}>
                <Route index element={<DeudoresPrestamos />} />
                <Route path="cheques-fiados" element={<Fiados />} />
              </Route>
              <Route path="/pasivos"      element={<Pasivos />} />
              <Route path="/reportes"     element={<Reportes />} />
              <Route path="/movimientos" element={<Movimientos />} />
              <Route path="/configuracion" element={<Configuracion />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
