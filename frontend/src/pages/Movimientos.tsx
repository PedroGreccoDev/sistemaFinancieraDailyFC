import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getMovimientos } from '../api/movimientos'
import { getGastos } from '../api/gastos_operativos'
import { fmtARS, fmtUSD, fmtDate } from '../lib/fmt'
import type { MovimientoEfectivo, MovimientoTipo } from '../types'

type Seccion = 'divisas' | 'gastos'
type Filtro = 'todos' | MovimientoTipo

function fmtCotizacion(value: string): string {
  return `$${parseFloat(value).toLocaleString('es-AR', { minimumFractionDigits: 2 })}`
}

function fmtMontoMovimiento(mov: MovimientoEfectivo): string {
  return mov.moneda === 'USD' ? fmtUSD(mov.monto) : fmtARS(mov.monto)
}

function TipoBadge({ tipo }: { tipo: MovimientoTipo }) {
  return tipo === 'compra' ? (
    <span className="inline-flex items-center text-xs font-semibold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 rounded-full px-2 py-0.5 capitalize">
      Compra
    </span>
  ) : (
    <span className="inline-flex items-center text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400 rounded-full px-2 py-0.5 capitalize">
      Venta
    </span>
  )
}

function calcularTotales(movs: MovimientoEfectivo[]) {
  let montoCompra = 0, montoVenta = 0, gananciaTotal = 0
  for (const m of movs) {
    const monto = parseFloat(m.monto)
    const ganancia = parseFloat(m.ganancia)
    if (m.tipo === 'compra') montoCompra += monto
    else montoVenta += monto
    gananciaTotal += ganancia
  }
  return { montoCompra, montoVenta, gananciaTotal }
}

