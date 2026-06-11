import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getChequeCartera, getCheques } from '../api/cheques'
import { fmtARS, fmtDate, daysUntil, todayISO, weekStartISO, monthStartISO, yearStartISO } from '../lib/fmt'
import type { Cheque } from '../types'
import DropdownFilter from '../components/DropdownFilter'
import DateRangePicker from '../components/DateRangePicker'

type FilterPreset = 'hoy' | 'semana' | 'mes' | 'anio' | 'custom'

function presetRange(preset: FilterPreset, desde: string | null, hasta: string | null): [string, string] {
  const hoy = todayISO()
  if (preset === 'hoy')    return [hoy, hoy]
  if (preset === 'semana') return [weekStartISO(), hoy]
  if (preset === 'mes')    return [monthStartISO(), hoy]
  if (preset === 'anio')   return [yearStartISO(), hoy]
  return [desde ?? hoy, hasta ?? hoy]
}

function filterByRange(cheques: Cheque[], start: string, end: string): Cheque[] {
  return cheques.filter(c => {
    if (!c.ultimo_evento_manual_at) return false
    const fecha = c.ultimo_evento_manual_at.slice(0, 10)
    return fecha >= start && fecha <= end
  })
}

function diasBadge(dias: number | null) {
  if (dias === null) return <span className="text-slate-400 text-xs">Sin fecha</span>
  if (dias < 0)
    return <span className="inline-flex items-center text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 rounded-full px-2 py-0.5">Vencido {Math.abs(dias)}d</span>
  if (dias === 0)
    return <span className="inline-flex items-center text-xs font-medium bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400 rounded-full px-2 py-0.5">Hoy</span>
  if (dias <= 7)
    return <span className="inline-flex items-center text-xs font-medium bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400 rounded-full px-2 py-0.5">{dias}d</span>
  if (dias <= 30)
    return <span className="inline-flex items-center text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400 rounded-full px-2 py-0.5">{dias}d</span>
  return <span className="inline-flex items-center text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400 rounded-full px-2 py-0.5">{dias}d</span>
}

function totalCartera(cheques: Cheque[]): number {
  return cheques.reduce((acc, c) => acc + parseFloat(c.monto), 0)
}

