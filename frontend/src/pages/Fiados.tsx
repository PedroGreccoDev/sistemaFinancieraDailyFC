import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getFiados, cobrarEfectivo, cobrarConCheque } from '../api/fiados'
import { getChequeCartera, fiarCheque } from '../api/cheques'
import { getClientes, createCliente } from '../api/clientes'
import { fmtARS, fmtDate } from '../lib/fmt'
import { chip, btnSolid, btnBordered, btnFlat, btnGhost } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconPlus, IconRefresh } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import type { Fiado, FiadoEstado, CobrarConChequeResult, Cliente } from '../types'
import DropdownFilter from '../components/DropdownFilter'

type Filtro = 'ABIERTO' | 'todos' | 'CANCELADO'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }
const TH: React.CSSProperties = { fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)', whiteSpace: 'nowrap' }
const TD: React.CSSProperties = { fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)' }

function EstadoBadge({ estado }: { estado: FiadoEstado }) {
  const isOpen = estado === 'ABIERTO'
  return (
    <span style={chip(isOpen ? 'warning' : 'success')}>
      {isOpen ? 'Abierto' : 'Cancelado'}
    </span>
  )
}

// ── Modal cobrar en efectivo ───────────────────────────────────────────

function ModalEfectivo({ fiado, clienteNombre, onClose, onSuccess }: { fiado: Fiado; clienteNombre: string; onClose: () => void; onSuccess: () => void }) {
  const [monto, setMonto] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const saldo = parseFloat(fiado.saldo_pendiente)
  const montoNum = parseFloat(monto) || 0
  const toast = useToast()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (montoNum <= 0) { setError('El monto debe ser mayor a 0.'); return }
    if (montoNum > saldo) { setError(`No puede superar el saldo pendiente (${fmtARS(saldo)}).`); return }
    setLoading(true); setError(null)
    try { await cobrarEfectivo(fiado.id, montoNum, 'panel-web'); toast('success', montoNum >= saldo ? 'Fiado cancelado' : 'Cobro registrado'); onSuccess() }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '380px' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)' }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Cobrar en efectivo</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{clienteNombre} · Cheque {fiado.cheque_nro}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', padding: '0.75rem 1rem', borderRadius: 'var(--r-md)' }}>
            <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.3rem' }}>Saldo pendiente</p>
            <p style={{ fontFamily: FN, fontSize: 'clamp(1.1rem, 5.5vw, 1.5rem)', color: '#fbbf24', letterSpacing: '0.02em', lineHeight: 1.05, overflowWrap: 'anywhere' }}>{fmtARS(saldo)}</p>
          </div>
          <div>
            <label style={LABEL_STYLE}>Monto cobrado</label>
            <input type="number" step="0.01" min="0.01" max={saldo} value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
            {montoNum > 0 && montoNum < saldo && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.5)', marginTop: '0.25rem' }}>Saldo restante: {fmtARS(saldo - montoNum)}</p>}
            {montoNum >= saldo && montoNum > 0 && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#4ade80', marginTop: '0.25rem' }}>Cancela la deuda completamente</p>}
          </div>
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading || montoNum <= 0} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || montoNum <= 0) ? 0.5 : 1 }}>{loading ? 'Guardando…' : 'Cobrar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal cobrar con cheque ───────────────────────────────────────────

function ModalCheque({ fiado, clienteNombre, onClose, onSuccess }: { fiado: Fiado; clienteNombre: string; onClose: () => void; onSuccess: (result: CobrarConChequeResult) => void }) {
  const [nro, setNro] = useState('')
  const [monto, setMonto] = useState('')
  const [pct, setPct] = useState('')
  const [fechaEmision, setFechaEmision] = useState('')
  const [fechaPago, setFechaPago] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const saldo = parseFloat(fiado.saldo_pendiente)
  const montoNum = parseFloat(monto) || 0
  const pctNum = parseFloat(pct) || 0
  const valorNeto = montoNum * (100 - pctNum) / 100
  const diferencia = valorNeto - saldo
  const showPreview = montoNum > 0 && pct !== ''
  const toast = useToast()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null); setLoading(true)
    try {
      const result = await cobrarConCheque(fiado.id, { nro_cheque_pago: nro.trim(), monto_cheque: montoNum, porcentaje_compra_cheque: pctNum, fecha_emision: fechaEmision || null, fecha_pago: fechaPago || null, operador_id: 'panel-web' })
      toast('success', 'Cheque recibido')
      onSuccess(result)
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92vh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Cobrar con cheque</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{clienteNombre} · Saldo: {fmtARS(saldo)}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div><label style={LABEL_STYLE}>Nº de cheque</label><input type="text" value={nro} onChange={(e) => setNro(e.target.value)} placeholder="Número del cheque" required style={INPUT_STYLE} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto nominal</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>% de compra</label><input type="number" step="0.0001" min="0" max="100" value={pct} onChange={(e) => setPct(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} /></div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Fecha emisión</label><input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>Fecha de pago</label><input type="date" value={fechaPago} onChange={(e) => setFechaPago(e.target.value)} style={INPUT_STYLE} /></div>
          </div>

          {showPreview && (
            <div style={{ background: diferencia >= 0 ? 'rgba(74,222,128,0.06)' : 'rgba(251,191,36,0.06)', border: `1px solid ${diferencia >= 0 ? 'rgba(74,222,128,0.2)' : 'rgba(251,191,36,0.2)'}`, padding: '0.75rem 1rem', borderRadius: 'var(--r-md)', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.65)' }}>Valor neto del cheque</span>
                <span style={{ fontWeight: 600, color: 'var(--text-1)' }}>{fmtARS(valorNeto)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.3rem', borderTop: '1px solid var(--bd-006)' }}>
                <span style={{ fontWeight: 700, color: diferencia >= 0 ? '#4ade80' : '#fbbf24' }}>
                  {diferencia > 0 ? 'Le debés al cliente' : diferencia < 0 ? 'Saldo restante' : 'Cancela exacto'}
                </span>
                {diferencia !== 0 && <span style={{ fontWeight: 700, color: diferencia >= 0 ? '#4ade80' : '#fbbf24' }}>{fmtARS(Math.abs(diferencia))}</span>}
              </div>
            </div>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: loading ? 0.5 : 1 }}>{loading ? 'Procesando…' : 'Confirmar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal resultado cobro con cheque ──────────────────────────────────

function ModalResultado({ result, onClose }: { result: CobrarConChequeResult; onClose: () => void }) {
  const diferencia = parseFloat(result.diferencia)
  const cancelado = result.fiado.estado === 'CANCELADO'

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '380px', padding: '1.5rem' }}>
        <div style={{ textAlign: 'center', marginBottom: '1.25rem' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>{cancelado ? '🎉' : '✅'}</p>
          <h2 style={{ fontFamily: FN, fontSize: '1.75rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>{cancelado ? 'Fiado cancelado' : 'Pago parcial registrado'}</h2>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1.25rem' }}>
          {[
            { label: 'Cheque recibido', value: result.cheque_ingresado.nro_cheque, mono: true },
            { label: 'Monto nominal', value: fmtARS(result.cheque_ingresado.monto), mono: false },
          ].map(({ label, value, mono }) => (
            <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.82rem' }}>
              <span style={{ color: 'rgba(100,116,139,0.65)' }}>{label}</span>
              <span style={{ fontWeight: 700, color: 'var(--text-1)', fontFamily: mono ? "'JetBrains Mono', monospace" : FM }}>{value}</span>
            </div>
          ))}
          {cancelado && diferencia > 0 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.82rem', paddingTop: '0.5rem', borderTop: '1px solid var(--bd-006)' }}>
              <span style={{ fontWeight: 700, color: '#fbbf24' }}>Le debés al cliente</span>
              <span style={{ fontWeight: 700, color: '#fbbf24' }}>{fmtARS(diferencia)}</span>
            </div>
          )}
          {!cancelado && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.82rem', paddingTop: '0.5rem', borderTop: '1px solid var(--bd-006)' }}>
              <span style={{ fontWeight: 700, color: '#fbbf24' }}>Saldo restante</span>
              <span style={{ fontWeight: 700, color: '#fbbf24' }}>{fmtARS(result.fiado.saldo_pendiente)}</span>
            </div>
          )}
        </div>
        <button onClick={onClose} style={{ ...btnSolid('primary'), width: '100%', padding: '0.6rem', fontSize: '0.82rem' }}>Cerrar</button>
      </div>
    </div>
  )
}

// ── Modal nuevo cheque fiado ──────────────────────────────────────────

function ModalNuevoFiado({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient()
  const [chequeId, setChequeId] = useState('')
  const [clienteId, setClienteId] = useState('')
  const [pct, setPct] = useState('')
  const [motivo, setMotivo] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const [mostrandoNuevoCliente, setMostrandoNuevoCliente] = useState(false)
  const [nuevoNombre, setNuevoNombre] = useState('')
  const [nuevoTelefono, setNuevoTelefono] = useState('')
  const [cargandoCliente, setCargandoCliente] = useState(false)
  const [errorCliente, setErrorCliente] = useState<string | null>(null)

  const { data: cartera } = useQuery({ queryKey: ['cartera'], queryFn: getChequeCartera })
  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const chequeSeleccionado = cartera?.find((c) => c.id === chequeId)
  const pctNum = parseFloat(pct) || 0
  const montoNominal = chequeSeleccionado ? parseFloat(chequeSeleccionado.monto) : 0
  const saldoInicial = montoNominal * (100 - pctNum) / 100
  const showPreview = !!chequeSeleccionado && pct !== ''

  async function handleCrearCliente() {
    if (!nuevoNombre.trim()) return
    setCargandoCliente(true); setErrorCliente(null)
    try {
      const nuevo = await createCliente({ nombre: nuevoNombre.trim(), telefono: nuevoTelefono.trim() || null })
      queryClient.setQueryData<Cliente[]>(['clientes'], (prev) => [...(prev ?? []), nuevo])
      setClienteId(nuevo.id); setMostrandoNuevoCliente(false); setNuevoNombre(''); setNuevoTelefono('')
    } catch (err) { setErrorCliente((err as Error).message) }
    finally { setCargandoCliente(false) }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setError(null); setLoading(true)
    try { await fiarCheque(chequeId, { cliente_destino_id: clienteId, porcentaje_venta: pctNum, motivo: motivo.trim(), operador_id: 'panel-web' }); toast('success', 'Cheque fiado'); onSuccess() }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92vh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Nuevo cheque fiado</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Seleccioná el cheque y el cliente</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div>
            <label style={LABEL_STYLE}>Cheque</label>
            <select value={chequeId} onChange={(e) => setChequeId(e.target.value)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
              <option value="">Seleccionar cheque…</option>
              {cartera?.map((c) => <option key={c.id} value={c.id}>{c.nro_cheque}{c.banco ? ` · ${c.banco}` : ''} · {fmtARS(parseFloat(c.monto))}</option>)}
            </select>
          </div>

          <div>
            <label style={LABEL_STYLE}>Cliente</label>
            {!mostrandoNuevoCliente ? (
              <>
                <select value={clienteId} onChange={(e) => setClienteId(e.target.value)} required={!mostrandoNuevoCliente} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                  <option value="">Seleccionar cliente…</option>
                  {clientes?.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
                <button type="button" onClick={() => { setMostrandoNuevoCliente(true); setClienteId('') }} style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--primary)', background: 'transparent', border: 'none', cursor: 'pointer', marginTop: '0.35rem', padding: 0 }}>
                  + Agregar cliente nuevo
                </button>
              </>
            ) : (
              <div style={{ background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.2)', padding: '0.875rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <p style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--primary)' }}>Nuevo cliente</p>
                <input type="text" value={nuevoNombre} onChange={(e) => setNuevoNombre(e.target.value)} placeholder="Nombre *" autoFocus style={INPUT_STYLE} />
                <input type="text" value={nuevoTelefono} onChange={(e) => setNuevoTelefono(e.target.value)} placeholder="Teléfono (opcional)" style={INPUT_STYLE} />
                {errorCliente && <p style={{ fontFamily: FM, fontSize: '0.72rem', color: '#f87171' }}>{errorCliente}</p>}
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button type="button" onClick={() => { setMostrandoNuevoCliente(false); setErrorCliente(null) }} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.45rem', fontSize: '0.72rem' }}>Volver</button>
                  <button type="button" onClick={handleCrearCliente} disabled={cargandoCliente || !nuevoNombre.trim()} style={{ ...btnSolid('primary'), flex: 1, padding: '0.45rem', fontSize: '0.72rem', opacity: (cargandoCliente || !nuevoNombre.trim()) ? 0.5 : 1 }}>{cargandoCliente ? 'Creando…' : 'Crear cliente'}</button>
                </div>
              </div>
            )}
          </div>

          <div><label style={LABEL_STYLE}>% de venta</label><input type="number" step="0.0001" min="0" max="100" value={pct} onChange={(e) => setPct(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Motivo</label><input type="text" value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Motivo del fiado" required style={INPUT_STYLE} /></div>

          {showPreview && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', padding: '0.75rem 1rem', borderRadius: 'var(--r-md)', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.65)' }}>Monto nominal</span>
                <span style={{ fontWeight: 600, color: 'var(--text-1)' }}>{fmtARS(montoNominal)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.3rem', borderTop: '1px solid var(--bd-006)' }}>
                <span style={{ fontWeight: 700, color: '#fbbf24' }}>Saldo inicial a cobrar</span>
                <span style={{ fontWeight: 700, color: '#fbbf24' }}>{fmtARS(saldoInicial)}</span>
              </div>
            </div>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading || mostrandoNuevoCliente} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || mostrandoNuevoCliente) ? 0.5 : 1 }}>{loading ? 'Guardando…' : 'Confirmar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function Fiados() {
  const [filtro, setFiltro] = useState<Filtro>('ABIERTO')
  const [creandoFiado, setCreandoFiado] = useState(false)
  const [cobrandoEfectivo, setCobrandoEfectivo] = useState<Fiado | null>(null)
  const [cobrandoCheque, setCobrandoCheque] = useState<Fiado | null>(null)
  const [resultado, setResultado] = useState<CobrarConChequeResult | null>(null)
  const queryClient = useQueryClient()

  const estado = filtro === 'todos' ? undefined : filtro as FiadoEstado
  const { data: fiados, isLoading, error, refetch } = useQuery({
    queryKey: ['fiados', filtro],
    queryFn: () => getFiados(estado),
    refetchInterval: 30_000,
  })
  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const clienteMap = new Map(clientes?.map((c) => [c.id, c.nombre]) ?? [])
  const abiertos = fiados?.filter((f) => f.estado === 'ABIERTO') ?? []
  const totalSaldo = abiertos.reduce((s, f) => s + parseFloat(f.saldo_pendiente), 0)
  const clientesDistintos = new Set(abiertos.map((f) => f.cliente_id)).size

  function handleNuevoFiadoSuccess() {
    setCreandoFiado(false)
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
    queryClient.invalidateQueries({ queryKey: ['cartera'] })
  }

  function handleEfectivoSuccess() {
    setCobrandoEfectivo(null)
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
  }

  function handleChequeSuccess(result: CobrarConChequeResult) {
    setCobrandoCheque(null)
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
    queryClient.invalidateQueries({ queryKey: ['cartera'] })
    setResultado(result)
  }

  function nombreCliente(id: string) { return clienteMap.get(id) ?? '…' }

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Cheques fiados</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Deudas de clientes por cheques entregados en crédito</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button onClick={() => refetch()} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}><IconRefresh size={14} />Actualizar</button>
          <button onClick={() => setCreandoFiado(true)} style={{ ...btnSolid('primary'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', padding: '0.45rem 0.875rem' }}><IconPlus size={15} />Nuevo</button>
        </div>
      </div>

      {/* KPIs */}
      {filtro !== 'CANCELADO' && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
          {[
            { label: 'Saldo total a cobrar', value: fmtARS(totalSaldo), color: '#fbbf24', sub: `${abiertos.length} fiado(s) abierto(s)` },
            { label: 'Clientes con deuda', value: String(clientesDistintos), color: 'var(--text-1)', sub: 'cliente(s) distintos' },
          ].map(({ label, value, color, sub }) => (
            <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
              <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color, letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
              <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filtros */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '0.75rem', marginBottom: '1rem' }}>
        <DropdownFilter
          label="Estado"
          value={filtro}
          options={[
            { value: 'todos' as Filtro, label: 'Todos' },
            { value: 'ABIERTO' as Filtro, label: 'Abiertos' },
            { value: 'CANCELADO' as Filtro, label: 'Cancelados' },
          ]}
          onChange={setFiltro}
        />
      </div>

      {/* Tabla */}
      <div style={{ ...CARD, overflow: 'hidden' }}>
        {isLoading && <SkeletonRows rows={6} />}
        {error && <div style={{ padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar los fiados.</div>}
        {fiados && fiados.length === 0 && (
          <div style={{ padding: '3rem', textAlign: 'center' }}>
            <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>✅</p>
            <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>Sin fiados registrados</p>
          </div>
        )}
        {fiados && fiados.length > 0 && (
          <>
          {/* Mobile: tarjetas */}
          <div className="sm:hidden">
            {fiados.map((fiado) => (
              <div key={`m-${fiado.id}`} style={{ padding: '0.85rem 1rem', borderBottom: '1px solid var(--ov-004)' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.4rem' }}>
                  <div style={{ minWidth: 0 }}>
                    <p style={{ fontFamily: FM, fontSize: '0.86rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word' }}>{nombreCliente(fiado.cliente_id)}</p>
                    <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)', marginTop: '1px' }}>{fiado.cheque_nro} · {fmtDate(fiado.fecha_fiado)}</p>
                  </div>
                  <EstadoBadge estado={fiado.estado} />
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '0.75rem' }}>
                  <span style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)' }}>
                    Orig. {fmtARS(fiado.monto_original)} · {fiado.porcentaje_venta}%
                  </span>
                  <span style={{ fontFamily: FM, fontSize: '0.9rem', fontWeight: 700, whiteSpace: 'nowrap', color: fiado.estado === 'ABIERTO' ? '#fbbf24' : 'rgba(100,116,139,0.5)' }}>{fmtARS(fiado.saldo_pendiente)}</span>
                </div>
                {fiado.estado === 'ABIERTO' && (
                  <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.65rem' }}>
                    <button onClick={() => setCobrandoEfectivo(fiado)} style={{ ...btnFlat('primary'), flex: 1, fontSize: '0.72rem', padding: '0.4rem' }}>Efectivo</button>
                    <button onClick={() => setCobrandoCheque(fiado)} style={{ ...btnFlat('success'), flex: 1, fontSize: '0.72rem', padding: '0.4rem' }}>Con cheque</button>
                  </div>
                )}
              </div>
            ))}
          </div>
          {/* Desktop: tabla */}
          <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '640px' }}>
              <thead>
                <tr>
                  <th style={TH}>Cliente</th>
                  <th style={TH}>Cheque</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Monto orig.</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Saldo</th>
                  <th style={TH}>Fecha</th>
                  <th style={TH}>Estado</th>
                  <th style={{ ...TH, padding: '0.625rem 1rem' }} />
                </tr>
              </thead>
              <tbody>
                {fiados.map((fiado) => (
                  <tr key={fiado.id}
                    onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                    onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                    <td style={{ ...TD, fontWeight: 600 }}>{nombreCliente(fiado.cliente_id)}</td>
                    <td style={{ ...TD, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.75rem', color: 'rgba(100,116,139,0.6)' }}>{fiado.cheque_nro}</td>
                    <td style={{ ...TD, textAlign: 'right', color: 'rgba(148,163,184,0.65)', whiteSpace: 'nowrap' }}>
                      <span style={{ fontSize: '0.72rem', color: 'rgba(100,116,139,0.5)', marginRight: '4px' }}>{fiado.porcentaje_venta}%</span>
                      {fmtARS(fiado.monto_original)}
                    </td>
                    <td style={{ ...TD, textAlign: 'right', fontWeight: 700, whiteSpace: 'nowrap', color: fiado.estado === 'ABIERTO' ? '#fbbf24' : 'rgba(100,116,139,0.5)' }}>
                      {fmtARS(fiado.saldo_pendiente)}
                    </td>
                    <td style={{ ...TD, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', whiteSpace: 'nowrap' }}>{fmtDate(fiado.fecha_fiado)}</td>
                    <td style={TD}><EstadoBadge estado={fiado.estado} /></td>
                    <td style={{ ...TD, textAlign: 'right' }}>
                      {fiado.estado === 'ABIERTO' && (
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                          <button onClick={() => setCobrandoEfectivo(fiado)} style={{ ...btnGhost('primary'), fontSize: '0.68rem', padding: 0, whiteSpace: 'nowrap' }}>Efectivo</button>
                          <button onClick={() => setCobrandoCheque(fiado)} style={{ ...btnGhost('success'), fontSize: '0.68rem', padding: 0, whiteSpace: 'nowrap' }}>Con cheque</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>

      {creandoFiado && <ModalNuevoFiado onClose={() => setCreandoFiado(false)} onSuccess={handleNuevoFiadoSuccess} />}
      {cobrandoEfectivo && <ModalEfectivo fiado={cobrandoEfectivo} clienteNombre={nombreCliente(cobrandoEfectivo.cliente_id)} onClose={() => setCobrandoEfectivo(null)} onSuccess={handleEfectivoSuccess} />}
      {cobrandoCheque && <ModalCheque fiado={cobrandoCheque} clienteNombre={nombreCliente(cobrandoCheque.cliente_id)} onClose={() => setCobrandoCheque(null)} onSuccess={handleChequeSuccess} />}
      {resultado && <ModalResultado result={resultado} onClose={() => setResultado(null)} />}
    </div>
  )
}