export default function Movimientos() {
  const [seccion, setSeccion] = useState<Seccion>('divisas')
  const [filtro, setFiltro] = useState<Filtro>('todos')

  const { data: movimientos, isLoading: loadingMovs, error: errorMovs, refetch: refetchMovs } = useQuery({
    queryKey: ['movimientos'],
    queryFn: getMovimientos,
    refetchInterval: 30_000,
  })

  const { data: gastos, isLoading: loadingGastos, error: errorGastos, refetch: refetchGastos } = useQuery({
    queryKey: ['gastos'],
    queryFn: getGastos,
    refetchInterval: 30_000,
  })

  const todos = movimientos ?? []
  const filtrados = filtro === 'todos' ? todos : todos.filter((m) => m.tipo === filtro)
  const { montoCompra, montoVenta, gananciaTotal } = calcularTotales(todos)

  const totalGastos = (gastos ?? []).reduce((acc, g) => acc + parseFloat(g.monto), 0)

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Movimientos</h1>
          <p className="text-sm text-slate-500 mt-0.5">Divisas y gastos operativos</p>
        </div>
        <button
          onClick={() => { refetchMovs(); refetchGastos() }}
          className="text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 border border-slate-200 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          Actualizar
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-slate-100 dark:bg-slate-800 rounded-lg p-1 w-fit">
        <button
          onClick={() => setSeccion('divisas')}
          className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
            seccion === 'divisas'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
          }`}
        >
          Divisas
        </button>
        <button
          onClick={() => setSeccion('gastos')}
          className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
            seccion === 'gastos'
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
          }`}
        >
          Gastos operativos
        </button>
      </div>

      {/* ── SECCIÓN DIVISAS ── */}
      {seccion === 'divisas' && (
        <>
          {movimientos && (
            <div className="grid grid-cols-3 gap-3 mb-5">
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 sm:p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Compras USD</p>
                <p className="text-lg sm:text-2xl font-bold text-red-500 dark:text-red-400 leading-none">
                  {fmtUSD(montoCompra)}
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  {todos.filter((m) => m.tipo === 'compra').length} operaciones
                </p>
              </div>
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 sm:p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Ventas USD</p>
                <p className="text-lg sm:text-2xl font-bold text-green-600 dark:text-green-400 leading-none">
                  {fmtUSD(montoVenta)}
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  {todos.filter((m) => m.tipo === 'venta').length} operaciones
                </p>
              </div>
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 sm:p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Ganancia total</p>
                <p className="text-lg sm:text-2xl font-bold text-indigo-600 dark:text-indigo-400 leading-none">
                  {fmtARS(gananciaTotal)}
                </p>
                <p className="text-xs text-slate-400 mt-1">{todos.length} operaciones totales</p>
              </div>
            </div>
          )}

          <div className="flex gap-2 mb-4">
            {(['todos', 'compra', 'venta'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFiltro(f)}
                className={`px-3 py-1.5 rounded text-sm font-medium transition-colors capitalize ${
                  filtro === f
                    ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-900'
                    : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
                }`}
              >
                {f === 'todos' ? 'Todos' : f === 'compra' ? 'Compras' : 'Ventas'}
              </button>
            ))}
          </div>

          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
            {loadingMovs && (
              <div className="p-12 text-center text-slate-400">Cargando movimientos…</div>
            )}
            {errorMovs && (
              <div className="p-12 text-center text-red-500">Error al cargar los movimientos.</div>
            )}
            {movimientos && filtrados.length === 0 && (
              <div className="p-12 text-center text-slate-400">
                <p className="text-4xl mb-3">💸</p>
                <p className="font-medium">Sin movimientos registrados</p>
              </div>
            )}
            {filtrados.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[560px]">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-700/50">
                      <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Tipo</th>
                      <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Monto</th>
                      <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Cotización</th>
                      <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Ganancia</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400 hidden sm:table-cell">Observaciones</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Fecha</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtrados.map((mov) => (
                      <tr
                        key={mov.id}
                        className="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors"
                      >
                        <td className="px-4 py-3">
                          <TipoBadge tipo={mov.tipo} />
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-slate-900 dark:text-slate-100">
                          {fmtMontoMovimiento(mov)}
                        </td>
                        <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-400 font-mono">
                          {fmtCotizacion(mov.cotizacion_aplicada)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {parseFloat(mov.ganancia) > 0 ? (
                            <span className="text-green-600 dark:text-green-400 font-medium">
                              {fmtARS(mov.ganancia)}
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-500 dark:text-slate-400 text-xs hidden sm:table-cell max-w-[200px] truncate">
                          {mov.observaciones ?? '—'}
                        </td>
                        <td className="px-4 py-3 text-slate-500 dark:text-slate-400 text-xs whitespace-nowrap">
                          {fmtDate(mov.fecha_operacion.slice(0, 10))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* ── SECCIÓN GASTOS OPERATIVOS ── */}
      {seccion === 'gastos' && (
        <>
          {gastos && (
            <div className="grid grid-cols-2 gap-3 mb-5">
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Total gastos ARS</p>
                <p className="text-xl sm:text-2xl font-bold text-red-500 dark:text-red-400 leading-none">
                  {fmtARS(totalGastos)}
                </p>
                <p className="text-xs text-slate-400 mt-1">{gastos.length} gasto(s) registrados</p>
              </div>
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Origen</p>
                <p className="text-base font-medium text-slate-700 dark:text-slate-300 mt-1">Bot WhatsApp</p>
                <p className="text-xs text-slate-400 mt-1">Los gastos se registran por mensaje</p>
              </div>
            </div>
          )}

          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
            {loadingGastos && (
              <div className="p-12 text-center text-slate-400">Cargando gastos…</div>
            )}
            {errorGastos && (
              <div className="p-12 text-center text-red-500">Error al cargar los gastos.</div>
            )}
            {gastos && gastos.length === 0 && (
              <div className="p-12 text-center text-slate-400">
                <p className="text-4xl mb-3">🧾</p>
                <p className="font-medium">Sin gastos registrados</p>
                <p className="text-xs mt-1">Mandá "cargué 10.000 de nafta" al bot de WhatsApp</p>
              </div>
            )}
            {gastos && gastos.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[400px]">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-700/50">
                      <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Concepto</th>
                      <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Monto</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Fecha</th>
                      <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400 hidden sm:table-cell">Observaciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gastos.map((gasto) => (
                      <tr
                        key={gasto.id}
                        className="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors"
                      >
                        <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100 capitalize">
                          {gasto.concepto}
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-red-600 dark:text-red-400">
                          {gasto.moneda === 'USD' ? fmtUSD(gasto.monto) : fmtARS(gasto.monto)}
                        </td>
                        <td className="px-4 py-3 text-slate-500 dark:text-slate-400 text-xs whitespace-nowrap">
                          {fmtDate(gasto.fecha_operacion)}
                        </td>
                        <td className="px-4 py-3 text-slate-500 dark:text-slate-400 text-xs hidden sm:table-cell max-w-[200px] truncate">
                          {gasto.observaciones ?? '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
