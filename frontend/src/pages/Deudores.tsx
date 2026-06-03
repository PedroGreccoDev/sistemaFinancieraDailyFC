import { useQuery } from '@tanstack/react-query'
import { getPrestamos } from '../api/prestamos'
import { getClientes } from '../api/clientes'
import { fmtMonto, fmtDate, daysUntil } from '../lib/fmt'
import type { Prestamo, Cuota } from '../types'

type Semaforo = 'mora' | 'proximo' | 'ok' | 'cancelado'

function getSemaforo(prestamo: Prestamo): Semaforo {
  if (prestamo.estado !== 'activo') return 'cancelado'
  const pendientes = prestamo.cuotas_detalle.filter((c) => c.estado === 'PENDIENTE')
  if (pendientes.length === 0) return 'cancelado'
  const enMora = pendientes.some((c) => daysUntil(c.fecha_vencimiento) < 0)
  if (enMora) return 'mora'
  const proxima = pendientes.sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))[0]
  if (proxima && daysUntil(proxima.fecha_vencimiento) <= 7) return 'proximo'
  return 'ok'
}

function proximaCuota(prestamo: Prestamo): Cuota | null {
  return (
    prestamo.cuotas_detalle
      .filter((c) => c.estado === 'PENDIENTE')
      .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))[0] ?? null
  )
}

const semaforoStyle: Record<Semaforo, { border: string; badge: string; label: string }> = {
  mora: { border: 'border-red-400', badge: 'bg-red-100 text-red-700', label: 'En mora' },
  proximo: { border: 'border-yellow-400', badge: 'bg-yellow-100 text-yellow-700', label: 'Vence pronto' },
  ok: { border: 'border-green-400', badge: 'bg-green-100 text-green-700', label: 'Al día' },
  cancelado: { border: 'border-slate-200', badge: 'bg-slate-100 text-slate-500', label: 'Cancelado' },
}

export default function Deudores() {
  const { data: prestamos, isLoading: loadingP, error: errP } = useQuery({
    queryKey: ['prestamos'],
    queryFn: () => getPrestamos(),
    refetchInterval: 30_000,
  })

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: getClientes,
    staleTime: 60_000,
  })

  const clienteMap = new Map(clientes?.map((c) => [c.id, c.nombre]) ?? [])

  const activos = (prestamos ?? [])
    .filter((p) => p.estado === 'activo')
    .sort((a, b) => {
      const sa = getSemaforo(a)
      const sb = getSemaforo(b)
      const order: Record<Semaforo, number> = { mora: 0, proximo: 1, ok: 2, cancelado: 3 }
      return order[sa] - order[sb]
    })

  const cancelados = (prestamos ?? []).filter((p) => p.estado !== 'activo')

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Deudores</h1>
          <p className="text-sm text-slate-500 mt-0.5">Semáforo de cuotas activas</p>
        </div>
        <div className="flex gap-3 text-xs text-slate-600">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-red-400 inline-block" />En mora</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-yellow-400 inline-block" />Vence en 7 días</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-green-400 inline-block" />Al día</span>
        </div>
      </div>

      {(loadingP) && <div className="text-center text-slate-400 py-12">Cargando deudores…</div>}
      {errP && <div className="text-center text-red-500 py-12">Error al cargar préstamos.</div>}

      {activos.length === 0 && !loadingP && (
        <div className="text-center text-slate-400 py-12">
          <p className="text-4xl mb-3">🎉</p>
          <p className="font-medium">No hay préstamos activos</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        {activos.map((p) => {
          const sem = getSemaforo(p)
          const style = semaforoStyle[sem]
          const proxima = proximaCuota(p)
          const cobradas = p.cuotas_detalle.filter((c) => c.estado === 'COBRADA').length
          const nombre = clienteMap.get(p.cliente_id) ?? '…'

          return (
            <div key={p.id} className={`bg-white border-2 ${style.border} rounded-lg p-4 shadow-sm`}>
              <div className="flex items-start justify-between mb-2">
                <h3 className="font-semibold text-slate-900 truncate">{nombre}</h3>
                <span className={`text-xs font-medium rounded-full px-2 py-0.5 shrink-0 ml-2 ${style.badge}`}>
                  {style.label}
                </span>
              </div>

              <div className="text-sm text-slate-600 space-y-1 mb-3">
                <div className="flex justify-between">
                  <span>Capital</span>
                  <span className="font-medium text-slate-800">{fmtMonto(p.credito, p.moneda)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Total a cobrar</span>
                  <span className="font-medium text-slate-800">{fmtMonto(p.total_a_cobrar, p.moneda)}</span>
                </div>
                {proxima && (
                  <div className="flex justify-between">
                    <span>Próxima cuota</span>
                    <span className="font-medium text-slate-800">
                      {fmtDate(proxima.fecha_vencimiento)} · {fmtMonto(proxima.monto, p.moneda)}
                    </span>
                  </div>
                )}
              </div>

              {/* Barra de progreso */}
              <div>
                <div className="flex justify-between text-xs text-slate-500 mb-1">
                  <span>{cobradas} de {p.cuotas} cuotas cobradas</span>
                  <span>{p.frecuencia}</span>
                </div>
                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full transition-all"
                    style={{ width: `${(cobradas / p.cuotas) * 100}%` }}
                  />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {cancelados.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-sm text-slate-500 hover:text-slate-700 select-none list-none flex items-center gap-2">
            <span className="group-open:rotate-90 transition-transform inline-block">▶</span>
            Ver {cancelados.length} préstamo(s) cancelado(s)
          </summary>
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {cancelados.map((p) => {
              const nombre = clienteMap.get(p.cliente_id) ?? '…'
              return (
                <div key={p.id} className="bg-slate-50 border border-slate-200 rounded-lg p-4 opacity-60">
                  <div className="flex justify-between items-center">
                    <span className="font-medium text-slate-700">{nombre}</span>
                    <span className="text-xs bg-slate-200 text-slate-500 rounded-full px-2 py-0.5 capitalize">{p.estado}</span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1">{fmtMonto(p.credito, p.moneda)} · {p.cuotas} cuotas</p>
                </div>
              )
            })}
          </div>
        </details>
      )}
    </div>
  )
}
