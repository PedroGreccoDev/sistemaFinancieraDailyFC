import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Navbar from './components/Navbar'
import DolarWidget from './components/DolarWidget'
import Dashboard from './pages/Dashboard'
import Cartera from './pages/Cartera'
import Deudores from './pages/Deudores'
import DeudoresPrestamos from './pages/DeudoresPrestamos'
import Pasivos from './pages/Pasivos'
import Reportes from './pages/Reportes'
import Fiados from './pages/Fiados'
import Movimientos from './pages/Movimientos'
import Gastos from './pages/Gastos'
import { useDarkMode } from './hooks/useDarkMode'
import { ToastProvider } from './lib/toast'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 15_000,
    },
  },
})

function SunIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

export default function App() {
  const [dark, toggleDark] = useDarkMode()

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
      <BrowserRouter>
        <div className="min-h-dvh flex flex-col md:flex-row" style={{ background: "var(--bg)" }}>
          <Navbar />
          <main className="flex-1 min-w-0 overflow-y-auto pb-40 md:pb-0">
            <Routes>
              <Route path="/"          element={<Dashboard />} />
              <Route path="/cartera"      element={<Cartera />} />
              <Route path="/deudores" element={<Deudores />}>
                <Route index element={<DeudoresPrestamos />} />
                <Route path="cheques-fiados" element={<Fiados />} />
              </Route>
              <Route path="/pasivos"      element={<Pasivos />} />
              <Route path="/reportes"     element={<Reportes />} />
              <Route path="/gastos"       element={<Gastos />} />
              <Route path="/movimientos" element={<Movimientos />} />
            </Routes>
          </main>
        </div>

        <DolarWidget />

        <button
          onClick={toggleDark}
          aria-label={dark ? 'Activar modo claro' : 'Activar modo oscuro'}
          className="fixed left-3 z-50 w-9 h-9 flex items-center justify-center rounded-full shadow-sm border border-slate-300/70 bg-white/80 text-slate-500 hover:bg-white hover:text-slate-900 dark:border-white/10 dark:bg-slate-700/50 dark:text-slate-300 dark:hover:bg-slate-600 dark:hover:text-white transition-all"
          style={{ bottom: 'calc(0.75rem + env(safe-area-inset-bottom))' }}
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </button>
      </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
