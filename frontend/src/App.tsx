import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Cartera from './pages/Cartera'
import Deudores from './pages/Deudores'
import Reportes from './pages/Reportes'
import { useDarkMode } from './hooks/useDarkMode'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 15_000,
    },
  },
})

export default function App() {
  const [dark, toggleDark] = useDarkMode()

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-dvh bg-slate-50 dark:bg-slate-900 flex flex-col transition-colors duration-200 pb-safe">
          <Navbar dark={dark} onToggle={toggleDark} />
          <main className="flex-1">
            <Routes>
              <Route path="/"          element={<Dashboard />} />
              <Route path="/cartera"   element={<Cartera />} />
              <Route path="/deudores"  element={<Deudores />} />
              <Route path="/reportes"  element={<Reportes />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
