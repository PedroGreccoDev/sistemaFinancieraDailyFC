import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getChequeCartera, getCheques, chequeFotoUrl, editarCheque } from '../api/cheques'
import { getClientes, createCliente } from '../api/clientes'
import { fmtARS, fmtDate, daysUntil, todayISO, weekStartISO, monthStartISO, yearStartISO } from '../lib/fmt'
import { btnBordered, btnSolid } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconRefresh, IconCamera } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import ChequeFotoModal from '../components/ChequeFotoModal'
import type { Cheque, Cliente } from '../types'
import DropdownFilter from '../components/DropdownFilter'
import DateRangePicker from '../components/DateRangePicker'

const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: "'Manrope', sans-serif", fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: "'Manrope', sans-serif", fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

// ── Selector de cliente (con alta inline) ─────────────────────────────

function ClienteSelect({ label, value, onChange, clientes }: { label: string; value: string; onChange: (id: string) => void; clientes: Cliente[] }) {
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [nombre, setNombre] = useState('')
  const [tel, setTel] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function crear() {
    if (!nombre.trim()) return
    setBusy(true); setErr(null)
    try {
      const nuevo = await createCliente({ nombre: nombre.trim(), telefono: tel.trim() || null })
      qc.setQueryData<Cliente[]>(['clientes'], (prev) => [...(prev ?? []), nuevo])
      onChange(nuevo.id); setCreating(false); setNombre(''); setTel('')
    } catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <div>
      <label style={LABEL_STYLE}>{label}</label>
      {!creating ? (
        <>
          <select value={value} onChange={(e) => onChange(e.target.value)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
            <option value="">— Sin asignar —</option>
            {clientes.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
          <button type="button" onClick={() => setCreating(true)} style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--primary)', background: 'transparent', border: 'none', cursor: 'pointer', marginTop: '0.35rem', padding: 0 }}>+ Agregar cliente nuevo</button>
        </>
      ) : (
        <div style={{ border: '1px solid var(--bd-008)', borderRadius: 'var(--r-md)', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem', background: 'var(--ov-002)' }}>
          <input type="text" value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Nombre *" autoFocus style={INPUT_STYLE} />
          <input type="text" value={tel} onChange={(e) => setTel(e.target.value)} placeholder="Teléfono (opcional)" style={INPUT_STYLE} />
          {err && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#f87171' }}>{err}</p>}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button type="button" onClick={() => { setCreating(false); setErr(null) }} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.4rem', fontSize: '0.72rem' }}>Volver</button>
            <button type="button" onClick={crear} disabled={busy || !nombre.trim()} style={{ ...btnSolid('primary'), flex: 1, padding: '0.4rem', fontSize: '0.72rem', opacity: (busy || !nombre.trim()) ? 0.5 : 1 }}>{busy ? 'Creando…' : 'Crear'}</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Modal editar cheque ───────────────────────────────────────────────

function ModalEditarCheque({ cheque, onClose, onSuccess }: { cheque: Cheque; onClose: () => void; onSuccess: () => void }) {
  const tieneVenta = cheque.estado === 'VENDIDO' || cheque.estado === 'FIADO'
  const [nroCheque, setNroCheque] = useState(cheque.nro_cheque)
  const [banco, setBanco] = useState(cheque.banco ?? '')
  const [monto, setMonto] = useState(cheque.monto)
  const [pctCompra, setPctCompra] = useState(cheque.porcentaje_compra)
  const [pctVenta, setPctVenta] = useState(cheque.porcentaje_venta ?? '')
  const [fechaEmision, setFechaEmision] = useState(cheque.fecha_emision ?? '')
  const [fechaPago, setFechaPago] = useState(cheque.fecha_pago ?? '')
  const [clienteOrigenId, setClienteOrigenId] = useState(cheque.cliente_origen_id ?? '')
  const [clienteDestinoId, setClienteDestinoId] = useState(cheque.cliente_destino_id ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const { data: clientes = [] } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const montoNum = parseFloat(monto) || 0
  const compraNum = parseFloat(pctCompra) || 0
  const ventaNum = parseFloat(pctVenta) || 0
  const gananciaPreview = tieneVenta && pctVenta !== '' ? montoNum * (compraNum - ventaNum) / 100 : null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await editarCheque(cheque.id, {
        nro_cheque: nroCheque.trim(),
        banco: banco.trim() || null,
        monto: montoNum,
        porcentaje_compra: compraNum,
        fecha_emision: fechaEmision || null,
        fecha_pago: fechaPago || null,
        cliente_origen_id: clienteOrigenId || null,
        ...(tieneVenta && pctVenta !== '' ? { porcentaje_venta: ventaNum } : {}),
        ...(tieneVenta ? { cliente_destino_id: clienteDestinoId || null } : {}),
      })
      toast('success', 'Cheque actualizado')
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Editar cheque</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Nº {cheque.nro_cheque} · {cheque.estado.replace('_', ' ').toLowerCase()}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Nº de cheque</label><input type="text" value={nroCheque} onChange={(e) => setNroCheque(e.target.value)} required style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>Banco <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opc.)</span></label><input type="text" value={banco} onChange={(e) => setBanco(e.target.value)} style={INPUT_STYLE} /></div>
          </div>
          <div><label style={LABEL_STYLE}>Monto nominal</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required style={INPUT_STYLE} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: tieneVenta ? '1fr 1fr' : '1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>% compra</label><input type="number" step="0.0001" min="0" max="100" value={pctCompra} onChange={(e) => setPctCompra(e.target.value)} required style={INPUT_STYLE} /></div>
            {tieneVenta && (
              <div><label style={LABEL_STYLE}>% venta</label><input type="number" step="0.0001" min="0" max="100" value={pctVenta} onChange={(e) => setPctVenta(e.target.value)} required style={INPUT_STYLE} /></div>
            )}
          </div>
          {gananciaPreview !== null && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.9rem', display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
              <span style={{ color: 'rgba(100,116,139,0.7)' }}>Ganancia recalculada</span>
              <span style={{ fontWeight: 700, color: gananciaPreview >= 0 ? '#4ade80' : '#f87171' }}>{fmtARS(gananciaPreview)}</span>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Fecha emisión</label><input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>Fecha de pago</label><input type="date" value={fechaPago} onChange={(e) => setFechaPago(e.target.value)} style={INPUT_STYLE} /></div>
          </div>
          <ClienteSelect label="Cliente origen (de quién lo recibí)" value={clienteOrigenId} onChange={setClienteOrigenId} clientes={clientes} />
          {tieneVenta && (
            <ClienteSelect label="Cliente destino (a quién se lo di)" value={clienteDestinoId} onChange={setClienteDestinoId} clientes={clientes} />
          )}
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: loading ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Guardar cambios'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

type FilterPreset = 'hoy' | 'semana' | 'mes' | 'anio' | 'custom'

const FN = "'Bebas Neue', sans-serif"
const FM = "'Manrope', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const TH = { fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left' as const, background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)', whiteSpace: 'nowrap' as const }
const TD = { fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)' }

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
  if (dias === null) return <span style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)' }}>Sin fecha</span>
  const s = (color: string, label: string) => (
    <span style={{ fontFamily: FM, fontSize: '0.7rem', fontWeight: 700, color, background: `${color}18`, border: `1px solid ${color}35`, padding: '1px 7px' }}>{label}</span>
  )
  if (dias < 0)   return s('#f87171', `Vencido ${Math.abs(dias)}d`)
  if (dias === 0) return s('#fb923c', 'Hoy')
  if (dias <= 7)  return s('#fbbf24', `${dias}d`)
  if (dias <= 30) return s('#a3e635', `${dias}d`)
  return s('#4ade80', `${dias}d`)
}

function totalCartera(cheques: Cheque[]): number {
  return cheques.reduce((acc, c) => acc + parseFloat(c.monto), 0)
}

/** Miniatura clickeable de la foto del cheque (solo si tiene_foto). */
function FotoThumb({ cheque, onOpen, size = 52 }: { cheque: Cheque; onOpen: (c: Cheque) => void; size?: number }) {
  if (!cheque.tiene_foto) {
    return <span style={{ display: 'inline-block', width: size, height: size, flexShrink: 0 }} />
  }
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onOpen(cheque) }}
      title="Ver foto del cheque"
      style={{ padding: 0, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', overflow: 'hidden', cursor: 'pointer', width: size, height: size, flexShrink: 0, background: 'var(--ov-0025)', display: 'block' }}
    >
      <img src={chequeFotoUrl(cheque.id)} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
    </button>
  )
}

export default function Cartera() {
  const [preset, setPreset] = useState<FilterPreset>('mes')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)
  const [fotoCheque, setFotoCheque] = useState<Cheque | null>(null)
  const [chequeEditar, setChequeEditar] = useState<Cheque | null>(null)
  const queryClient = useQueryClient()

  function handleEditSuccess() {
    setChequeEditar(null)
    queryClient.invalidateQueries({ queryKey: ['cartera'] })
    queryClient.invalidateQueries({ queryKey: ['cheques-vendidos'] })
  }

  function handlePreset(p: FilterPreset) {
    setPreset(p)
    if (p !== 'custom') setShowPicker(false)
    else setShowPicker(true)
  }

  const labelPersonalizado =
    customDesde && customHasta ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
    : customDesde ? `Desde ${fmtDate(customDesde)}` : 'Personalizado'

  const { data: cheques, isLoading, error, refetch } = useQuery({ queryKey: ['cartera'], queryFn: getChequeCartera, refetchInterval: 30_000 })
  const { data: vendidos } = useQuery({ queryKey: ['cheques-vendidos'], queryFn: () => getCheques('VENDIDO'), refetchInterval: 60_000 })

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
    ? [...filterByRange(vendidos, rangeStart, rangeEnd)].sort((a, b) => (b.ultimo_evento_manual_at ?? '').localeCompare(a.ultimo_evento_manual_at ?? ''))
    : []
  const totalGanancia = filteredVendidos.reduce((acc, c) => acc + parseFloat(c.ganancia), 0)

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>

      {/* Header cartera */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Cartera</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Cheques en stock</p>
        </div>
        <button onClick={() => refetch()} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}>
          <IconRefresh size={14} />Actualizar
        </button>
      </div>

      {/* KPIs */}
      {cheques && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
          {[
            { label: 'En cartera', value: String(cheques.length), color: 'var(--text-strong)', sub: 'cheque(s) en stock' },
            { label: 'Total', value: fmtARS(totalCartera(cheques)), color: 'var(--text-strong)', sub: 'valor nominal' },
          ].map(({ label, value, color, sub }) => (
            <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
              <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color, letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
              <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tabla cartera */}
      <div style={{ ...CARD, overflow: 'hidden', marginBottom: '2.5rem' }}>
        {isLoading && <SkeletonRows rows={6} />}
        {error && <div style={{ padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar la cartera.</div>}
        {cheques && cheques.length === 0 && <div style={{ padding: '3rem', textAlign: 'center', color: 'rgba(100,116,139,0.6)', fontFamily: FM, fontSize: '0.82rem' }}>La cartera está vacía</div>}
        {sorted.length > 0 && (
          <>
          {/* Mobile: tarjetas */}
          <div className="sm:hidden">
            {sorted.map((cheque) => {
              const dias = cheque.fecha_pago ? daysUntil(cheque.fecha_pago) : null
              return (
                <div key={cheque.id} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', padding: '0.8rem 1rem', borderBottom: '1px solid var(--ov-004)' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.65rem', minWidth: 0 }}>
                    {cheque.tiene_foto && <FotoThumb cheque={cheque} onOpen={setFotoCheque} size={60} />}
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem', color: 'var(--text-1)', wordBreak: 'break-word' }}>{cheque.nro_cheque}</p>
                      <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.7)', marginTop: '2px' }}>Pago {fmtDate(cheque.fecha_pago)}</p>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <p style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-1)' }}>{fmtARS(cheque.monto)}</p>
                    <div style={{ marginTop: '4px' }}>{diasBadge(dias)}</div>
                    <button onClick={() => setChequeEditar(cheque)} style={{ ...btnBordered('neutral'), fontSize: '0.66rem', padding: '2px 8px', marginTop: '6px' }}>Editar</button>
                  </div>
                </div>
              )
            })}
          </div>
          {/* Desktop: tabla */}
          <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '540px' }}>
              <thead>
                <tr>
                  <th style={{ ...TH, width: '76px', textAlign: 'center' }} aria-label="Foto">
                    <span style={{ display: 'inline-flex', color: 'rgba(100,116,139,0.7)' }}><IconCamera size={14} /></span>
                  </th>
                  <th style={TH}>Nº Cheque</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Monto</th>
                  <th style={{ ...TH, textAlign: 'right' }} className="hidden sm:table-cell">Compra %</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Fecha pago</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Vence</th>
                  <th style={TH} className="hidden sm:table-cell">Ingresado</th>
                  <th style={{ ...TH, textAlign: 'right' }} aria-label="Acciones" />
                </tr>
              </thead>
              <tbody>
                {sorted.map((cheque) => {
                  const dias = cheque.fecha_pago ? daysUntil(cheque.fecha_pago) : null
                  return (
                    <tr key={cheque.id} style={{ transition: 'background 0.1s' }}
                      onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                      onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                      <td style={{ ...TD, width: '76px', padding: '0.5rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'center' }}><FotoThumb cheque={cheque} onOpen={setFotoCheque} /></div>
                      </td>
                      <td style={{ ...TD, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.78rem' }}>{cheque.nro_cheque}</td>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 600 }}>{fmtARS(cheque.monto)}</td>
                      <td style={{ ...TD, textAlign: 'right', color: 'rgba(148,163,184,0.7)' }} className="hidden sm:table-cell">{parseFloat(cheque.porcentaje_compra).toFixed(2)}%</td>
                      <td style={{ ...TD, textAlign: 'center', color: 'rgba(148,163,184,0.7)' }}>{fmtDate(cheque.fecha_pago)}</td>
                      <td style={{ ...TD, textAlign: 'center' }}>{diasBadge(dias)}</td>
                      <td style={{ ...TD, color: 'rgba(100,116,139,0.6)', fontSize: '0.72rem' }} className="hidden sm:table-cell">{fmtDate(cheque.created_at.slice(0, 10))}</td>
                      <td style={{ ...TD, textAlign: 'right' }}>
                        <button onClick={() => setChequeEditar(cheque)} style={{ ...btnBordered('neutral'), fontSize: '0.68rem', padding: '2px 8px' }}>Editar</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>

      {/* Historial de ventas */}
      <div style={{ marginBottom: '1.25rem', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Historial de Ventas</h2>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Cheques vendidos por período</p>
        </div>
      </div>

      <div style={{ position: 'relative', display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '0.75rem', marginBottom: '1rem' }}>
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
            from={customDesde} to={customHasta}
            onChange={(f, t) => { setCustomDesde(f); setCustomHasta(t) }}
            onClose={() => setShowPicker(false)}
          />
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
        {[
          { label: 'Cheques vendidos', value: String(filteredVendidos.length), color: 'var(--text-strong)', sub: 'en el período' },
          { label: 'Ganancia del período', value: fmtARS(totalGanancia), color: '#4ade80', sub: 'spread acumulado' },
        ].map(({ label, value, color, sub }) => (
          <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
            <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color, letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
            <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
          </div>
        ))}
      </div>

      <div style={{ ...CARD, overflow: 'hidden' }}>
        {filteredVendidos.length === 0 ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'rgba(100,116,139,0.6)', fontFamily: FM, fontSize: '0.82rem' }}>Sin ventas en el período</div>
        ) : (
          <>
          {/* Mobile: tarjetas */}
          <div className="sm:hidden">
            {filteredVendidos.map((c) => {
              return (
                <div key={c.id} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', padding: '0.8rem 1rem', borderBottom: '1px solid var(--ov-004)' }}>
                  <div style={{ minWidth: 0 }}>
                    <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem', color: 'var(--text-1)', wordBreak: 'break-word' }}>{c.nro_cheque}</p>
                    <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.7)', marginTop: '2px' }}>
                      {fmtARS(c.monto)} · {fmtDate(c.ultimo_evento_manual_at?.slice(0, 10) ?? null)}
                    </p>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>Ganancia</p>
                    <p style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: '#4ade80', marginTop: '2px' }}>{fmtARS(c.ganancia)}</p>
                    <button onClick={() => setChequeEditar(c)} style={{ ...btnBordered('neutral'), fontSize: '0.66rem', padding: '2px 8px', marginTop: '6px' }}>Editar</button>
                  </div>
                </div>
              )
            })}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.8rem 1rem', background: 'var(--ov-0025)' }}>
              <span style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 700, color: 'rgba(148,163,184,0.8)' }}>Total ganancia</span>
              <span style={{ fontFamily: FM, fontSize: '0.9rem', fontWeight: 700, color: '#4ade80' }}>{fmtARS(totalGanancia)}</span>
            </div>
          </div>
          {/* Desktop: tabla */}
          <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '620px' }}>
              <thead>
                <tr>
                  <th style={TH}>Nº Cheque</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Monto</th>
                  <th style={{ ...TH, textAlign: 'right' }} className="hidden sm:table-cell">% Compra</th>
                  <th style={{ ...TH, textAlign: 'right' }} className="hidden sm:table-cell">% Venta</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Ganancia</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Fecha venta</th>
                  <th style={{ ...TH, textAlign: 'right' }} aria-label="Acciones" />
                </tr>
              </thead>
              <tbody>
                {filteredVendidos.map(c => {
                  return (
                    <tr key={c.id}
                      onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                      onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                      <td style={{ ...TD, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.78rem' }}>{c.nro_cheque}</td>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 600 }}>{fmtARS(c.monto)}</td>
                      <td style={{ ...TD, textAlign: 'right', color: 'rgba(148,163,184,0.65)' }} className="hidden sm:table-cell">{parseFloat(c.porcentaje_compra).toFixed(2)}%</td>
                      <td style={{ ...TD, textAlign: 'right', color: 'rgba(148,163,184,0.65)' }} className="hidden sm:table-cell">
                        {c.porcentaje_venta !== null ? `${parseFloat(c.porcentaje_venta).toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 600, color: '#4ade80' }}>{fmtARS(c.ganancia)}</td>
                      <td style={{ ...TD, textAlign: 'center', color: 'rgba(148,163,184,0.65)', fontSize: '0.72rem' }}>
                        {fmtDate(c.ultimo_evento_manual_at?.slice(0, 10) ?? null)}
                      </td>
                      <td style={{ ...TD, textAlign: 'right' }}>
                        <button onClick={() => setChequeEditar(c)} style={{ ...btnBordered('neutral'), fontSize: '0.68rem', padding: '2px 8px' }}>Editar</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '1px solid var(--bd-010)', background: 'var(--ov-0025)' }}>
                  <td colSpan={4} style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'rgba(148,163,184,0.8)', borderBottom: 'none' }} className="hidden sm:table-cell">Total</td>
                  <td colSpan={4} style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'rgba(148,163,184,0.8)', borderBottom: 'none' }} className="sm:hidden">Total</td>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#4ade80', borderBottom: 'none' }}>{fmtARS(totalGanancia)}</td>
                  <td colSpan={2} style={{ ...TD, borderBottom: 'none' }} />
                </tr>
              </tfoot>
            </table>
          </div>
          </>
        )}
      </div>

      {fotoCheque && <ChequeFotoModal cheque={fotoCheque} onClose={() => setFotoCheque(null)} />}
      {chequeEditar && <ModalEditarCheque cheque={chequeEditar} onClose={() => setChequeEditar(null)} onSuccess={handleEditSuccess} />}
    </div>
  )
}
