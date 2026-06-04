import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getDolarBlue } from '../api/dolar'

export default function Navbar() {
  const { data: dolar } = useQuery({
    queryKey: ['dolar-blue'],
    queryFn: getDolarBlue,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 3 * 60 * 1000,
  })

  return (
    <nav className="bg-slate-900 text-white shadow-md">
      {/* Fila principal */}
      <div className="flex items-center px-4 h-12 gap-4">
        <span className="font-bold text-base tracking-tight text-white shrink-0">
          Daily FC
        </span>

        <div className="flex gap-1 flex-1">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                isActive ? 'bg-slate-700 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-800'
              }`
            }
          >
            Cartera
          </NavLink>
          <NavLink
            to="/deudores"
            className={({ isActive }) =>
              `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                isActive ? 'bg-slate-700 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-800'
              }`
            }
          >
            Deudores
          </NavLink>
          <NavLink
            to="/reportes"
            className={({ isActive }) =>
              `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                isActive ? 'bg-slate-700 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-800'
              }`
            }
          >
            Reportes
          </NavLink>
        </div>

        {/* Dólar: compacto en mobile, expandido en desktop */}
        {dolar ? (
          <>
            {/* Mobile: solo el spread en una línea */}
            <div className="sm:hidden shrink-0 text-xs font-mono bg-slate-800 rounded px-2 py-1">
              <span className="text-green-400">${dolar.compra.toLocaleString('es-AR')}</span>
              <span className="text-slate-500 mx-1">/</span>
              <span className="text-red-400">${dolar.venta.toLocaleString('es-AR')}</span>
            </div>
            {/* Desktop: versión completa */}
            <div className="hidden sm:flex items-center gap-3 bg-slate-800 rounded px-3 py-1.5 shrink-0 text-sm">
              <span className="text-slate-400 text-xs">Dólar Blue</span>
              <span className="text-green-400 font-mono font-semibold">
                C ${dolar.compra.toLocaleString('es-AR')}
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-red-400 font-mono font-semibold">
                V ${dolar.venta.toLocaleString('es-AR')}
              </span>
            </div>
          </>
        ) : (
          <div className="shrink-0 bg-slate-800 rounded px-2 py-1 text-slate-500 text-xs">…</div>
        )}
      </div>
    </nav>
  )
}
