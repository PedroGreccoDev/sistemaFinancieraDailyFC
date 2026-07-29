import { useState } from 'react'
import { pagarPrestamo } from '../api/prestamos'
import { cobrarEfectivo } from '../api/fiados'
import { cobrarDeudaSimple } from '../api/deudas_simples'
import { fmtARS, fmtUSD } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { Moneda } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

// Una deuda concreta a la que se puede imputar un pago de importe libre (parcial
// o total): un préstamo, un fiado o una deuda libre. `saldo` y `moneda` son de la
// deuda (los fiados son siempre ARS; préstamos y deudas libres, en su moneda).
export interface DeudaItem {
  tipo: 'prestamo' | 'fiado' | 'deuda_simple'
  id: string
  clienteNombre: string
  label: string
  saldo: number
  moneda: Moneda
}

function fmtMoneda(monto: string | number, moneda: Moneda): string {
  return moneda === 'USD' ? fmtUSD(monto) : fmtARS(monto)
}

/**
 * Modal de pago de importe libre (parcial o total) contra una deuda de cliente,
 * en efectivo y en cualquier moneda. Si la moneda de pago difiere de la de la
 * deuda, pide la cotización (pesos por 1 USD) y muestra el equivalente saldado.
 * El pago se imputa a las cuotas más viejas primero (préstamos) o al saldo (fiados).
 */
export default function ModalPagarDeuda({ deuda, onClose, onSuccess }: { deuda: DeudaItem; onClose: () => void; onSuccess: () => void }) {
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
      } else if (deuda.tipo === 'deuda_simple') {
        await cobrarDeudaSimple(deuda.id, {
          monto_cobrado: montoNum,
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
