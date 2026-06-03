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
    <nav className="bg-slate-900 text-white h-14 flex items-center px-6 gap-8 shadow-md">
      <span className="font-bold text-lg tracking-tight text-white shrink-0">
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

      <div className="shrink-0 text-sm">
        {dolar ? (
          <div className="flex items-center gap-3 bg-slate-800 rounded px-3 py-1.5">
            <span className="text-slate-400 text-xs">Dólar Blue</span>
            <span className="text-green-400 font-mono font-semibold">
              C ${dolar.compra.toLocaleString('es-AR')}
            </span>
            <span className="text-slate-600">|</span>
            <span className="text-red-400 font-mono font-semibold">
              V ${dolar.venta.toLocaleString('es-AR')}
            </span>
          </div>
        ) : (
          <div className="bg-slate-800 rounded px-3 py-1.5 text-slate-500 text-xs">
            Cargando cotización…
          </div>
        )}
      </div>
    </nav>
  )
}
