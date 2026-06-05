import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getDolarBlue } from '../api/dolar'


const NAV_LINKS = [
  { to: '/',          label: 'Inicio',   end: true  },
  { to: '/cartera',   label: 'Cartera',  end: false },
  { to: '/deudores',  label: 'Deudores', end: false },
  { to: '/reportes',    label: 'Reportes',    end: false },
  { to: '/movimientos', label: 'Movimientos', end: false },
]

export default function Navbar() {
  const { data: dolar } = useQuery({
    queryKey: ['dolar-blue'],
    queryFn: getDolarBlue,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 3 * 60 * 1000,
  })

  const horaActualizacion = dolar?.fechaActualizacion
    ? new Date(dolar.fechaActualizacion).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <nav className="bg-slate-900 text-white shadow-md pt-safe">
      {/* Fila 1: logo + links + toggle */}
      <div className="flex items-center px-4 h-12 gap-3">
        <span className="font-bold text-base tracking-tight shrink-0">Daily FC</span>

        <div className="flex gap-0.5 flex-1 overflow-x-auto scrollbar-none">
          {NAV_LINKS.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `px-2.5 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap ${
                  isActive
                    ? 'bg-slate-700 text-white'
                    : 'text-slate-300 hover:text-white hover:bg-slate-800'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </div>

      </div>

      {/* Fila 2: barra del dólar blue */}
      <div className="border-t border-slate-800 bg-slate-800/60 px-4 py-2">
        {dolar ? (
          <div className="flex flex-col items-center gap-1">
            <div className="flex items-center gap-5 sm:gap-10">
              <div className="text-center">
                <p className="text-slate-500 text-[10px] uppercase tracking-wider mb-0.5">Compra</p>
                <p className="text-red-400 font-mono font-bold text-xl sm:text-2xl leading-none">
                  ${dolar.compra.toLocaleString('es-AR')}
                </p>
              </div>
              <div className="w-px h-8 bg-slate-700" />
              <div className="text-center">
                <p className="text-slate-500 text-[10px] uppercase tracking-wider mb-0.5">Venta</p>
                <p className="text-green-400 font-mono font-bold text-xl sm:text-2xl leading-none">
                  ${dolar.venta.toLocaleString('es-AR')}
                </p>
              </div>
              <div className="hidden sm:block w-px h-8 bg-slate-700" />
              <div className="hidden sm:block text-center">
                <p className="text-slate-500 text-[10px] uppercase tracking-wider mb-0.5">Spread</p>
                <p className="text-slate-300 font-mono font-semibold text-xl leading-none">
                  ${(dolar.venta - dolar.compra).toLocaleString('es-AR')}
                </p>
              </div>
            </div>
            <p className="text-slate-600 text-[10px]">
              Dólar Blue · Fuente: El Cronista
              {horaActualizacion && <span> · Actualizado {horaActualizacion}</span>}
            </p>
          </div>
        ) : (
          <p className="text-center text-slate-600 text-xs py-1">Cargando cotización…</p>
        )}
      </div>
    </nav>
  )
}
