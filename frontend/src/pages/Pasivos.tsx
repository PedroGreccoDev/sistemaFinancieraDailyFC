import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPasivos, createPasivo, cancelarPasivoEfectivo, cancelarPasivoConCheque } from '../api/pasivos'
import { getChequeCartera } from '../api/cheques'
import { fmtARS, fmtUSD, fmtDate } from '../lib/fmt'
import type { Cheque, Moneda, Pasivo, PasivoEstado } from '../types'
import DropdownFilter from '../components/DropdownFilter'

type Filtro = 'todos' | PasivoEstado

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'linear-gradient(145deg, #0c0c10 0%, #13131a 100%)', border: '1px solid rgba(255,255,255,0.06)', boxShadow: '0 4px 24px rgba(0,0,0,0.4)' }
const MODAL_BG = '#0d0d14'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: '#080810', border: '1px solid rgba(255,255,255,0.12)', color: '#e2e8f0', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }
const TH: React.CSSProperties = { fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left', background: 'rgba(255,255,255,0.025)', borderBottom: '1px solid rgba(255,255,255,0.06)', whiteSpace: 'nowrap' }
const TD: React.CSSProperties = { fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.04)', color: '#e2e8f0' }

function EstadoBadge({ estado }: { estado: PasivoEstado }) {
  const isPending = estado === 'PENDIENTE'
  return (
    <span style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, color: isPending ? '#fbbf24' : '#4ade80', background: isPending ? 'rgba(251,191,36,0.12)' : 'rgba(74,222,128,0.12)', border: `1px solid ${isPending ? 'rgba(251,191,36,0.3)' : 'rgba(74,222,128,0.3)'}`, padding: '2px 8px' }}>
      {isPending ? 'Pendiente' : 'Cancelada'}
    </span>
  )
}

function fmtMoneda(monto: string | number, moneda: Moneda): string {
  return moneda === 'USD' ? fmtUSD(monto) : fmtARS(monto)
}

// ── Modal nueva deuda ─────────────────────────────────────────────────

