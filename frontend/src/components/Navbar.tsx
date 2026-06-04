import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getDolarBlue } from '../api/dolar'

interface NavbarProps {
  dark: boolean
  onToggle: () => void
}

function SunIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
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

export default function Navbar({ dark, onToggle }: NavbarProps) {
  const { data: dolar } = useQuery({
    queryKey: ['dolar-blue'],
    queryFn: getDolarBlue,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 3 * 60 * 1000,
  })

  return (
    <nav className="bg-slate-900 text-white shadow-md">
      {/* Fila 1: logo + links + toggle */}
      <div className="flex items-center px-4 h-12 gap-3">
        <span className="font-bold text-base tracking-tight shrink-0">Daily FC</span>

        <div className="flex gap-1 flex-1">
          {(['/', '/deudores', '/reportes'] as const).map((to, i) => {
            const labels = ['Cartera', 'Deudores', 'Reportes']
            return (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-slate-700 text-white'
                      : 'text-slate-300 hover:text-white hover:bg-slate-800'
                  }`
                }
              >
                {labels[i]}
              </NavLink>
            )
          })}
        </div>

        <button
          onClick={onToggle}
          className="shrink-0 p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
          aria-label={dark ? 'Activar modo claro' : 'Activar modo oscuro'}
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>

      {/* Fila 2: barra del dólar blue */}
      <div className="border-t border-slate-800 bg-slate-800/60 px-4 py-2.5">
        {dolar ? (
          <div className="flex items-center justify-center gap-6 sm:gap-10">
            <span className="text-slate-500 text-xs uppercase tracking-widest hidden sm:block">
              Dólar Blue
            </span>
            <div className="flex items-center gap-6 sm:gap-10">
              <div className="text-center">
                <p className="text-slate-500 text-[10px] uppercase tracking-wider mb-0.5">Compra</p>
                <p className="text-green-400 font-mono font-bold text-xl sm:text-2xl leading-none">
                  ${dolar.compra.toLocaleString('es-AR')}
                </p>
              </div>
              <div className="w-px h-8 bg-slate-700" />
              <div className="text-center">
                <p className="text-slate-500 text-[10px] uppercase tracking-wider mb-0.5">Venta</p>
                <p className="text-red-400 font-mono font-bold text-xl sm:text-2xl leading-none">
                  ${dolar.venta.toLocaleString('es-AR')}
                </p>
              </div>
              <div className="hidden sm:block text-center">
                <p className="text-slate-500 text-[10px] uppercase tracking-wider mb-0.5">Spread</p>
                <p className="text-slate-300 font-mono font-semibold text-xl leading-none">
                  ${(dolar.venta - dolar.compra).toLocaleString('es-AR')}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-center text-slate-600 text-xs py-1">Cargando cotización…</p>
        )}
      </div>
    </nav>
  )
}
