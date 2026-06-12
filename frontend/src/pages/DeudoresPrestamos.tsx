import { useQuery } from '@tanstack/react-query'
import { getPrestamos } from '../api/prestamos'
import { getClientes } from '../api/clientes'
import { fmtMonto, fmtDate, daysUntil } from '../lib/fmt'
import type { Prestamo, Cuota } from '../types'

type Semaforo = 'mora' | 'proximo' | 'ok' | 'cancelado'

const FM = "'Manrope', sans-serif"

function getSemaforo(prestamo: Prestamo): Semaforo {
  if (prestamo.estado !== 'ACTIVO') return 'cancelado'
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

const semaforoConfig: Record<Semaforo, { accent: string; borderColor: string; badgeBg: string; label: string }> = {
  mora:     { accent: '#f87171', borderColor: 'rgba(248,113,113,0.5)',  badgeBg: 'rgba(248,113,113,0.12)', label: 'En mora' },
  proximo:  { accent: '#fbbf24', borderColor: 'rgba(251,191,36,0.5)',  badgeBg: 'rgba(251,191,36,0.12)',  label: 'Vence pronto' },
  ok:       { accent: '#4ade80', borderColor: 'rgba(74,222,128,0.4)',  badgeBg: 'rgba(74,222,128,0.12)',  label: 'Al día' },
  cancelado:{ accent: 'rgba(100,116,139,0.5)', borderColor: 'rgba(255,255,255,0.08)', badgeBg: 'rgba(255,255,255,0.06)', label: 'Cancelado' },
}

export default function DeudoresPrestamos() {
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
    .filter((p) => p.estado === 'ACTIVO')
    .sort((a, b) => {
      const sa = getSemaforo(a)
      const sb = getSemaforo(b)
      const order: Record<Semaforo, number> = { mora: 0, proximo: 1, ok: 2, cancelado: 3 }
      return order[sa] - order[sb]
    })

  const cancelados = (prestamos ?? []).filter((p) => p.estado !== 'ACTIVO')

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>

      {/* Leyenda */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.7)' }}>Semáforo de cuotas activas</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem' }}>
          {(['mora', 'proximo', 'ok'] as Semaforo[]).map((s) => (
            <span key={s} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: FM, fontSize: '0.7rem', color: 'rgba(148,163,184,0.6)' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: semaforoConfig[s].accent, display: 'inline-block' }} />
              {semaforoConfig[s].label}
            </span>
          ))}
        </div>
      </div>

      {loadingP && <div style={{ textAlign: 'center', color: 'rgba(100,116,139,0.6)', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Cargando deudores…</div>}
      {errP && <div style={{ textAlign: 'center', color: '#f87171', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar préstamos.</div>}

      {activos.length === 0 && !loadingP && (
        <div style={{ textAlign: 'center', color: 'rgba(100,116,139,0.6)', padding: '3rem' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>🎉</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600 }}>No hay préstamos activos</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" style={{ marginBottom: '2rem' }}>
        {activos.map((p) => {
          const sem = getSemaforo(p)
          const cfg = semaforoConfig[sem]
          const proxima = proximaCuota(p)
          const cobradas = p.cuotas_detalle.filter((c) => c.estado === 'COBRADA').length
          const nombre = clienteMap.get(p.cliente_id) ?? '…'
          const pct = (cobradas / p.cuotas) * 100

          return (
            <div key={p.id} style={{ background: 'linear-gradient(145deg, #0c0c10 0%, #13131a 100%)', border: `1px solid ${cfg.borderColor}`, boxShadow: `0 4px 24px rgba(0,0,0,0.4), 0 0 0 1px ${cfg.borderColor}`, padding: '1.1rem 1.2rem' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.875rem' }}>
                <h3 style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: '#e2e8f0', wordBreak: 'break-word', maxWidth: '70%' }}>{nombre}</h3>
                <span style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, color: cfg.accent, background: cfg.badgeBg, border: `1px solid ${cfg.borderColor}`, padding: '2px 8px', letterSpacing: '0.05em', flexShrink: 0 }}>
                  {cfg.label}
                </span>
              </div>

              {/* Datos */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', marginBottom: '0.875rem' }}>
                {[
                  { label: 'Capital', value: fmtMonto(p.credito, p.moneda) },
                  { label: 'Total a cobrar', value: fmtMonto(p.total_a_cobrar, p.moneda) },
                ].map(({ label, value }) => (
                  <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                    <span style={{ color: 'rgba(100,116,139,0.7)' }}>{label}</span>
                    <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{value}</span>
                  </div>
                ))}
                {proxima && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.25rem', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                    <span style={{ color: 'rgba(100,116,139,0.7)', flexShrink: 0 }}>Próxima cuota</span>
                    <div style={{ textAlign: 'right', color: '#e2e8f0', fontWeight: 600 }}>
                      <span style={{ display: 'block', fontSize: '0.72rem', color: 'rgba(148,163,184,0.65)' }}>{fmtDate(proxima.fecha_vencimiento)}</span>
                      <span style={{ display: 'block' }}>{fmtMonto(proxima.monto, p.moneda)}</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Barra de progreso */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.62rem', color: 'rgba(100,116,139,0.6)', marginBottom: '0.3rem' }}>
                  <span>{cobradas} de {p.cuotas} cuotas</span>
                  <span style={{ textTransform: 'lowercase' }}>{p.frecuencia}</span>
                </div>
                <div style={{ height: '3px', background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', background: cfg.accent, width: `${pct}%`, transition: 'width 0.3s ease' }} />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {cancelados.length > 0 && (
        <details style={{ marginTop: '0.5rem' }}>
          <summary style={{ cursor: 'pointer', fontFamily: FM, fontSize: '0.75rem', color: 'rgba(100,116,139,0.55)', listStyle: 'none', display: 'flex', alignItems: 'center', gap: '0.5rem', userSelect: 'none' }}>
            <span>▶</span>
            Ver {cancelados.length} préstamo(s) cancelado(s)
          </summary>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" style={{ marginTop: '0.875rem' }}>
            {cancelados.map((p) => {
              const nombre = clienteMap.get(p.cliente_id) ?? '…'
              return (
                <div key={p.id} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', padding: '0.75rem 1rem', opacity: 0.55 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: '#e2e8f0' }}>{nombre}</span>
                    <span style={{ fontFamily: FM, fontSize: '0.62rem', fontWeight: 700, color: 'rgba(100,116,139,0.6)', background: 'rgba(255,255,255,0.04)', padding: '1px 7px' }}>{p.estado}</span>
                  </div>
                  <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{fmtMonto(p.credito, p.moneda)} · {p.cuotas} cuotas</p>
                </div>
              )
            })}
          </div>
        </details>
      )}
    </div>
  )
}
