import { useQuery } from '@tanstack/react-query'
import { getChequeCartera } from '../api/cheques'
import { fmtARS, fmtDate, daysUntil } from '../lib/fmt'
import type { Cheque } from '../types'

function diasBadge(dias: number | null) {
  if (dias === null) return <span className="text-slate-400 text-xs">Sin fecha</span>
  if (dias < 0)
    return <span className="inline-flex items-center gap-1 text-xs font-medium bg-red-100 text-red-700 rounded-full px-2 py-0.5">Vencido hace {Math.abs(dias)}d</span>
  if (dias === 0)
    return <span className="inline-flex items-center gap-1 text-xs font-medium bg-orange-100 text-orange-700 rounded-full px-2 py-0.5">Hoy</span>
  if (dias <= 7)
    return <span className="inline-flex items-center gap-1 text-xs font-medium bg-orange-100 text-orange-700 rounded-full px-2 py-0.5">{dias}d</span>
  if (dias <= 30)
    return <span className="inline-flex items-center gap-1 text-xs font-medium bg-yellow-100 text-yellow-700 rounded-full px-2 py-0.5">{dias}d</span>
  return <span className="inline-flex items-center gap-1 text-xs font-medium bg-green-100 text-green-700 rounded-full px-2 py-0.5">{dias}d</span>
}

function totalCartera(cheques: Cheque[]): number {
  return cheques.reduce((acc, c) => acc + parseFloat(c.monto), 0)
}

export default function Cartera() {
  const { data: cheques, isLoading, error, refetch } = useQuery({
    queryKey: ['cartera'],
    queryFn: getChequeCartera,
    refetchInterval: 30_000,
  })

  const sorted = cheques
    ? [...cheques].sort((a, b) => {
        if (!a.fecha_pago && !b.fecha_pago) return 0
        if (!a.fecha_pago) return 1
        if (!b.fecha_pago) return -1
        return a.fecha_pago.localeCompare(b.fecha_pago)
      })
    : []

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Cartera</h1>
          <p className="text-sm text-slate-500 mt-0.5">Cheques en stock — inventario activo</p>
        </div>
        <button
          onClick={() => refetch()}
          className="text-sm text-slate-600 hover:text-slate-900 border border-slate-200 rounded px-3 py-1.5 hover:bg-slate-50 transition-colors"
        >
          Actualizar
        </button>
      </div>

      {/* Resumen */}
      {cheques && (
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div className="bg-white border border-slate-200 rounded-lg p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Cheques en cartera</p>
            <p className="text-3xl font-bold text-slate-900 mt-1">{cheques.length}</p>
          </div>
          <div className="bg-white border border-slate-200 rounded-lg p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium">Total en cartera</p>
            <p className="text-3xl font-bold text-slate-900 mt-1">{fmtARS(totalCartera(cheques))}</p>
          </div>
        </div>
      )}

      {/* Tabla */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        {isLoading && (
          <div className="p-12 text-center text-slate-400">Cargando cartera…</div>
        )}
        {error && (
          <div className="p-12 text-center text-red-500">
            Error al cargar la cartera. ¿Está corriendo el backend?
          </div>
        )}
        {cheques && cheques.length === 0 && (
          <div className="p-12 text-center text-slate-400">
            <p className="text-4xl mb-3">📭</p>
            <p className="font-medium">La cartera está vacía</p>
          </div>
        )}
        {sorted.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="text-left px-4 py-3 font-medium text-slate-600">Nº Cheque</th>
                <th className="text-right px-4 py-3 font-medium text-slate-600">Monto</th>
                <th className="text-right px-4 py-3 font-medium text-slate-600">Compra %</th>
                <th className="text-center px-4 py-3 font-medium text-slate-600">Fecha pago</th>
                <th className="text-center px-4 py-3 font-medium text-slate-600">Vence en</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600">Ingresado</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((cheque) => {
                const dias = cheque.fecha_pago ? daysUntil(cheque.fecha_pago) : null
                return (
                  <tr key={cheque.nro_cheque} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-mono font-medium text-slate-800">{cheque.nro_cheque}</td>
                    <td className="px-4 py-3 text-right font-semibold text-slate-900">{fmtARS(cheque.monto)}</td>
                    <td className="px-4 py-3 text-right text-slate-600">{parseFloat(cheque.porcentaje_compra).toFixed(2)}%</td>
                    <td className="px-4 py-3 text-center text-slate-600">{fmtDate(cheque.fecha_pago)}</td>
                    <td className="px-4 py-3 text-center">{diasBadge(dias)}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{fmtDate(cheque.created_at.slice(0, 10))}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
