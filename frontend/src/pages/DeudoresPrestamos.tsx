import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPrestamos, createPrestamo, cobrarCuotasLote, cobrarCuotasConChequeLote } from '../api/prestamos'
import { getClientes, createCliente } from '../api/clientes'
import { fmtMonto, fmtDate, daysUntil } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import { Skeleton } from '../components/Skeleton'
import { IconPlus } from '../components/icons'
import type { Prestamo, Cuota, Moneda, Frecuencia, Cliente } from '../types'

type Semaforo = 'mora' | 'proximo' | 'ok' | 'cancelado'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

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

const FRECUENCIAS: { value: Frecuencia; label: string }[] = [
  { value: 'DIARIA',    label: 'Diaria' },
  { value: 'SEMANAL',   label: 'Semanal' },
  { value: 'QUINCENAL', label: 'Quincenal' },
  { value: 'MENSUAL',   label: 'Mensual' },
  { value: 'ANUAL',     label: 'Anual' },
]

// ── Modal cobrar cuota ────────────────────────────────────────────────

function ModalCobrarCuota({
  prestamo,
  clienteNombre,
  onClose,
  onSuccess,
}: {
  prestamo: Prestamo
  clienteNombre: string
  onClose: () => void
  onSuccess: () => void
}) {
  const queryClient = useQueryClient()
  const toast = useToast()

  const pendientes = prestamo.cuotas_detalle
    .filter((c) => c.estado !== 'COBRADA')
    .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))

  const [cuotaIds, setCuotaIds] = useState<Set<string>>(
    () => new Set(pendientes[0]?.id ? [pendientes[0].id] : [])
  )
  const [metodo, setMetodo] = useState<'efectivo' | 'transferencia' | 'cheque'>('efectivo')
  const [fechaCobro, setFechaCobro] = useState('')

  const [nroCheque, setNroCheque] = useState('')
  const [banco, setBanco] = useState('')
  const [montoCheque, setMontoCheque] = useState('')
  const [pctCompra, setPctCompra] = useState('')
  const [fechaEmision, setFechaEmision] = useState('')
  const [fechaPago, setFechaPago] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const cuotasSeleccionadas = pendientes.filter((c) => cuotaIds.has(c.id))
  const totalSeleccionado = cuotasSeleccionadas.reduce((sum, c) => sum + parseFloat(c.monto), 0)

  function toggleCuota(id: string) {
    setCuotaIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    const ids = [...cuotaIds]
    const n = ids.length
    try {
      if (metodo === 'efectivo' || metodo === 'transferencia') {
        await cobrarCuotasLote(prestamo.id, { cuota_ids: ids, fecha_cobro: fechaCobro || null })
        toast('success', `${n} cuota${n > 1 ? 's' : ''} cobrada${n > 1 ? 's' : ''} en ${metodo}`)
      } else {
        await cobrarCuotasConChequeLote(prestamo.id, {
          cuota_ids: ids,
          nro_cheque: nroCheque.trim(),
          banco: banco.trim() || null,
          monto: parseFloat(montoCheque),
          porcentaje_compra: parseFloat(pctCompra) || 0,
          fecha_emision: fechaEmision || null,
          fecha_pago: fechaPago || null,
          cliente_origen_id: prestamo.cliente_id,
          fecha_cobro: fechaCobro || null,
        })
        queryClient.invalidateQueries({ queryKey: ['cartera'] })
        toast('success', `${n} cuota${n > 1 ? 's' : ''} cobrada${n > 1 ? 's' : ''} · cheque ingresado a cartera`)
      }
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>

        {/* Header */}
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 1 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Cobrar cuota</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{clienteNombre} · {pendientes.length} cuota(s) pendiente(s)</p>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>

          {/* Lista de cuotas pendientes */}
          <div>
            <p style={LABEL_STYLE}>Seleccioná las cuotas a cobrar</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              {pendientes.map((c) => {
                const mora = daysUntil(c.fecha_vencimiento) < 0
                const selected = cuotaIds.has(c.id)
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => toggleCuota(c.id)}
                    style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '0.6rem 0.875rem',
                      borderRadius: 'var(--r-md)',
                      border: selected ? '1px solid var(--primary)' : '1px solid var(--bd-008)',
                      background: selected ? 'color-mix(in srgb, var(--primary) 10%, transparent)' : 'var(--ov-002)',
                      cursor: 'pointer', textAlign: 'left', transition: 'all 0.12s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
                      <div style={{
                        width: 15, height: 15, borderRadius: '3px', flexShrink: 0,
                        border: selected ? '2px solid var(--primary)' : '2px solid var(--bd-012)',
                        background: selected ? 'var(--primary)' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        transition: 'all 0.12s ease',
                      }}>
                        {selected && <span style={{ color: '#fff', fontSize: '0.55rem', fontWeight: 900, lineHeight: 1 }}>✓</span>}
                      </div>
                      <span style={{ fontFamily: FM, fontSize: '0.8rem', fontWeight: selected ? 700 : 500, color: selected ? 'var(--primary)' : 'var(--text-1)' }}>
                        Cuota {c.numero_cuota}
                      </span>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span style={{ display: 'block', fontFamily: FM, fontSize: '0.78rem', fontWeight: 700, color: selected ? 'var(--primary)' : 'var(--text-1)' }}>
                        {fmtMonto(c.monto, prestamo.moneda)}
                      </span>
                      <span style={{ display: 'block', fontFamily: FM, fontSize: '0.65rem', color: mora ? 'var(--danger)' : 'rgba(100,116,139,0.6)', marginTop: '1px' }}>
                        {fmtDate(c.fecha_vencimiento)}{mora ? ' · en mora' : ''}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>

            {cuotaIds.size > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: FM, fontSize: '0.72rem', color: 'var(--primary)', background: 'color-mix(in srgb, var(--primary) 6%, transparent)', borderRadius: 'var(--r-md)', padding: '0.4rem 0.75rem', marginTop: '0.35rem' }}>
                <span>{cuotaIds.size} cuota{cuotaIds.size > 1 ? 's' : ''} seleccionada{cuotaIds.size > 1 ? 's' : ''}</span>
                <span style={{ fontWeight: 700 }}>{fmtMonto(totalSeleccionado, prestamo.moneda)}</span>
              </div>
            )}
          </div>

          {/* Método de pago */}
          {cuotaIds.size > 0 && (
            <div>
              <p style={LABEL_STYLE}>Método de cobro</p>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {(['efectivo', 'transferencia', 'cheque'] as const).map((m) => (
                  <button key={m} type="button" onClick={() => setMetodo(m)}
                    style={{ ...(metodo === m ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.72rem' }}>
                    {m === 'efectivo' ? 'Efectivo' : m === 'transferencia' ? 'Transferencia' : 'Cheque'}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Fecha de cobro (efectivo / transferencia) */}
          {cuotaIds.size > 0 && (metodo === 'efectivo' || metodo === 'transferencia') && (
            <div>
              <label style={LABEL_STYLE}>Fecha de cobro <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
              <input type="date" value={fechaCobro} onChange={(e) => setFechaCobro(e.target.value)} style={INPUT_STYLE} />
            </div>
          )}

          {/* Campos cheque */}
          {cuotaIds.size > 0 && metodo === 'cheque' && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div>
                  <label style={LABEL_STYLE}>Nº de cheque</label>
                  <input type="text" value={nroCheque} onChange={(e) => setNroCheque(e.target.value)} placeholder="Número" required style={INPUT_STYLE} />
                </div>
                <div>
                  <label style={LABEL_STYLE}>Banco <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
                  <input type="text" value={banco} onChange={(e) => setBanco(e.target.value)} placeholder="Banco" style={INPUT_STYLE} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div>
                  <label style={LABEL_STYLE}>Monto nominal</label>
                  <input type="number" step="0.01" min="0.01" value={montoCheque} onChange={(e) => setMontoCheque(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                </div>
                <div>
                  <label style={LABEL_STYLE}>% de compra</label>
                  <input type="number" step="0.0001" min="0" max="100" value={pctCompra} onChange={(e) => setPctCompra(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div>
                  <label style={LABEL_STYLE}>Fecha emisión</label>
                  <input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} style={INPUT_STYLE} />
                </div>
                <div>
                  <label style={LABEL_STYLE}>Fecha de pago</label>
                  <input type="date" value={fechaPago} onChange={(e) => setFechaPago(e.target.value)} style={INPUT_STYLE} />
                </div>
              </div>
              <div>
                <label style={LABEL_STYLE}>Fecha de cobro <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
                <input type="date" value={fechaCobro} onChange={(e) => setFechaCobro(e.target.value)} style={INPUT_STYLE} />
              </div>
              {parseFloat(montoCheque) > 0 && parseFloat(pctCompra) >= 0 && (
                <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.65rem 1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                    <span style={{ color: 'rgba(100,116,139,0.7)' }}>Valor neto del cheque</span>
                    <span style={{ color: 'var(--text-1)', fontWeight: 700 }}>
                      {fmtMonto(parseFloat(montoCheque) * (100 - (parseFloat(pctCompra) || 0)) / 100, prestamo.moneda)}
                    </span>
                  </div>
                </div>
              )}
            </>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading || cuotaIds.size === 0}
              style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || cuotaIds.size === 0) ? 0.5 : 1 }}>
              {loading ? 'Guardando…' : cuotaIds.size > 1 ? `Cobrar ${cuotaIds.size} cuotas` : 'Confirmar cobro'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal nuevo préstamo ──────────────────────────────────────────────

function ModalNuevoPrestamo({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()

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
      const nuevo = await createCliente({ nombre: nuevoNombre.trim(), telefono: nuevoTelefono.trim() || null })
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
    if (totalNum < creditoNum) { setError('El total a cobrar debe ser mayor o igual al capital.'); return }
    setError(null)
    setLoading(true)
    try {
      await createPrestamo({ cliente_id: clienteId, credito: creditoNum, moneda, cuotas: cuotasNum, frecuencia, total_a_cobrar: totalNum, fecha_inicio: fechaInicio || null })
      toast('success', 'Préstamo creado correctamente')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '400px', maxHeight: '92dvh', overflowY: 'auto' }}>

        {/* Header */}
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 1 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Nuevo préstamo</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Completá los datos de la operación</p>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

          {/* Cliente */}
          <div>
            <label style={LABEL_STYLE}>Cliente</label>
            {!mostrandoNuevoCliente ? (
              <>
                <select value={clienteId} onChange={(e) => setClienteId(e.target.value)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                  <option value="">Seleccionar cliente…</option>
                  {clientes?.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
                <button type="button" onClick={() => { setMostrandoNuevoCliente(true); setClienteId('') }}
                  style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--primary)', background: 'transparent', border: 'none', cursor: 'pointer', marginTop: '0.35rem', padding: 0 }}>
                  + Agregar cliente nuevo
                </button>
              </>
            ) : (
              <div style={{ border: '1px solid var(--bd-008)', borderRadius: 'var(--r-md)', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem', background: 'var(--ov-002)' }}>
                <p style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--primary)' }}>Nuevo cliente</p>
                <input type="text" value={nuevoNombre} onChange={(e) => setNuevoNombre(e.target.value)} placeholder="Nombre *" autoFocus style={INPUT_STYLE} />
                <input type="text" value={nuevoTelefono} onChange={(e) => setNuevoTelefono(e.target.value)} placeholder="Teléfono (opcional)" style={INPUT_STYLE} />
                {errorCliente && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#f87171' }}>{errorCliente}</p>}
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button type="button" onClick={() => { setMostrandoNuevoCliente(false); setErrorCliente(null) }} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.4rem', fontSize: '0.72rem' }}>Volver</button>
                  <button type="button" onClick={handleCrearCliente} disabled={cargandoCliente || !nuevoNombre.trim()} style={{ ...btnSolid('primary'), flex: 1, padding: '0.4rem', fontSize: '0.72rem', opacity: (cargandoCliente || !nuevoNombre.trim()) ? 0.5 : 1 }}>
                    {cargandoCliente ? 'Creando…' : 'Crear cliente'}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Moneda */}
          <div>
            <label style={LABEL_STYLE}>Moneda</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {(['ARS', 'USD'] as Moneda[]).map((m) => (
                <button key={m} type="button" onClick={() => setMoneda(m)}
                  style={{ ...(moneda === m ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.8rem' }}>
                  {m}
                </button>
              ))}
            </div>
          </div>

          {/* Capital y Total */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={LABEL_STYLE}>Capital</label>
              <input type="number" step="0.01" min="0.01" value={credito} onChange={(e) => setCredito(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
            </div>
            <div>
              <label style={LABEL_STYLE}>Total a cobrar</label>
              <input type="number" step="0.01" min="0.01" value={totalACobrar} onChange={(e) => setTotalACobrar(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
            </div>
          </div>

          {/* Cuotas y Frecuencia */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={LABEL_STYLE}>Cuotas</label>
              <input type="number" step="1" min="1" value={cuotas} onChange={(e) => setCuotas(e.target.value)} placeholder="1" required style={INPUT_STYLE} />
            </div>
            <div>
              <label style={LABEL_STYLE}>Frecuencia</label>
              <select value={frecuencia} onChange={(e) => setFrecuencia(e.target.value as Frecuencia)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                {FRECUENCIAS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </div>
          </div>

          {/* Fecha inicio */}
          <div>
            <label style={LABEL_STYLE}>Fecha de inicio <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
            <input type="date" value={fechaInicio} onChange={(e) => setFechaInicio(e.target.value)} style={INPUT_STYLE} />
          </div>

          {/* Preview */}
          {showPreview && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {[
                { label: 'Capital', value: fmtMonto(creditoNum, moneda), color: 'var(--text-1)' },
                { label: 'Total a cobrar', value: fmtMonto(totalNum, moneda), color: 'var(--text-1)' },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                  <span style={{ color: 'rgba(100,116,139,0.7)' }}>{label}</span>
                  <span style={{ color, fontWeight: 600 }}>{value}</span>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.35rem', borderTop: '1px solid var(--bd-006)' }}>
                <span style={{ color: 'var(--success)', fontWeight: 700 }}>Ganancia</span>
                <span style={{ color: 'var(--success)', fontWeight: 700 }}>{fmtMonto(ganancia, moneda)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.72rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.6)' }}>Cuota aprox.</span>
                <span style={{ color: 'rgba(100,116,139,0.6)' }}>{fmtMonto(montoCuota, moneda)}</span>
              </div>
            </div>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading || mostrandoNuevoCliente} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || mostrandoNuevoCliente) ? 0.5 : 1 }}>
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
  const [cobrandoCuota, setCobrandoCuota] = useState<Prestamo | null>(null)
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

  function handleCobrarCuota() {
    setCobrandoCuota(null)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
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
          style={{ ...btnSolid('primary'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', padding: '0.45rem 0.875rem' }}
        >
          <IconPlus size={15} />Nuevo
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
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.875rem' }}>
                <h3 style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word', maxWidth: '70%' }}>{nombre}</h3>
                <span style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, color: cfg.accent, background: cfg.badgeBg, border: `1px solid ${cfg.borderColor}`, padding: '2px 8px', letterSpacing: '0.05em', flexShrink: 0 }}>
                  {cfg.label}
                </span>
              </div>

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

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.62rem', color: 'rgba(100,116,139,0.6)', marginBottom: '0.3rem' }}>
                  <span>{cobradas} de {p.cuotas} cuotas</span>
                  <span style={{ textTransform: 'lowercase' }}>{p.frecuencia}</span>
                </div>
                <div style={{ display: 'flex', gap: '2px' }}>
                  {Array.from({ length: p.cuotas }).map((_, i) => (
                    <div key={i} style={{ flex: 1, height: '4px', borderRadius: '2px', background: i < cobradas ? cfg.accent : 'var(--bd-006)', transition: 'background 0.3s ease' }} />
                  ))}
                </div>
              </div>

              <button
                type="button"
                onClick={() => setCobrandoCuota(p)}
                style={{ ...btnSolid('primary'), width: '100%', marginTop: '0.75rem', padding: '0.45rem', fontSize: '0.75rem', textAlign: 'center' }}
              >
                Cobrar cuota
              </button>
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
      {cobrandoCuota && (
        <ModalCobrarCuota
          prestamo={cobrandoCuota}
          clienteNombre={clienteMap.get(cobrandoCuota.cliente_id) ?? '…'}
          onClose={() => setCobrandoCuota(null)}
          onSuccess={handleCobrarCuota}
        />
      )}
    </div>
  )
}
