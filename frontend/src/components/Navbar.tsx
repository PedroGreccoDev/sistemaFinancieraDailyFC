import { NavLink } from 'react-router-dom'

const NAV_LINKS = [
  { to: '/',             label: 'Inicio',      end: true  },
  { to: '/cartera',      label: 'Cartera',     end: false },
  { to: '/deudores',     label: 'Deudores',    end: false },
  { to: '/pasivos',      label: 'Deudas',      end: false },
  { to: '/reportes',     label: 'Reportes',    end: false },
  { to: '/movimientos',  label: 'Movimientos', end: false },
]

export default function Navbar() {
  return (
    <nav className="bg-white dark:bg-slate-900 text-slate-900 dark:text-white shadow-md pt-safe">
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
                    ? 'bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-white'
                    : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  )
}