export default function Cartera() {
  const [preset, setPreset] = useState<FilterPreset>('mes')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)

  function handlePreset(p: FilterPreset) {
    setPreset(p)
    if (p !== 'custom') setShowPicker(false)
    else setShowPicker(true)
  }

  const labelPersonalizado =
    customDesde && customHasta
      ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
      : customDesde
      ? `Desde ${fmtDate(customDesde)}`
      : 'Personalizado'

  const { data: cheques, isLoading, error, refetch } = useQuery({
    queryKey: ['cartera'],
    queryFn: getChequeCartera,
    refetchInterval: 30_000,
  })

  const { data: vendidos } = useQuery({
    queryKey: ['cheques-vendidos'],
    queryFn: () => getCheques('VENDIDO'),
    refetchInterval: 60_000,
  })

  const sorted = cheques
    ? [...cheques].sort((a, b) => {
        if (!a.fecha_pago && !b.fecha_pago) return 0
        if (!a.fecha_pago) return 1
        if (!b.fecha_pago) return -1
        return a.fecha_pago.localeCompare(b.fecha_pago)
      })
    : []

  const [rangeStart, rangeEnd] = presetRange(preset, customDesde, customHasta)
  const filteredVendidos = vendidos
    ? [...filterByRange(vendidos, rangeStart, rangeEnd)].sort((a, b) =>
        (b.ultimo_evento_manual_at ?? '').localeCompare(a.ultimo_evento_manual_at ?? '')
      )
    : []
  const totalGanancia = filteredVendidos.reduce((acc, c) => acc + parseFloat(c.ganancia), 0)

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">

      {/* ── Cartera en stock ── */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Cartera</h1>
          <p className="text-sm text-slate-500 mt-0.5">Cheques en stock</p>
        </div>
        <button
          onClick={() => refetch()}
          className="text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 border border-slate-200 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          Actualizar
        </button>
      </div>

      {cheques && (
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 sm:p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">En cartera</p>
            <p className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100 mt-1">{cheques.length}</p>
          </div>
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 sm:p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Total</p>
            <p className="text-lg sm:text-3xl font-bold text-slate-900 dark:text-slate-100 mt-1">{fmtARS(totalCartera(cheques))}</p>
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
        {isLoading && (
          <div className="p-12 text-center text-slate-400">Cargando cartera…</div>
        )}
        {error && (
          <div className="p-12 text-center text-red-500">Error al cargar la cartera.</div>
        )}
        {cheques && cheques.length === 0 && (
          <div className="p-12 text-center text-slate-400">
            <p className="text-4xl mb-3">📭</p>
            <p className="font-medium">La cartera está vacía</p>
          </div>
        )}
        {sorted.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[540px]">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-700/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Nº Cheque</th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Monto</th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400 hidden sm:table-cell">Compra %</th>
                  <th className="text-center px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Fecha pago</th>
                  <th className="text-center px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Vence</th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400 hidden sm:table-cell">Ingresado</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((cheque) => {
                  const dias = cheque.fecha_pago ? daysUntil(cheque.fecha_pago) : null
                  return (
                    <tr key={cheque.nro_cheque} className="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors">
                      <td className="px-4 py-3 font-mono font-medium text-slate-800 dark:text-slate-200 text-xs sm:text-sm">{cheque.nro_cheque}</td>
                      <td className="px-4 py-3 text-right font-semibold text-slate-900 dark:text-slate-100">{fmtARS(cheque.monto)}</td>
                      <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-400 hidden sm:table-cell">{parseFloat(cheque.porcentaje_compra).toFixed(2)}%</td>
                      <td className="px-4 py-3 text-center text-slate-600 dark:text-slate-400">{fmtDate(cheque.fecha_pago)}</td>
                      <td className="px-4 py-3 text-center">{diasBadge(dias)}</td>
                      <td className="px-4 py-3 text-slate-400 dark:text-slate-500 text-xs hidden sm:table-cell">{fmtDate(cheque.created_at.slice(0, 10))}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Historial de ventas ── */}
      <div className="mt-10">
        <div className="mb-5">
          <h2 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Historial de Ventas</h2>
          <p className="text-sm text-slate-500 mt-0.5">Cheques vendidos por período</p>
        </div>

        {/* Filtros de período */}
        <div className="relative flex flex-wrap items-end gap-3 mb-4">
          <DropdownFilter
            label="Período"
            value={preset}
            options={[
              { value: 'hoy' as FilterPreset, label: 'Hoy' },
              { value: 'semana' as FilterPreset, label: 'Esta semana' },
              { value: 'mes' as FilterPreset, label: 'Este mes' },
              { value: 'anio' as FilterPreset, label: 'Este año' },
              { value: 'custom' as FilterPreset, label: labelPersonalizado },
            ]}
            onChange={handlePreset}
          />

          {showPicker && (
            <DateRangePicker
              from={customDesde}
              to={customHasta}
              onChange={(f, t) => { setCustomDesde(f); setCustomHasta(t) }}
              onClose={() => setShowPicker(false)}
            />
          )}
        </div>

        {/* Resumen del período */}
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 sm:p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Cheques vendidos</p>
            <p className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100 mt-1">{filteredVendidos.length}</p>
          </div>
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 sm:p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Ganancia del período</p>
            <p className="text-lg sm:text-2xl font-bold text-emerald-600 dark:text-emerald-400 mt-1">{fmtARS(totalGanancia)}</p>
          </div>
        </div>

        {/* Tabla */}
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          {filteredVendidos.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <p className="text-4xl mb-3">📭</p>
              <p className="font-medium">Sin ventas en el período</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[620px]">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-700/50">
                    <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Nº Cheque</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Monto</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400 hidden sm:table-cell">% Compra</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400 hidden sm:table-cell">% Venta</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Spread</th>
                    <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Ganancia</th>
                    <th className="text-center px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Fecha venta</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredVendidos.map(c => {
                    const spread = c.porcentaje_venta !== null
                      ? (parseFloat(c.porcentaje_compra) - parseFloat(c.porcentaje_venta)).toFixed(2)
                      : null
                    return (
                      <tr key={c.nro_cheque} className="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors">
                        <td className="px-4 py-3 font-mono font-medium text-slate-800 dark:text-slate-200 text-xs sm:text-sm">{c.nro_cheque}</td>
                        <td className="px-4 py-3 text-right font-semibold text-slate-900 dark:text-slate-100">{fmtARS(c.monto)}</td>
                        <td className="px-4 py-3 text-right text-slate-500 hidden sm:table-cell">{parseFloat(c.porcentaje_compra).toFixed(2)}%</td>
                        <td className="px-4 py-3 text-right text-slate-500 hidden sm:table-cell">
                          {c.porcentaje_venta !== null ? `${parseFloat(c.porcentaje_venta).toFixed(2)}%` : '—'}
                        </td>
                        <td className="px-4 py-3 text-right font-medium text-indigo-600 dark:text-indigo-400">
                          {spread !== null ? `${spread}%` : '—'}
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-emerald-600 dark:text-emerald-400">{fmtARS(c.ganancia)}</td>
                        <td className="px-4 py-3 text-center text-slate-500 text-xs">
                          {fmtDate(c.ultimo_evento_manual_at?.slice(0, 10) ?? null)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/50">
                    <td colSpan={5} className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right hidden sm:table-cell">Total</td>
                    <td colSpan={5} className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right sm:hidden">Total</td>
                    <td className="px-4 py-3 text-right font-bold text-emerald-600 dark:text-emerald-400">{fmtARS(totalGanancia)}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
