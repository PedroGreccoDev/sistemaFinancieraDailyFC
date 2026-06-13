import { useQuery } from '@tanstack/react-query'
import { getPrestamos } from '../api/prestamos'
import { getClientes } from '../api/clientes'
import { fmtMonto, fmtDate, daysUntil } from '../lib/fmt'
import { Skeleton } from '../components/Skeleton'
import type { Prestamo, Cuota } from '../types'

type Semaforo = 'mora' | 'proximo' | 'ok' | 'cancelado'

const FM = "'Manrope', sans-serif"

function getSemaforo(prestamo: Prestamo): Semaforo {
  if (prestamo.estado !== 'ACTIVO') return 'cancelado'
  const pendientes = prestamo.cuotas_detalle.filter((c) => c.estado !== 'COBRADA')
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
      .filter((c) => c.estado !== 'COBRADA')
      .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))[0] ?? null
  )
}

const semaforoConfig: Record<Semaforo, { accent: string; borderColor: string; badgeBg: string; label: string }> = {
  mora:     { accent: 'var(--danger)',  borderColor: 'color-mix(in srgb, var(--danger) 50%, transparent)',  badgeBg: 'color-mix(in srgb, var(--danger) 12%, transparent)',  label: 'En mora' },
  proximo:  { accent: 'var(--warning)', borderColor: 'color-mix(in srgb, var(--warning) 50%, transparent)', badgeBg: 'color-mix(in srgb, var(--warning) 12%, transparent)', label: 'Vence pronto' },
  ok:       { accent: 'var(--success)', borderColor: 'color-mix(in srgb, var(--success) 45%, transparent)', badgeBg: 'color-mix(in srgb, var(--success) 12%, transparent)', label: 'Al día' },
  cancelado:{ accent: 'var(--text-2)', borderColor: 'var(--bd-008)', badgeBg: 'var(--bd-006)', label: 'Cancelado' },
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

      {loadingP && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" style={{ marginBottom: '2rem' }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} style={{ background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-card)', padding: '1.1rem 1.2rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><Skeleton w="50%" h={14} /><Skeleton w={64} h={16} /></div>
              <Skeleton w="40%" h={11} style={{ marginTop: '1rem' }} />
              <Skeleton w="65%" h={11} style={{ marginTop: '0.5rem' }} />
              <Skeleton w="100%" h={4} r={999} style={{ marginTop: '1.1rem' }} />
            </div>
          ))}
        </div>
      )}
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
            <div key={p.id} style={{ background: 'var(--surface-grad)', border: `1px solid ${cfg.borderColor}`, borderRadius: 'var(--r-lg)', boxShadow: `var(--shadow-card), 0 0 0 1px ${cfg.borderColor}`, padding: '1.1rem 1.2rem' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.875rem' }}>
                <h3 style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word', maxWidth: '70%' }}>{nombre}</h3>
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
                    <span style={{ color: 'var(--text-1)', fontWeight: 600 }}>{value}</span>
                  </div>
                ))}
                {proxima && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.25rem', borderTop: '1px solid var(--bd-006)' }}>
                    <span style={{ color: 'rgba(100,116,139,0.7)', flexShrink: 0 }}>Próxima cuota</span>
                    <div style={{ textAlign: 'right', color: 'var(--text-1)', fontWeight: 600 }}>
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
                <div style={{ height: '3px', background: 'var(--bd-006)', overflow: 'hidden' }}>
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
                <div key={p.id} style={{ background: 'var(--ov-002)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem', opacity: 0.55 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-1)' }}>{nombre}</span>
                    <span style={{ fontFamily: FM, fontSize: '0.62rem', fontWeight: 700, color: 'rgba(100,116,139,0.6)', background: 'var(--ov-004)', padding: '1px 7px' }}>{p.estado}</span>
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
