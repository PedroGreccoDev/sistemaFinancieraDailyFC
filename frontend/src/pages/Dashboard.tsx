import { useQuery } from '@tanstack/react-query'
import { getChequeCartera } from '../api/cheques'
import { getPrestamos } from '../api/prestamos'
import { getClientes } from '../api/clientes'
import { getReporteGanancias } from '../api/reportes'
import { fmtARS, fmtMonto, fmtDate, daysUntil, monthStartISO, todayISO } from '../lib/fmt'
import type { Cheque, Prestamo } from '../types'

// ── helpers ──────────────────────────────────────────────────────────

function cuotasVencidas(prestamos: Prestamo[]) {
  return prestamos
    .filter((p) => p.estado === 'activo')
    .flatMap((p) =>
      p.cuotas_detalle
        .filter((c) => c.estado === 'PENDIENTE' && daysUntil(c.fecha_vencimiento) < 0)
        .map((c) => ({ ...c, prestamo_id: p.id, cliente_id: p.cliente_id, moneda: p.moneda }))
    )
    .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))
}

function chequesPorVencer(cheques: Cheque[], dias: number) {
  return cheques
    .filter((c) => {
      if (!c.fecha_pago) return false
      const d = daysUntil(c.fecha_pago)
      return d >= 0 && d <= dias
    })
    .sort((a, b) => (a.fecha_pago ?? '').localeCompare(b.fecha_pago ?? ''))
}

// ── sub-componentes ───────────────────────────────────────────────────

