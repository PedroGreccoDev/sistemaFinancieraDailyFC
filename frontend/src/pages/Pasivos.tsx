import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPasivos, cancelarPasivo } from '../api/pasivos'
import { fmtARS, fmtUSD, fmtDate } from '../lib/fmt'
import type { Pasivo, PasivoEstado } from '../types'

type Filtro = 'todos' | PasivoEstado

function EstadoBadge({ estado }: { estado: PasivoEstado }) {
  return estado === 'PENDIENTE' ? (
    <span className="inline-flex items-center text-xs font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 rounded-full px-2 py-0.5">
      Pendiente
    </span>
  ) : (
    <span className="inline-flex items-center text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400 rounded-full px-2 py-0.5">
      Cancelada
    </span>
  )
}

function fmtMonto(pasivo: Pasivo): string {
  return pasivo.moneda === 'USD' ? fmtUSD(pasivo.monto) : fmtARS(pasivo.monto)
}

export default function Pasivos() {
  const [filtro, setFiltro] = useState<Filtro>('PENDIENTE')
  const [cancelando, setCancelando] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const estado = filtro === 'todos' ? undefined : filtro as PasivoEstado
  const { data: pasivos, isLoading, error, refetch } = useQuery({
    queryKey: ['pasivos', filtro],
    queryFn: () => getPasivos(estado),
    refetchInterval: 30_000,
  })

  const pendientes = pasivos?.filter((p) => p.estado === 'PENDIENTE') ?? []
  const totalARS = pendientes
    .filter((p) => p.moneda === 'ARS')
    .reduce((acc, p) => acc + parseFloat(p.monto), 0)
  const totalUSD = pendientes
    .filter((p) => p.moneda === 'USD')
    .reduce((acc, p) => acc + parseFloat(p.monto), 0)

  async function handleCancelar(id: string) {
    if (!confirm('¿Confirmar cancelación del pasivo?')) return
    setCancelando(id)
    try {
      await cancelarPasivo(id)
      queryClient.invalidateQueries({ queryKey: ['pasivos'] })
    } finally {
      setCancelando(null)
    }
  }

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Pasivos</h1>
          <p className="text-sm text-slate-500 mt-0.5">Deudas del negocio con clientes y proveedores</p>
        </div>
        <button
          onClick={() => refetch()}
          className="text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 border border-slate-200 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          Actualizar
        </button>
      </div>

      {/* KPIs */}
      {filtro !== 'CANCELADA' && (
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Pendiente ARS</p>
            <p className="text-xl sm:text-2xl font-bold text-red-500 dark:text-red-400 leading-none">
              {fmtARS(totalARS)}
            </p>
            <p className="text-xs text-slate-400 mt-1">{pendientes.filter((p) => p.moneda === 'ARS').length} pasivo(s)</p>
          </div>
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Pendiente USD</p>
            <p className="text-xl sm:text-2xl font-bold text-red-500 dark:text-red-400 leading-none">
              {fmtUSD(totalUSD)}
            </p>
            <p className="text-xs text-slate-400 mt-1">{pendientes.filter((p) => p.moneda === 'USD').length} pasivo(s)</p>
          </div>
        </div>
      )}

      {/* Filtros */}
      <div className="flex gap-2 mb-4">
        {(['PENDIENTE', 'todos', 'CANCELADA'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFiltro(f as Filtro)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors capitalize ${
              filtro === f
                ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-900'
                : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
            }`}
          >
            {f === 'PENDIENTE' ? 'Pendientes' : f === 'todos' ? 'Todos' : 'Cancelados'}
          </button>
        ))}
      </div>

      {/* Lista */}
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
        {isLoading && (
          <div className="p-12 text-center text-slate-400">Cargando pasivos…</div>
        )}
        {error && (
          <div className="p-12 text-center text-red-500">Error al cargar los pasivos.</div>
        )}
        {pasivos && pasivos.length === 0 && (
          <div className="p-12 text-center text-slate-400">
            <p className="text-4xl mb-3">✅</p>
            <p className="font-medium">Sin pasivos registrados</p>
          </div>
        )}
        {pasivos && pasivos.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[580px]">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-700/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Acreedor</th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Concepto</th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Monto</th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Vencimiento</th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Estado</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {pasivos.map((pasivo) => (
                  <tr
                    key={pasivo.id}
                    className="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">
                      {pasivo.acreedor}
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400 max-w-[200px] truncate">
                      {pasivo.concepto}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-red-600 dark:text-red-400">
                      {fmtMonto(pasivo)}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 text-xs whitespace-nowrap">
                      {pasivo.fecha_vencimiento ? fmtDate(pasivo.fecha_vencimiento) : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <EstadoBadge estado={pasivo.estado} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      {pasivo.estado === 'PENDIENTE' && (
                        <button
                          onClick={() => handleCancelar(pasivo.id)}
                          disabled={cancelando === pasivo.id}
                          className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-200 font-medium disabled:opacity-50 transition-colors"
                        >
                          {cancelando === pasivo.id ? 'Cancelando…' : 'Cancelar'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
