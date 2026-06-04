import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getReporteGanancias } from '../api/reportes'
import { fmtARS, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'

type Preset = 'hoy' | 'semana' | 'mes' | 'custom'

const presets: { key: Preset; label: string }[] = [
  { key: 'hoy', label: 'Hoy' },
  { key: 'semana', label: 'Esta semana' },
  { key: 'mes', label: 'Este mes' },
  { key: 'custom', label: 'Personalizado' },
]

function getRangeForPreset(preset: Preset, customDesde: string, customHasta: string) {
  const hoy = todayISO()
  if (preset === 'hoy') return { desde: hoy, hasta: hoy }
  if (preset === 'semana') return { desde: weekStartISO(), hasta: hoy }
  if (preset === 'mes') return { desde: monthStartISO(), hasta: hoy }
  return { desde: customDesde, hasta: customHasta }
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-5">
      <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">{label}</p>
      <p className="text-2xl font-bold text-slate-900 dark:text-slate-100 mt-1">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
    </div>
  )
}

export default function Reportes() {
  const [preset, setPreset] = useState<Preset>('mes')
  const [customDesde, setCustomDesde] = useState(monthStartISO())
  const [customHasta, setCustomHasta] = useState(todayISO())

  const { desde, hasta } = getRangeForPreset(preset, customDesde, customHasta)

  const { data, isLoading, error } = useQuery({
    queryKey: ['reporte', desde, hasta],
    queryFn: () => getReporteGanancias(desde, hasta),
    enabled: !!desde && !!hasta,
  })

  return (
    <div className="p-4 sm:p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Reportes</h1>
        <p className="text-sm text-slate-500 mt-0.5">Arqueo de caja y ganancias consolidadas</p>
      </div>

      {/* Filtros */}
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 mb-6">
        <div className="flex flex-wrap gap-2 mb-4">
          {presets.map((p) => (
            <button
              key={p.key}
              onClick={() => setPreset(p.key)}
              className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
                preset === p.key
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {preset === 'custom' && (
          <div className="flex flex-col sm:flex-row gap-3 sm:gap-4 sm:items-center">
            <div>
              <label className="block text-xs text-slate-500 mb-1">Desde</label>
              <input
                type="date"
                value={customDesde}
                onChange={(e) => setCustomDesde(e.target.value)}
                className="border border-slate-200 dark:border-slate-600 rounded px-3 py-1.5 text-sm text-slate-800 dark:text-slate-200 bg-white dark:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Hasta</label>
              <input
                type="date"
                value={customHasta}
                onChange={(e) => setCustomHasta(e.target.value)}
                className="border border-slate-200 dark:border-slate-600 rounded px-3 py-1.5 text-sm text-slate-800 dark:text-slate-200 bg-white dark:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>
        )}

        {!isLoading && desde && (
          <p className="text-xs text-slate-400 mt-3">
            Período: {desde.split('-').reverse().join('/')} → {hasta.split('-').reverse().join('/')}
          </p>
        )}
      </div>

      {isLoading && (
        <div className="text-center text-slate-400 py-12">Calculando ganancias…</div>
      )}
      {error && (
        <div className="text-center text-red-500 py-12">Error al cargar el reporte.</div>
      )}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 mb-4">
            <MetricCard
              label="Cheques (spread)"
              value={fmtARS(data.ganancia_cheques)}
              sub="Compra-venta de cheques"
            />
            <MetricCard
              label="Préstamos (intereses)"
              value={fmtARS(data.ganancia_prestamos)}
              sub="Diferencia crédito / total"
            />
            <MetricCard
              label="Divisas (efectivo)"
              value={fmtARS(data.ganancia_movimientos_efectivo)}
              sub="Compra-venta de dólares"
            />
            <div className="bg-indigo-600 text-white rounded-lg p-5">
              <p className="text-xs text-indigo-200 uppercase tracking-wide font-medium">Ganancia total</p>
              <p className="text-2xl sm:text-3xl font-bold mt-1">{fmtARS(data.total)}</p>
              <p className="text-xs text-indigo-300 mt-1">Todos los módulos</p>
            </div>
          </div>

          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[320px]">
                <thead>
                  <tr className="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700">
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Módulo</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Ganancia</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">% del total</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: 'Cheques', value: data.ganancia_cheques },
                    { label: 'Préstamos', value: data.ganancia_prestamos },
                    { label: 'Divisas', value: data.ganancia_movimientos_efectivo },
                  ].map((row) => {
                    const pct = parseFloat(data.total) > 0
                      ? ((parseFloat(row.value) / parseFloat(data.total)) * 100).toFixed(1)
                      : '0.0'
                    return (
                      <tr key={row.label} className="border-b border-slate-100 dark:border-slate-700/50">
                        <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{row.label}</td>
                        <td className="px-4 py-3 text-right font-semibold text-slate-900 dark:text-slate-100">{fmtARS(row.value)}</td>
                        <td className="px-4 py-3 text-right text-slate-500">{pct}%</td>
                      </tr>
                    )
                  })}
                  <tr className="bg-slate-50 dark:bg-slate-700/50 font-semibold">
                    <td className="px-4 py-3 text-slate-900 dark:text-slate-100">Total</td>
                    <td className="px-4 py-3 text-right text-indigo-700 dark:text-indigo-400">{fmtARS(data.total)}</td>
                    <td className="px-4 py-3 text-right text-slate-500">100%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
