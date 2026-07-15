import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPrestamos, pagarPrestamo } from '../api/prestamos'
import { getFiados, cobrarEfectivo } from '../api/fiados'
import { getClientes } from '../api/clientes'
import { fmtARS, fmtUSD } from '../lib/fmt'
import { chip, btnSolid, btnBordered, btnFlat } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconRefresh } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import type { Moneda, Prestamo, Fiado, Cliente } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

function fmtMoneda(monto: string | number, moneda: Moneda): string {
  return moneda === 'USD' ? fmtUSD(monto) : fmtARS(monto)
}

// ── Modelo consolidado por cliente ────────────────────────────────────

// Una deuda concreta a la que se puede imputar un pago (un préstamo o un fiado).
interface DeudaItem {
  tipo: 'prestamo' | 'fiado'
  id: string
  clienteNombre: string
  label: string
  saldo: number
  moneda: Moneda
}

interface DeudorResumen {
  clienteId: string
  nombre: string
  totalArs: number
  totalUsd: number
  deudas: DeudaItem[]
}

// Saldo pendiente de un préstamo = suma del saldo (monto − monto_pagado) de sus
// cuotas no cobradas, en la moneda del préstamo.
function saldoPrestamo(p: Prestamo): number {
  return p.cuotas_detalle
    .filter((c) => c.estado !== 'COBRADA')
    .reduce((acc, c) => acc + (parseFloat(c.monto) - parseFloat(c.monto_pagado || '0')), 0)
}

function construirResumen(
  prestamos: Prestamo[],
  fiados: Fiado[],
  clientes: Cliente[],
): DeudorResumen[] {
  const nombreDe = new Map(clientes.map((c) => [c.id, c.nombre]))
  const map = new Map<string, DeudorResumen>()

  const bucket = (clienteId: string): DeudorResumen => {
    let r = map.get(clienteId)
    if (!r) {
      r = { clienteId, nombre: nombreDe.get(clienteId) ?? '—', totalArs: 0, totalUsd: 0, deudas: [] }
      map.set(clienteId, r)
    }
    return r
  }

  for (const p of prestamos) {
    if (p.estado === 'CANCELADO') continue // ACTIVO o EN_MORA con saldo siguen contando
    const saldo = saldoPrestamo(p)
    if (saldo <= 0.009) continue
    const r = bucket(p.cliente_id)
    const pendientes = p.cuotas_detalle.filter((c) => c.estado !== 'COBRADA').length
    r.deudas.push({
      tipo: 'prestamo',
      id: p.id,
      clienteNombre: r.nombre,
      label: `Préstamo · ${pendientes}/${p.cuotas} cuota${p.cuotas > 1 ? 's' : ''} pend.`,
      saldo,
      moneda: p.moneda,
    })
    if (p.moneda === 'USD') r.totalUsd += saldo
    else r.totalArs += saldo
  }

  for (const f of fiados) {
    if (f.estado !== 'ABIERTO') continue
    const saldo = parseFloat(f.saldo_pendiente)
    if (saldo <= 0.009) continue
    const r = bucket(f.cliente_id)
    r.deudas.push({
      tipo: 'fiado',
      id: f.id,
      clienteNombre: r.nombre,
      label: `Cheque fiado · Nº ${f.cheque_nro}`,
      saldo,
      moneda: 'ARS', // los cheques (y por ende los fiados) son siempre en pesos
    })
    r.totalArs += saldo
  }

  return [...map.values()].sort((a, b) => a.nombre.localeCompare(b.nombre))
}

// ── Modal pagar una deuda (importe libre, en cualquier moneda) ─────────