function KpiCard({
  label, value, sub, accent,
}: { label: string; value: string; sub?: string; accent?: 'red' | 'green' | 'indigo' }) {
  const valueClass =
    accent === 'red'    ? 'text-red-500 dark:text-red-400' :
    accent === 'green'  ? 'text-green-600 dark:text-green-400' :
    accent === 'indigo' ? 'text-indigo-600 dark:text-indigo-400' :
    'text-slate-900 dark:text-slate-100'

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-4 sm:p-5">
      <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">{label}</p>
      <p className={`text-2xl sm:text-3xl font-bold leading-none ${valueClass}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-1.5">{sub}</p>}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-3">
      {children}
    </h2>
  )
}

function EmptyState({ text }: { text: string }) {
  return <p className="text-sm text-slate-400 py-3">{text}</p>
}

// ── página ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: cheques }   = useQuery({ queryKey: ['cartera'],   queryFn: getChequeCartera, refetchInterval: 30_000 })
  const { data: prestamos } = useQuery({ queryKey: ['prestamos'], queryFn: () => getPrestamos(), refetchInterval: 30_000 })
  const { data: clientes }  = useQuery({ queryKey: ['clientes'],  queryFn: getClientes, staleTime: 60_000 })
  const { data: reporte }   = useQuery({
    queryKey: ['reporte', monthStartISO(), todayISO()],
    queryFn: () => getReporteGanancias(monthStartISO(), todayISO()),
  })

  const clienteMap = new Map(clientes?.map((c) => [c.id, c.nombre]) ?? [])

  const totalCartera    = (cheques  ?? []).reduce((s, c) => s + parseFloat(c.monto), 0)
  const prestamosActivos = (prestamos ?? []).filter((p) => p.estado === 'activo')
  const capitalEnCalle  = prestamosActivos.reduce((s, p) => s + parseFloat(p.credito), 0)
  const vencidas        = cuotasVencidas(prestamos ?? [])
  const proximos        = chequesPorVencer(cheques ?? [], 7)

  // actividad reciente: últimos 5 registros de cheques + préstamos mezclados
  const actividad = [
    ...(cheques  ?? []).map((c) => ({ tipo: 'cheque'  as const, id: c.nro_cheque, label: `Cheque ${c.nro_cheque}`, sub: fmtARS(c.monto), date: c.created_at })),
    ...(prestamos ?? []).map((p) => ({ tipo: 'prestamo' as const, id: p.id, label: `Préstamo — ${clienteMap.get(p.cliente_id) ?? '…'}`, sub: fmtMonto(p.credito, p.moneda), date: p.created_at })),
  ]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 5)

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Resumen</h1>
        <p className="text-sm text-slate-500 mt-0.5">{new Date().toLocaleDateString('es-AR', { weekday: 'long', day: 'numeric', month: 'long' })}</p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-8">
        <KpiCard
          label="Cheques en cartera"
          value={String(cheques?.length ?? '—')}
          sub={cheques ? fmtARS(totalCartera) : undefined}
        />
        <KpiCard
          label="Capital en calle"
          value={prestamos ? fmtARS(capitalEnCalle) : '—'}
          sub={`${prestamosActivos.length} préstamo${prestamosActivos.length !== 1 ? 's' : ''} activo${prestamosActivos.length !== 1 ? 's' : ''}`}
          accent="indigo"
        />
        <KpiCard
          label="Cuotas vencidas"
          value={prestamos ? String(vencidas.length) : '—'}
          sub={vencidas.length > 0 ? 'Requieren atención' : 'Todo al día'}
          accent={vencidas.length > 0 ? 'red' : undefined}
        />
        <KpiCard
          label="Ganancia del mes"
          value={reporte ? fmtARS(reporte.total) : '—'}
          sub="Todos los módulos"
          accent="green"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Alertas */}
        <div>
          <SectionTitle>Alertas urgentes</SectionTitle>

          {/* Cuotas vencidas */}
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl mb-4 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">Cuotas vencidas</span>
              {vencidas.length > 0 && (
                <span className="ml-auto text-xs font-semibold bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400 rounded-full px-2 py-0.5">
                  {vencidas.length}
                </span>
              )}
            </div>
            <div className="divide-y divide-slate-100 dark:divide-slate-700/50">
              {vencidas.length === 0 && !prestamos && <div className="px-4 py-3 text-sm text-slate-400">Cargando…</div>}
              {vencidas.length === 0 && prestamos  && <div className="px-4 py-3"><EmptyState text="Sin cuotas vencidas" /></div>}
              {vencidas.slice(0, 4).map((c) => (
                <div key={c.id} className="px-4 py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
                      {clienteMap.get(c.cliente_id) ?? '…'}
                    </p>
                    <p className="text-xs text-red-500 dark:text-red-400">
                      Venció {fmtDate(c.fecha_vencimiento)} · hace {Math.abs(daysUntil(c.fecha_vencimiento))}d
                    </p>
                  </div>
                  <span className="text-sm font-semibold text-slate-900 dark:text-slate-100 shrink-0">
                    {fmtMonto(c.monto, c.moneda)}
                  </span>
                </div>
              ))}
              {vencidas.length > 4 && (
                <div className="px-4 py-2 text-xs text-slate-400 text-center">
                  +{vencidas.length - 4} más en Deudores
                </div>
              )}
            </div>
          </div>

          {/* Cheques próximos a vencer */}
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-yellow-400 shrink-0" />
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">Cheques vencen en 7 días</span>
              {proximos.length > 0 && (
                <span className="ml-auto text-xs font-semibold bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-400 rounded-full px-2 py-0.5">
                  {proximos.length}
                </span>
              )}
            </div>
            <div className="divide-y divide-slate-100 dark:divide-slate-700/50">
              {proximos.length === 0 && !cheques  && <div className="px-4 py-3 text-sm text-slate-400">Cargando…</div>}
              {proximos.length === 0 && cheques   && <div className="px-4 py-3"><EmptyState text="Sin cheques por vencer" /></div>}
              {proximos.slice(0, 4).map((c) => {
                const dias = daysUntil(c.fecha_pago!)
                return (
                  <div key={c.nro_cheque} className="px-4 py-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-mono font-medium text-slate-800 dark:text-slate-200 truncate">{c.nro_cheque}</p>
                      <p className="text-xs text-yellow-600 dark:text-yellow-400">
                        {dias === 0 ? 'Vence hoy' : `Vence en ${dias}d`} · {fmtDate(c.fecha_pago)}
                      </p>
                    </div>
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100 shrink-0">
                      {fmtARS(c.monto)}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Actividad reciente */}
        <div>
          <SectionTitle>Actividad reciente</SectionTitle>
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
            {actividad.length === 0 && (
              <div className="px-4 py-6 text-center text-slate-400 text-sm">
                {!cheques && !prestamos ? 'Cargando…' : 'Sin actividad registrada'}
              </div>
            )}
            <div className="divide-y divide-slate-100 dark:divide-slate-700/50">
              {actividad.map((item) => (
                <div key={item.id} className="px-4 py-3 flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 ${
                    item.tipo === 'cheque'
                      ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400'
                      : 'bg-purple-100 dark:bg-purple-900/40 text-purple-600 dark:text-purple-400'
                  }`}>
                    {item.tipo === 'cheque' ? 'CH' : 'PR'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">{item.label}</p>
                    <p className="text-xs text-slate-400">{item.sub}</p>
                  </div>
                  <span className="text-xs text-slate-400 shrink-0">
                    {fmtDate(item.date.slice(0, 10))}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
