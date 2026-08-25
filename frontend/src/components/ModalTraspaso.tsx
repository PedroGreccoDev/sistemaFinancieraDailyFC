import { useState } from 'react'
import { crearTraspaso } from '../api/traspasos'
import { fmtARS, fmtUSD } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { MedioPago, Moneda } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--surface-grad)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }
const HELP: React.CSSProperties = { fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.75)', lineHeight: 1.5 }

type Sentido = 'DEPOSITO' | 'EXTRACCION'

/** De qué caja a qué caja va cada sentido. */
const CAJAS: Record<Sentido, { origen: MedioPago; destino: MedioPago }> = {
  DEPOSITO: { origen: 'EFECTIVO', destino: 'TRANSFERENCIA' },
  EXTRACCION: { origen: 'TRANSFERENCIA', destino: 'EFECTIVO' },
}

/**
 * Pasar plata de una caja a la otra: depositar o extraer.
 *
 * No se elige "origen" y "destino" por separado aunque el backend los reciba
 * así: el operador piensa "deposité" o "saqué", no en dos cajas. Ofrecer los dos
 * desplegables invita a elegir la misma en ambos, que es la única combinación
 * inválida.
 */
export default function ModalTraspaso({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: () => void
}) {
  const toast = useToast()
  const [sentido, setSentido] = useState<Sentido>('DEPOSITO')
  const [monto, setMonto] = useState('')
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [fecha, setFecha] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const montoNum = parseFloat(monto) || 0
  const fmt = moneda === 'USD' ? fmtUSD : fmtARS

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await crearTraspaso({
        monto,
        moneda,
        ...CAJAS[sentido],
        fecha: fecha || null,
      })
      toast('success', sentido === 'DEPOSITO' ? 'Depósito registrado' : 'Extracción registrada')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)' }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>
            Mover plata entre cajas
          </h2>
          <p style={{ ...HELP, marginTop: '0.2rem' }}>
            Depositar o extraer. No cambia lo que tenés: la misma plata pasa de una caja
            a la otra.
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div>
            <label style={LABEL_STYLE}>¿Qué hiciste?</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {([
                ['DEPOSITO', '💵 → 🏦', 'Deposité'],
                ['EXTRACCION', '🏦 → 💵', 'Extraje'],
              ] as [Sentido, string, string][]).map(([s, icono, texto]) => {
                const activo = sentido === s
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSentido(s)}
                    style={{
                      flex: 1,
                      fontFamily: FM,
                      fontSize: '0.78rem',
                      fontWeight: activo ? 700 : 500,
                      padding: '0.6rem 0.75rem',
                      cursor: 'pointer',
                      color: activo ? 'var(--text-1)' : 'var(--text-2)',
                      background: activo ? 'color-mix(in srgb, var(--primary) 14%, transparent)' : 'var(--bg)',
                      border: `1px solid ${activo ? 'color-mix(in srgb, var(--primary) 45%, transparent)' : 'var(--bd-012)'}`,
                      borderRadius: 'var(--r-md)',
                    }}
                  >
                    <div style={{ fontSize: '0.9rem' }}>{icono}</div>
                    {texto}
                  </button>
                )
              })}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={LABEL_STYLE}>Monto</label>
              <input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="0,00" required autoFocus style={INPUT_STYLE} />
            </div>
            <div>
              <label style={LABEL_STYLE}>Moneda</label>
              <select value={moneda} onChange={(e) => setMoneda(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </div>
          </div>

          <div>
            <label style={LABEL_STYLE}>
              Fecha <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional, hoy por defecto)</span>
            </label>
            <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} style={INPUT_STYLE} />
          </div>

          {montoNum > 0 && (
            <p style={{ ...HELP, color: 'var(--text-1)' }}>
              {sentido === 'DEPOSITO' ? (
                <>Salen <strong>{fmt(montoNum)}</strong> del cajón y entran a la cuenta.</>
              ) : (
                <>Salen <strong>{fmt(montoNum)}</strong> de la cuenta y entran al cajón.</>
              )}
              <br />
              El resultado del día no cambia: no ganaste ni perdiste nada.
            </p>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), padding: '0.5rem 1rem' }}>
              Cancelar
            </button>
            <button type="submit" disabled={loading || montoNum <= 0} style={{ ...btnSolid('primary'), padding: '0.5rem 1rem', opacity: (loading || montoNum <= 0) ? 0.5 : 1 }}>
              {loading ? 'Guardando…' : 'Registrar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