function ModalPagarDeuda({ deuda, onClose, onSuccess }: { deuda: DeudaItem; onClose: () => void; onSuccess: () => void }) {
  const [monto, setMonto] = useState('')
  const [monedaPago, setMonedaPago] = useState<Moneda>(deuda.moneda)
  const [cotizacion, setCotizacion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const saldo = deuda.saldo
  const montoNum = parseFloat(monto) || 0
  const cotizNum = parseFloat(cotizacion) || 0
  const cross = monedaPago !== deuda.moneda

  // Equivalente saldado en la moneda de la deuda (solo informativo en el modal).
  let equivalente: number | null = null
  if (montoNum > 0 && (!cross || cotizNum > 0)) {
    if (!cross) equivalente = montoNum
    else if (deuda.moneda === 'USD') equivalente = montoNum / cotizNum  // deuda USD, pago ARS
    else equivalente = montoNum * cotizNum                              // deuda ARS, pago USD
    equivalente = Math.round(equivalente * 100) / 100
  }
  const cancelaTotal = equivalente !== null && Math.abs(equivalente - saldo) < 0.01
  const superaSaldo = equivalente !== null && equivalente - saldo >= 0.01
  const faltaCotiz = cross && cotizNum <= 0
  const puedeEnviar = montoNum > 0 && !faltaCotiz && equivalente !== null && !superaSaldo

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (deuda.tipo === 'prestamo') {
        await pagarPrestamo(deuda.id, {
          monto_pagado: montoNum,
          moneda_pago: monedaPago,
          cotizacion: cross ? cotizNum : null,
        })
      } else {
        await cobrarEfectivo(deuda.id, montoNum, 'panel-web', {
          moneda_pago: monedaPago,
          cotizacion: cross ? cotizNum : null,
        })
      }
      toast('success', cancelaTotal ? 'Deuda saldada' : 'Pago registrado')
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '380px' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)' }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Pagar deuda</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{deuda.clienteNombre} · {deuda.label}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', padding: '0.75rem 1rem', borderRadius: 'var(--r-md)', display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
            <span style={{ color: 'rgba(100,116,139,0.65)' }}>Saldo pendiente</span>
            <span style={{ fontWeight: 700, color: '#fbbf24' }}>{fmtMoneda(saldo, deuda.moneda)}</span>
          </div>

          <div>
            <label style={LABEL_STYLE}>Moneda de pago</label>
            <select value={monedaPago} onChange={(e) => setMonedaPago(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
              <option value="ARS">ARS (pesos)</option>
              <option value="USD">USD</option>
            </select>
          </div>

          <div>
            <label style={LABEL_STYLE}>Monto a pagar ({monedaPago})</label>
            <input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
          </div>

          {cross && (
            <div>
              <label style={LABEL_STYLE}>Cotización (pesos por 1 USD)</label>
              <input type="number" step="0.0001" min="0.0001" value={cotizacion} onChange={(e) => setCotizacion(e.target.value)} required style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.68rem', marginTop: '0.25rem', color: 'rgba(100,116,139,0.55)' }}>
                Pagás en {monedaPago}; la deuda es en {deuda.moneda}. La cotización imputa cuánto se salda.
              </p>
            </div>
          )}

          {equivalente !== null && !superaSaldo && (
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: cancelaTotal ? '#4ade80' : '#fbbf24' }}>
              {cross && `Salda ${fmtMoneda(equivalente, deuda.moneda)} de la deuda · `}
              {cancelaTotal ? 'Salda la deuda completamente' : `Saldo restante: ${fmtMoneda(saldo - equivalente, deuda.moneda)}`}
            </p>
          )}
          {superaSaldo && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#f87171' }}>El pago equivale a {fmtMoneda(equivalente!, deuda.moneda)} y supera el saldo pendiente</p>}
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Volver</button>
            <button type="submit" disabled={loading || !puedeEnviar} style={{ ...btnSolid('success'), flex: 1, padding: '0.55rem', opacity: (loading || !puedeEnviar) ? 0.5 : 1 }}>{loading ? 'Registrando…' : 'Confirmar pago'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Tarjeta de un deudor ──────────────────────────────────────────────

function DeudorCard({ deudor, onPagar }: { deudor: DeudorResumen; onPagar: (d: DeudaItem) => void }) {
  return (
    <div className="lift" style={{ ...CARD, padding: '1rem 1.15rem' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
        <h3 style={{ fontFamily: FM, fontSize: '0.92rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word' }}>{deudor.nombre}</h3>
        <div style={{ display: 'flex', gap: '1.25rem', textAlign: 'right' }}>
          {deudor.totalArs > 0.009 && (
            <div>
              <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>Total ARS</p>
              <p style={{ fontFamily: FN, fontSize: '1.2rem', color: '#fbbf24', lineHeight: 1.1, overflowWrap: 'anywhere' }}>{fmtARS(deudor.totalArs)}</p>
            </div>
          )}
          {deudor.totalUsd > 0.009 && (
            <div>
              <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>Total USD</p>
              <p style={{ fontFamily: FN, fontSize: '1.2rem', color: '#38bdf8', lineHeight: 1.1, overflowWrap: 'anywhere' }}>{fmtUSD(deudor.totalUsd)}</p>
            </div>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--bd-006)' }}>
        {deudor.deudas.map((d) => (
          <div key={`${d.tipo}-${d.id}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.6rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
              <span style={chip(d.tipo === 'prestamo' ? 'primary' : 'secondary')}>{d.tipo === 'prestamo' ? 'Préstamo' : 'Fiado'}</span>
              <span style={{ fontFamily: FM, fontSize: '0.76rem', color: 'rgba(100,116,139,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.label}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexShrink: 0 }}>
              <span style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-1)', whiteSpace: 'nowrap' }}>{fmtMoneda(d.saldo, d.moneda)}</span>
              <button onClick={() => onPagar(d)} style={{ ...btnFlat('success'), fontSize: '0.7rem', padding: '0.3rem 0.7rem' }}>Pagar</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function DeudoresGeneral() {
  const [pagando, setPagando] = useState<DeudaItem | null>(null)
  const queryClient = useQueryClient()

  const { data: prestamos, isLoading: loadingP, error: errP } = useQuery({
    queryKey: ['prestamos'],
    queryFn: () => getPrestamos(),
    refetchInterval: 30_000,
  })
  const { data: fiados, isLoading: loadingF, error: errF } = useQuery({
    queryKey: ['fiados', 'ABIERTO'],
    queryFn: () => getFiados('ABIERTO'),
    refetchInterval: 30_000,
  })
  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const isLoading = loadingP || loadingF
  const error = errP || errF
  const resumen = construirResumen(prestamos ?? [], fiados ?? [], clientes ?? [])

  const totalArs = resumen.reduce((acc, r) => acc + r.totalArs, 0)
  const totalUsd = resumen.reduce((acc, r) => acc + r.totalUsd, 0)

  function handleSuccess() {
    setPagando(null)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
  }

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>General</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Deuda consolidada de cada cliente (préstamos + cheques fiados)</p>
        </div>
        <button onClick={() => { queryClient.invalidateQueries({ queryKey: ['prestamos'] }); queryClient.invalidateQueries({ queryKey: ['fiados'] }) }} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}><IconRefresh size={14} />Actualizar</button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
        {[
          { label: 'Total a cobrar ARS', value: fmtARS(totalArs), color: '#fbbf24' },
          { label: 'Total a cobrar USD', value: fmtUSD(totalUsd), color: '#38bdf8' },
        ].map(({ label, value, color }) => (
          <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
            <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color, letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
            <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{resumen.length} deudor(es)</p>
          </div>
        ))}
      </div>

      {/* Lista */}
      {isLoading && <div style={{ ...CARD, overflow: 'hidden' }}><SkeletonRows rows={6} /></div>}
      {error && <div style={{ ...CARD, padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar los deudores.</div>}
      {!isLoading && !error && resumen.length === 0 && (
        <div style={{ ...CARD, padding: '3rem', textAlign: 'center' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>✅</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>Ningún cliente tiene deuda pendiente</p>
        </div>
      )}
      {!isLoading && !error && resumen.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {resumen.map((d) => <DeudorCard key={d.clienteId} deudor={d} onPagar={setPagando} />)}
        </div>
      )}

      {pagando && <ModalPagarDeuda deuda={pagando} onClose={() => setPagando(null)} onSuccess={handleSuccess} />}
    </div>
  )
}
