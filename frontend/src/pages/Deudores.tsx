import { NavLink, Outlet } from 'react-router-dom'

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${
    isActive
      ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
      : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
  }`

export default function Deudores() {
  return (
    <div>
      <div className="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 sm:px-6">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100 pt-4 sm:pt-6 mb-3">Deudores</h1>
          <div className="flex gap-1">
            <NavLink to="/deudores" end className={tabClass}>Préstamos</NavLink>
            <NavLink to="/deudores/cheques-fiados" className={tabClass}>Cheques fiados</NavLink>
          </div>
        </div>
      </div>
      <Outlet />
    </div>
  )
}