function ModalNuevaDeuda({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [acreedor, setAcreedor] = useState('')
  const [concepto, setConcepto] = useState('')
  const [monto, setMonto] = useState('')
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [fechaVenc, setFechaVenc] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await createPasivo({ acreedor: acreedor.trim(), concepto: concepto.trim(), monto: parseFloat(monto), moneda, fecha_vencimiento: fechaVenc || null, observaciones: observaciones.trim() || null })
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', background: 'rgba(0,0,0,0.7)', padding: '1rem' }}>
      <div style={{ background: MODAL_BG, border: '1px solid rgba(255,255,255,0.08)', width: '100%', maxWidth: '420px', maxHeight: '92vh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid rgba(255,255,255,0.06)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: '#e2e8f0', lineHeight: 1 }}>Nueva deuda</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Registrar una deuda del negocio</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div><label style={LABEL_STYLE}>A quién le debo</label><input type="text" value={acreedor} onChange={(e) => setAcreedor(e.target.value)} required style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Concepto / razón</label><input type="text" value={concepto} onChange={(e) => setConcepto(e.target.value)} required style={INPUT_STYLE} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>Moneda</label><select value={moneda} onChange={(e) => setMoneda(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}><option value="ARS">ARS</option><option value="USD">USD</option></select></div>
          </div>
          <div><label style={LABEL_STYLE}>Vencimiento <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><input type="date" value={fechaVenc} onChange={(e) => setFechaVenc(e.target.value)} style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Observaciones <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} /></div>
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ flex: 1, padding: '0.55rem', fontFamily: FM, fontSize: '0.78rem', fontWeight: 600, background: 'transparent', border: '1px solid rgba(255,255,255,0.12)', color: 'rgba(148,163,184,0.8)', cursor: 'pointer' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ flex: 1, padding: '0.55rem', fontFamily: FM, fontSize: '0.78rem', fontWeight: 700, background: '#6366f1', border: 'none', color: '#fff', cursor: 'pointer', opacity: loading ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Registrar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal cancelar con efectivo ───────────────────────────────────────

function ModalCancelarEfectivo({ pasivo, onClose, onSuccess }: { pasivo: Pasivo; onClose: () => void; onSuccess: () => void }) {
  const saldo = parseFloat(pasivo.saldo_pendiente)
  const [montoCobrado, setMontoCobrado] = useState(pasivo.saldo_pendiente)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const montoNum = parseFloat(montoCobrado) || 0
  const cancelaTotal = montoNum === saldo && saldo > 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try { await cancelarPasivoEfectivo(pasivo.id, { monto_cobrado: montoNum }); onSuccess() }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.7)', padding: '1rem' }}>
      <div style={{ background: MODAL_BG, border: '1px solid rgba(255,255,255,0.08)', width: '100%', maxWidth: '380px' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: '#e2e8f0', lineHeight: 1 }}>Pagar con efectivo</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{pasivo.acreedor}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            {[
              { label: 'Deuda original', value: fmtMoneda(pasivo.monto, pasivo.moneda), color: '#e2e8f0' },
              { label: 'Saldo pendiente', value: fmtMoneda(pasivo.saldo_pendiente, pasivo.moneda), color: '#f87171' },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.65)' }}>{label}</span>
                <span style={{ fontWeight: 700, color }}>{value}</span>
              </div>
            ))}
          </div>
          <div>
            <label style={LABEL_STYLE}>Monto a pagar</label>
            <input type="number" step="0.01" min="0.01" max={saldo} value={montoCobrado} onChange={(e) => setMontoCobrado(e.target.value)} required style={INPUT_STYLE} />
            {montoNum > 0 && montoNum <= saldo && (
              <p style={{ fontFamily: FM, fontSize: '0.7rem', marginTop: '0.3rem', color: cancelaTotal ? '#4ade80' : '#fbbf24' }}>
                {cancelaTotal ? 'Cancela la deuda completamente' : `Saldo restante: ${fmtMoneda(saldo - montoNum, pasivo.moneda)}`}
              </p>
            )}
            {montoNum > saldo && <p style={{ fontFamily: FM, fontSize: '0.7rem', marginTop: '0.3rem', color: '#f87171' }}>Supera el saldo pendiente</p>}
          </div>
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ flex: 1, padding: '0.55rem', fontFamily: FM, fontSize: '0.78rem', fontWeight: 600, background: 'transparent', border: '1px solid rgba(255,255,255,0.12)', color: 'rgba(148,163,184,0.8)', cursor: 'pointer' }}>Volver</button>
            <button type="submit" disabled={loading || montoNum <= 0 || montoNum > saldo} style={{ flex: 1, padding: '0.55rem', fontFamily: FM, fontSize: '0.78rem', fontWeight: 700, background: '#16a34a', border: 'none', color: '#fff', cursor: 'pointer', opacity: (loading || montoNum <= 0 || montoNum > saldo) ? 0.5 : 1 }}>{loading ? 'Registrando…' : 'Confirmar pago'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal cancelar con cheque ─────────────────────────────────────────

function ModalCancelarCheque({ pasivo, onClose, onSuccess }: { pasivo: Pasivo; onClose: () => void; onSuccess: () => void }) {
  const saldo = parseFloat(pasivo.saldo_pendiente)
  const [chequeSeleccionado, setChequeSeleccionado] = useState<Cheque | null>(null)
  const [porcentajeVenta, setPorcentajeVenta] = useState('')
  const [operadorId, setOperadorId] = useState('')
  const [motivo, setMotivo] = useState(`Cancelación de deuda con ${pasivo.acreedor}`)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: cheques, isLoading: loadingCheques } = useQuery({ queryKey: ['cheques', 'cartera'], queryFn: getChequeCartera })

  function handleSelectCheque(nro: string) {
    const found = cheques?.find((c) => c.nro_cheque === nro) ?? null
    setChequeSeleccionado(found)
    if (found) setPorcentajeVenta(found.porcentaje_compra)
  }

  const montoNum = chequeSeleccionado ? parseFloat(chequeSeleccionado.monto) : 0
  const pctNum = parseFloat(porcentajeVenta) || 0
  const valorNeto = montoNum > 0 ? parseFloat((montoNum * (100 - pctNum) / 100).toFixed(2)) : null
  const diferencia = valorNeto !== null ? parseFloat((valorNeto - saldo).toFixed(2)) : null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!chequeSeleccionado) return
    setError(null)
    setLoading(true)
    try { await cancelarPasivoConCheque(pasivo.id, { nro_cheque: chequeSeleccionado.nro_cheque, porcentaje_venta: pctNum, operador_id: operadorId.trim(), motivo: motivo.trim() }); onSuccess() }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', background: 'rgba(0,0,0,0.7)', padding: '1rem' }}>
      <div style={{ background: MODAL_BG, border: '1px solid rgba(255,255,255,0.08)', width: '100%', maxWidth: '420px', maxHeight: '92vh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid rgba(255,255,255,0.06)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: '#e2e8f0', lineHeight: 1 }}>Pagar con cheque</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Entregar un cheque de cartera al acreedor</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            {[
              { label: 'Acreedor', value: pasivo.acreedor, color: '#e2e8f0' },
              { label: 'Saldo pendiente', value: fmtMoneda(pasivo.saldo_pendiente, pasivo.moneda), color: '#f87171' },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.65)' }}>{label}</span>
                <span style={{ fontWeight: 700, color }}>{value}</span>
              </div>
            ))}
          </div>

          <div>
            <label style={LABEL_STYLE}>Cheque a entregar</label>
            {loadingCheques ? <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.5)' }}>Cargando cheques…</p>
              : !cheques || cheques.length === 0 ? <p style={{ fontFamily: FM, fontSize: '0.78rem', color: '#fbbf24' }}>No hay cheques en cartera.</p>
              : <select value={chequeSeleccionado?.nro_cheque ?? ''} onChange={(e) => handleSelectCheque(e.target.value)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                  <option value="">— Seleccioná un cheque —</option>
                  {cheques.map((c) => <option key={c.nro_cheque} value={c.nro_cheque}>#{c.nro_cheque} — {fmtARS(c.monto)}{c.fecha_pago ? ` — vence ${fmtDate(c.fecha_pago)}` : ''}</option>)}
                </select>}
          </div>

          <div>
            <label style={LABEL_STYLE}>% venta aplicado</label>
            <input type="number" step="0.0001" min="0" max="100" value={porcentajeVenta} onChange={(e) => setPorcentajeVenta(e.target.value)} required style={INPUT_STYLE} />
            {chequeSeleccionado && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.5)', marginTop: '0.25rem' }}>% compra original: {chequeSeleccionado.porcentaje_compra}%</p>}
          </div>

          {chequeSeleccionado && valorNeto !== null && diferencia !== null && (
            <div style={{ background: diferencia >= 0 ? 'rgba(74,222,128,0.06)' : 'rgba(251,191,36,0.06)', border: `1px solid ${diferencia >= 0 ? 'rgba(74,222,128,0.2)' : 'rgba(251,191,36,0.2)'}`, padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {[
                { label: 'Nominal cheque', value: fmtARS(chequeSeleccionado.monto) },
                { label: `Valor neto (${pctNum}%)`, value: fmtARS(valorNeto) },
              ].map(({ label, value }) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                  <span style={{ color: 'rgba(100,116,139,0.65)' }}>{label}</span>
                  <span style={{ fontWeight: 600, color: '#e2e8f0' }}>{value}</span>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.3rem', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                <span style={{ fontWeight: 700, color: diferencia >= 0 ? '#4ade80' : '#fbbf24' }}>{diferencia >= 0 ? 'Cancela la deuda completamente' : 'Saldo restante'}</span>
                <span style={{ fontWeight: 700, color: diferencia >= 0 ? '#4ade80' : '#fbbf24' }}>{diferencia >= 0 ? (diferencia > 0 ? `+${fmtARS(diferencia)}` : '✓') : fmtARS(-diferencia)}</span>
              </div>
            </div>
          )}

          <div><label style={LABEL_STYLE}>Operador</label><input type="text" value={operadorId} onChange={(e) => setOperadorId(e.target.value)} required placeholder="Nombre del operador" style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Motivo</label><input type="text" value={motivo} onChange={(e) => setMotivo(e.target.value)} required style={INPUT_STYLE} /></div>

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ flex: 1, padding: '0.55rem', fontFamily: FM, fontSize: '0.78rem', fontWeight: 600, background: 'transparent', border: '1px solid rgba(255,255,255,0.12)', color: 'rgba(148,163,184,0.8)', cursor: 'pointer' }}>Volver</button>
            <button type="submit" disabled={loading || !chequeSeleccionado || !cheques || cheques.length === 0} style={{ flex: 1, padding: '0.55rem', fontFamily: FM, fontSize: '0.78rem', fontWeight: 700, background: '#6366f1', border: 'none', color: '#fff', cursor: 'pointer', opacity: (loading || !chequeSeleccionado) ? 0.5 : 1 }}>{loading ? 'Registrando…' : 'Confirmar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function Pasivos() {
  const [filtro, setFiltro] = useState<Filtro>('PENDIENTE')
  const [pasivoEfectivo, setPasivoEfectivo] = useState<Pasivo | null>(null)
  const [pasivoCheque, setPasivoCheque] = useState<Pasivo | null>(null)
  const [mostrarNueva, setMostrarNueva] = useState(false)
  const queryClient = useQueryClient()

  const estado = filtro === 'todos' ? undefined : filtro as PasivoEstado
  const { data: pasivos, isLoading, error, refetch } = useQuery({
    queryKey: ['pasivos', filtro],
    queryFn: () => getPasivos(estado),
    refetchInterval: 30_000,
  })

  const pendientes = pasivos?.filter((p) => p.estado === 'PENDIENTE') ?? []
  const totalARS = pendientes.filter((p) => p.moneda === 'ARS').reduce((acc, p) => acc + parseFloat(p.saldo_pendiente), 0)
  const totalUSD = pendientes.filter((p) => p.moneda === 'USD').reduce((acc, p) => acc + parseFloat(p.saldo_pendiente), 0)

  function handleSuccess() {
    setPasivoEfectivo(null); setPasivoCheque(null); setMostrarNueva(false)
    queryClient.invalidateQueries({ queryKey: ['pasivos'] })
    queryClient.invalidateQueries({ queryKey: ['cheques'] })
  }

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: '#e2e8f0', lineHeight: 1, marginBottom: '0.2rem' }}>Deudas</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Deudas del negocio con clientes y proveedores</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button onClick={() => setMostrarNueva(true)} style={{ fontFamily: FM, fontSize: '0.75rem', fontWeight: 700, background: '#6366f1', border: 'none', color: '#fff', padding: '0.45rem 0.875rem', cursor: 'pointer' }}>+ Nueva deuda</button>
          <button onClick={() => refetch()} style={{ fontFamily: FM, fontSize: '0.75rem', fontWeight: 600, background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(148,163,184,0.7)', padding: '0.45rem 0.875rem', cursor: 'pointer' }}>Actualizar</button>
        </div>
      </div>

      {/* KPIs */}
      {filtro !== 'CANCELADA' && (
        <div className="grid grid-cols-2 gap-3" style={{ marginBottom: '1.25rem' }}>
          {[
            { label: 'Saldo pendiente ARS', value: fmtARS(totalARS), sub: `${pendientes.filter((p) => p.moneda === 'ARS').length} deuda(s)` },
            { label: 'Saldo pendiente USD', value: fmtUSD(totalUSD), sub: `${pendientes.filter((p) => p.moneda === 'USD').length} deuda(s)` },
          ].map(({ label, value, sub }) => (
            <div key={label} style={{ ...CARD, padding: '1rem 1.2rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
              <p style={{ fontFamily: FN, fontSize: '1.75rem', color: '#f87171', letterSpacing: '0.03em', lineHeight: 1, marginBottom: '0.2rem' }}>{value}</p>
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
            { value: 'PENDIENTE' as Filtro, label: 'Pendientes' },
            { value: 'CANCELADA' as Filtro, label: 'Cancelados' },
          ]}
          onChange={(v) => setFiltro(v as Filtro)}
        />
      </div>

      {/* Lista */}
      <div style={{ ...CARD, overflow: 'hidden' }}>
        {isLoading && <div style={{ padding: '3rem', textAlign: 'center', color: 'rgba(100,116,139,0.6)', fontFamily: FM, fontSize: '0.82rem' }}>Cargando deudas…</div>}
        {error && <div style={{ padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar las deudas.</div>}
        {pasivos && pasivos.length === 0 && (
          <div style={{ padding: '3rem', textAlign: 'center' }}>
            <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>✅</p>
            <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>Sin deudas registradas</p>
          </div>
        )}
        {pasivos && pasivos.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '640px' }}>
              <thead>
                <tr>
                  <th style={TH}>Acreedor</th>
                  <th style={TH}>Concepto</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Original</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Saldo</th>
                  <th style={TH}>Vencimiento</th>
                  <th style={TH}>Estado</th>
                  <th style={{ ...TH, padding: '0.625rem 1rem' }} />
                </tr>
              </thead>
              <tbody>
                {pasivos.map((pasivo) => (
                  <tr key={pasivo.id}
                    onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'}
                    onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                    <td style={{ ...TD, fontWeight: 600 }}>{pasivo.acreedor}</td>
                    <td style={{ ...TD, color: 'rgba(148,163,184,0.7)', maxWidth: '220px', whiteSpace: 'normal', wordBreak: 'break-word' }}>{pasivo.concepto}</td>
                    <td style={{ ...TD, textAlign: 'right', color: 'rgba(100,116,139,0.6)' }}>{fmtMoneda(pasivo.monto, pasivo.moneda)}</td>
                    <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#f87171' }}>{fmtMoneda(pasivo.saldo_pendiente, pasivo.moneda)}</td>
                    <td style={{ ...TD, color: 'rgba(100,116,139,0.6)', fontSize: '0.72rem', whiteSpace: 'nowrap' }}>{pasivo.fecha_vencimiento ? fmtDate(pasivo.fecha_vencimiento) : '—'}</td>
                    <td style={TD}><EstadoBadge estado={pasivo.estado} /></td>
                    <td style={{ ...TD, textAlign: 'right' }}>
                      {pasivo.estado === 'PENDIENTE' && (
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                          <button onClick={() => setPasivoEfectivo(pasivo)} style={{ fontFamily: FM, fontSize: '0.68rem', fontWeight: 700, color: '#4ade80', background: 'rgba(74,222,128,0.08)', border: '1px solid rgba(74,222,128,0.2)', padding: '2px 8px', cursor: 'pointer' }}>Efectivo</button>
                          <button onClick={() => setPasivoCheque(pasivo)} style={{ fontFamily: FM, fontSize: '0.68rem', fontWeight: 700, color: '#818cf8', background: 'rgba(129,140,248,0.08)', border: '1px solid rgba(129,140,248,0.2)', padding: '2px 8px', cursor: 'pointer' }}>Con cheque</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {mostrarNueva && <ModalNuevaDeuda onClose={() => setMostrarNueva(false)} onSuccess={handleSuccess} />}
      {pasivoEfectivo && <ModalCancelarEfectivo pasivo={pasivoEfectivo} onClose={() => setPasivoEfectivo(null)} onSuccess={handleSuccess} />}
      {pasivoCheque && <ModalCancelarCheque pasivo={pasivoCheque} onClose={() => setPasivoCheque(null)} onSuccess={handleSuccess} />}
    </div>
  )
}
