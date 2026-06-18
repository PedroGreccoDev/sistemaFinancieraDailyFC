import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPrestamos, createPrestamo } from '../api/prestamos'
import { getClientes, createCliente } from '../api/clientes'
import { fmtMonto, fmtDate, daysUntil } from '../lib/fmt'
import { Skeleton } from '../components/Skeleton'
import type { Prestamo, Cuota, Moneda, Frecuencia, Cliente } from '../types'

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

function inputCls() {
  return 'w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'
}

function labelCls() {
  return 'block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1'
}

const FRECUENCIAS: { value: Frecuencia; label: string }[] = [
  { value: 'DIARIA',    label: 'Diaria' },
  { value: 'SEMANAL',   label: 'Semanal' },
  { value: 'QUINCENAL', label: 'Quincenal' },
  { value: 'MENSUAL',   label: 'Mensual' },
  { value: 'ANUAL',     label: 'Anual' },
]

// ── Modal nuevo préstamo ──────────────────────────────────────────────

function ModalNuevoPrestamo({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient()

  const [clienteId, setClienteId] = useState('')
  const [credito, setCredito] = useState('')
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [cuotas, setCuotas] = useState('')
  const [frecuencia, setFrecuencia] = useState<Frecuencia>('MENSUAL')
  const [totalACobrar, setTotalACobrar] = useState('')
  const [fechaInicio, setFechaInicio] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [mostrandoNuevoCliente, setMostrandoNuevoCliente] = useState(false)
  const [nuevoNombre, setNuevoNombre] = useState('')
  const [nuevoTelefono, setNuevoTelefono] = useState('')
  const [cargandoCliente, setCargandoCliente] = useState(false)
  const [errorCliente, setErrorCliente] = useState<string | null>(null)

  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const creditoNum = parseFloat(credito) || 0
  const totalNum = parseFloat(totalACobrar) || 0
  const cuotasNum = parseInt(cuotas) || 0
  const ganancia = totalNum - creditoNum
  const montoCuota = cuotasNum > 0 ? totalNum / cuotasNum : 0
  const showPreview = creditoNum > 0 && totalNum >= creditoNum && cuotasNum > 0

  async function handleCrearCliente() {
    if (!nuevoNombre.trim()) return
    setCargandoCliente(true)
    setErrorCliente(null)
    try {
      const nuevo = await createCliente({
        nombre: nuevoNombre.trim(),
        telefono: nuevoTelefono.trim() || null,
      })
      queryClient.setQueryData<Cliente[]>(['clientes'], (prev) => [...(prev ?? []), nuevo])
      setClienteId(nuevo.id)
      setMostrandoNuevoCliente(false)
      setNuevoNombre('')
      setNuevoTelefono('')
    } catch (err) {
      setErrorCliente((err as Error).message)
    } finally {
      setCargandoCliente(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (totalNum < creditoNum) {
      setError('El total a cobrar debe ser mayor o igual al capital.')
      return
    }
    setError(null)
    setLoading(true)
    try {
      await createPrestamo({
        cliente_id: clienteId,
        credito: creditoNum,
        moneda,
        cuotas: cuotasNum,
        frecuencia,
        total_a_cobrar: totalNum,
        fecha_inicio: fechaInicio || null,
      })
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-slate-800 rounded-xl w-full max-w-sm shadow-xl max-h-[92vh] overflow-y-auto">
        <div className="p-5 border-b border-slate-200 dark:border-slate-700 sticky top-0 bg-white dark:bg-slate-800 z-10">
          <h2 className="font-semibold text-slate-900 dark:text-slate-100">Nuevo préstamo</h2>
          <p className="text-sm text-slate-500 mt-0.5">Completá los datos de la operación</p>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Cliente */}
          <div>
            <label className={labelCls()}>Cliente</label>
            {!mostrandoNuevoCliente ? (
              <>
                <select
                  value={clienteId}
                  onChange={(e) => setClienteId(e.target.value)}
                  required
                  className={inputCls()}
                >
                  <option value="">Seleccionar cliente…</option>
                  {clientes?.map((c) => (
                    <option key={c.id} value={c.id}>{c.nombre}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => { setMostrandoNuevoCliente(true); setClienteId('') }}
                  className="mt-1.5 text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  + Agregar cliente nuevo
                </button>
              </>
            ) : (
              <div className="border border-indigo-200 dark:border-indigo-700 rounded-lg p-3 space-y-2 bg-indigo-50/50 dark:bg-indigo-900/10">
                <p className="text-xs font-medium text-indigo-700 dark:text-indigo-400">Nuevo cliente</p>
                <input
                  type="text"
                  value={nuevoNombre}
                  onChange={(e) => setNuevoNombre(e.target.value)}
                  placeholder="Nombre *"
                  autoFocus
                  className={inputCls()}
                />
                <input
                  type="text"
                  value={nuevoTelefono}
                  onChange={(e) => setNuevoTelefono(e.target.value)}
                  placeholder="Teléfono (opcional)"
                  className={inputCls()}
                />
                {errorCliente && <p className="text-xs text-red-500">{errorCliente}</p>}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => { setMostrandoNuevoCliente(false); setErrorCliente(null) }}
                    className="flex-1 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                  >
                    Volver
                  </button>
                  <button
                    type="button"
                    onClick={handleCrearCliente}
                    disabled={cargandoCliente || !nuevoNombre.trim()}
                    className="flex-1 px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {cargandoCliente ? 'Creando…' : 'Crear cliente'}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Moneda */}
          <div>
            <label className={labelCls()}>Moneda</label>
            <div className="flex gap-2">
              {(['ARS', 'USD'] as Moneda[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMoneda(m)}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    moneda === m
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          {/* Capital y Total */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls()}>Capital</label>
              <input
                type="number" step="0.01" min="0.01"
                value={credito}
                onChange={(e) => setCredito(e.target.value)}
                placeholder="0,00"
                required
                className={inputCls()}
              />
            </div>
            <div>
              <label className={labelCls()}>Total a cobrar</label>
              <input
                type="number" step="0.01" min="0.01"
                value={totalACobrar}
                onChange={(e) => setTotalACobrar(e.target.value)}
                placeholder="0,00"
                required
                className={inputCls()}
              />
            </div>
          </div>

          {/* Cuotas y Frecuencia */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls()}>Cuotas</label>
              <input
                type="number" step="1" min="1"
                value={cuotas}
                onChange={(e) => setCuotas(e.target.value)}
                placeholder="1"
                required
                className={inputCls()}
              />
            </div>
            <div>
              <label className={labelCls()}>Frecuencia</label>
              <select
                value={frecuencia}
                onChange={(e) => setFrecuencia(e.target.value as Frecuencia)}
                required
                className={inputCls()}
              >
                {FRECUENCIAS.map((f) => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Fecha inicio */}
          <div>
            <label className={labelCls()}>Fecha de inicio <span className="text-slate-400 font-normal">(opcional)</span></label>
            <input
              type="date"
              value={fechaInicio}
              onChange={(e) => setFechaInicio(e.target.value)}
              className={inputCls()}
            />
          </div>

          {/* Preview */}
          {showPreview && (
            <div className="bg-slate-50 dark:bg-slate-700/50 rounded-lg px-4 py-3 text-sm space-y-1.5">
              <div className="flex justify-between text-slate-600 dark:text-slate-400">
                <span>Capital</span>
                <span className="font-semibold">{fmtMonto(creditoNum, moneda)}</span>
              </div>
              <div className="flex justify-between text-slate-600 dark:text-slate-400">
                <span>Total a cobrar</span>
                <span className="font-semibold">{fmtMonto(totalNum, moneda)}</span>
              </div>
              <div className="flex justify-between text-green-600 dark:text-green-400 font-semibold border-t border-slate-200 dark:border-slate-600 pt-1.5">
                <span>Ganancia</span>
                <span>{fmtMonto(ganancia, moneda)}</span>
              </div>
              <div className="flex justify-between text-slate-500 dark:text-slate-400 text-xs">
                <span>Cuota aprox.</span>
                <span>{fmtMonto(montoCuota, moneda)}</span>
              </div>
            </div>
          )}

          {error && <p className="text-sm text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose}
              className="flex-1 px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={loading || mostrandoNuevoCliente}
              className="flex-1 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">
              {loading ? 'Guardando…' : 'Confirmar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function DeudoresPrestamos() {
  const [creandoPrestamo, setCreandoPrestamo] = useState(false)
  const queryClient = useQueryClient()

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

  function handleNuevoPrestamo() {
    setCreandoPrestamo(false)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    queryClient.invalidateQueries({ queryKey: ['clientes'] })
  }

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>

      {/* Leyenda + botón Nuevo */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <div>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.7)' }}>Semáforo de cuotas activas</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginTop: '0.35rem' }}>
            {(['mora', 'proximo', 'ok'] as Semaforo[]).map((s) => (
              <span key={s} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: FM, fontSize: '0.7rem', color: 'rgba(148,163,184,0.6)' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: semaforoConfig[s].accent, display: 'inline-block' }} />
                {semaforoConfig[s].label}
              </span>
            ))}
          </div>
        </div>
        <button
          onClick={() => setCreandoPrestamo(true)}
          className="text-sm font-medium bg-indigo-600 hover:bg-indigo-700 text-white rounded px-3 py-1.5 transition-colors"
        >
          Nuevo
        </button>
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

          return (
            <div key={p.id} className="lift" style={{ background: 'var(--surface-grad)', border: `1px solid ${cfg.borderColor}`, borderRadius: 'var(--r-lg)', boxShadow: `var(--shadow-card), 0 0 0 1px ${cfg.borderColor}`, padding: '1.1rem 1.2rem' }}>
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
                <div style={{ display: 'flex', gap: '2px' }}>
                  {Array.from({ length: p.cuotas }).map((_, i) => (
                    <div
                      key={i}
                      style={{
                        flex: 1,
                        height: '4px',
                        borderRadius: '2px',
                        background: i < cobradas ? cfg.accent : 'var(--bd-006)',
                        transition: 'background 0.3s ease',
                      }}
                    />
                  ))}
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

      {creandoPrestamo && (
        <ModalNuevoPrestamo
          onClose={() => setCreandoPrestamo(false)}
          onSuccess={handleNuevoPrestamo}
        />
      )}
    </div>
  )
}
