import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getReporteGanancias } from '../api/reportes'
import { fmtARS, fmtUSD, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'

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

function MetricCard({
  label,
  value,
  sub,
  color = 'default',
}: {
  label: string
  value: string
  sub?: string
  color?: 'default' | 'green' | 'red' | 'indigo'
}) {
  const valueClass = {
    default: 'text-slate-900 dark:text-slate-100',
    green: 'text-green-600 dark:text-green-400',
    red: 'text-red-500 dark:text-red-400',
    indigo: 'text-indigo-600 dark:text-indigo-400',
  }[color]

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-5">
      <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${valueClass}`}>{value}</p>
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
          {/* Ganancias por módulo */}
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-3">Ganancias del período</h2>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 mb-4">
            <MetricCard
              label="Cheques (spread)"
              value={fmtARS(data.ganancia_cheques)}
              sub="Compra-venta de cheques"
              color="green"
            />
            <MetricCard
              label="Préstamos (intereses)"
              value={fmtARS(data.ganancia_prestamos)}
              sub="Diferencia crédito / total"
              color="green"
            />
            <MetricCard
              label="Divisas (efectivo)"
              value={fmtARS(data.ganancia_movimientos_efectivo)}
              sub="Compra-venta de dólares"
              color="green"
            />
            <MetricCard
              label="Gastos operativos"
              value={fmtARS(data.gastos_operativos)}
              sub="Nafta, insumos, etc."
              color="red"
            />
          </div>

          {/* Totales */}
          <div className="grid grid-cols-2 gap-3 sm:gap-4 mb-6">
            <div className="bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-5">
              <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Total ganancias brutas</p>
              <p className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100 mt-1">
                {fmtARS(data.total_ganancias)}
              </p>
              <p className="text-xs text-slate-400 mt-1">Sin descontar gastos</p>
            </div>
            <div className="bg-indigo-600 text-white rounded-lg p-5">
              <p className="text-xs text-indigo-200 uppercase tracking-wide font-medium">Neto del período</p>
              <p className="text-2xl sm:text-3xl font-bold mt-1">{fmtARS(data.neto)}</p>
              <p className="text-xs text-indigo-300 mt-1">Ganancias − gastos</p>
            </div>
          </div>

          {/* Tabla desglose */}
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden mb-6">
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[320px]">
                <thead>
                  <tr className="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700">
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Módulo</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Importe</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">% del bruto</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: 'Cheques', value: data.ganancia_cheques, egreso: false },
                    { label: 'Préstamos', value: data.ganancia_prestamos, egreso: false },
                    { label: 'Divisas', value: data.ganancia_movimientos_efectivo, egreso: false },
                    { label: 'Gastos operativos', value: data.gastos_operativos, egreso: true },
                  ].map((row) => {
                    const pct = parseFloat(data.total_ganancias) > 0
                      ? ((parseFloat(row.value) / parseFloat(data.total_ganancias)) * 100).toFixed(1)
                      : '0.0'
                    return (
                      <tr key={row.label} className="border-b border-slate-100 dark:border-slate-700/50">
                        <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{row.label}</td>
                        <td className={`px-4 py-3 text-right font-semibold ${row.egreso ? 'text-red-500 dark:text-red-400' : 'text-slate-900 dark:text-slate-100'}`}>
                          {row.egreso ? '−' : ''}{fmtARS(row.value)}
                        </td>
                        <td className="px-4 py-3 text-right text-slate-500">{row.egreso ? '−' : ''}{pct}%</td>
                      </tr>
                    )
                  })}
                  <tr className="bg-slate-50 dark:bg-slate-700/50 font-semibold">
                    <td className="px-4 py-3 text-slate-900 dark:text-slate-100">Neto</td>
                    <td className="px-4 py-3 text-right text-indigo-700 dark:text-indigo-400">{fmtARS(data.neto)}</td>
                    <td className="px-4 py-3 text-right text-slate-500">—</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Saldo Pasivos */}
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-3">Pasivos pendientes (snapshot actual)</h2>
          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-5">
              <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Deudas pendientes ARS</p>
              <p className="text-2xl font-bold text-red-500 dark:text-red-400 mt-1">
                {fmtARS(data.saldo_pasivos.pendiente_ars)}
              </p>
              <p className="text-xs text-slate-400 mt-1">Lo que el negocio debe (en $)</p>
            </div>
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-5">
              <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Deudas pendientes USD</p>
              <p className="text-2xl font-bold text-red-500 dark:text-red-400 mt-1">
                {fmtUSD(data.saldo_pasivos.pendiente_usd)}
              </p>
              <p className="text-xs text-slate-400 mt-1">Lo que el negocio debe (en U$D)</p>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
