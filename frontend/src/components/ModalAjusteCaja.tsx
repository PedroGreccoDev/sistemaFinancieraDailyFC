import { useState } from 'react'
import { crearAjusteCaja } from '../api/ajustes_caja'
import { useAuth } from '../auth/AuthContext'
import { fmtMonto } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { AjusteCajaMotivo, Moneda } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

const MOTIVOS: { valor: AjusteCajaMotivo; label: string; ayuda: string }[] = [
  { valor: 'CORRECCION', label: 'Corrección', ayuda: 'La caja del sistema no coincide con el efectivo real' },
  { valor: 'APORTE',     label: 'Aporte',     ayuda: 'El dueño puso plata en el negocio' },
  { valor: 'RETIRO',     label: 'Retiro',     ayuda: 'El dueño sacó plata del negocio' },
  { valor: 'OTRO',       label: 'Otro',       ayuda: 'Cualquier otra razón (contá cuál)' },
]

/** Un retiro o una corrección hacia abajo salen de la caja; el resto entra. */
const TIPO_SUGERIDO: Record<AjusteCajaMotivo, 'INGRESO' | 'EGRESO'> = {
  CORRECCION: 'INGRESO',
  APORTE:     'INGRESO',
  RETIRO:     'EGRESO',
  OTRO:       'INGRESO',
}

/**
 * Agregar o restar efectivo de la caja a mano, sin una operación de negocio detrás.
 *
 * El ajuste cuenta como ingreso o egreso del período, así que mueve el neto del día.
 * En dólares hay un paso extra: para **sumar** USD hay que decir a cuánto se
 * consiguieron, porque si no esos dólares quedan en la caja pero no se pueden
 * vender (la venta consume lotes con su costo).
 */
export default function ModalAjusteCaja({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const { user } = useAuth()
  const toast = useToast()

  const hoy = new Date().toISOString().slice(0, 10)
  const [fecha, setFecha] = useState(hoy)
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [tipo, setTipo] = useState<'INGRESO' | 'EGRESO'>('INGRESO')
  const [motivo, setMotivo] = useState<AjusteCajaMotivo>('CORRECCION')
  const [monto, setMonto] = useState('')
  const [cotizacion, setCotizacion] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const montoNum = parseFloat(monto) || 0
  const cotizacionNum = parseFloat(cotizacion) || 0
  // Sumar dólares crea un lote FIFO, y un lote sin costo no sirve para vender.
  const pideCotizacion = moneda === 'USD' && tipo === 'INGRESO'
  const faltaDescripcion = motivo === 'OTRO' && !descripcion.trim()
  const puedeGuardar = montoNum > 0 && !faltaDescripcion && (!pideCotizacion || cotizacionNum > 0)

  function elegirMotivo(nuevo: AjusteCajaMotivo) {
    setMotivo(nuevo)
    setTipo(TIPO_SUGERIDO[nuevo])
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await crearAjusteCaja({
        fecha,
        moneda,
        tipo,
        motivo,
        monto: montoNum,
        cotizacion_usd: pideCotizacion ? cotizacionNum : null,
        descripcion: descripcion.trim() || null,
        operador_id: user?.username ?? 'panel',
      })
      toast('success', tipo === 'INGRESO' ? 'Efectivo agregado a la caja' : 'Efectivo restado de la caja')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const ayuda = MOTIVOS.find((m) => m.valor === motivo)?.ayuda ?? ''

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Ajustar caja</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Agregar o restar efectivo sin una operación detrás</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

          {/* Motivo */}
          <div>
            <label style={LABEL_STYLE}>Motivo</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
              {MOTIVOS.map((m) => (
                <button key={m.valor} type="button" onClick={() => elegirMotivo(m.valor)}
                  style={{ ...(motivo === m.valor ? btnSolid('primary') : btnBordered('neutral')), padding: '0.45rem', fontSize: '0.78rem' }}>
                  {m.label}
                </button>
              ))}
            </div>
            <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.35rem' }}>{ayuda}</p>
          </div>

          {/* Sentido */}
          <div>
            <label style={LABEL_STYLE}>¿Entra o sale plata?</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button type="button" onClick={() => setTipo('INGRESO')}
                style={{ ...(tipo === 'INGRESO' ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.78rem' }}>
                + Agregar
              </button>
              <button type="button" onClick={() => setTipo('EGRESO')}
                style={{ ...(tipo === 'EGRESO' ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.78rem' }}>
                − Restar
              </button>
            </div>
          </div>

          {/* Monto + Moneda */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required placeholder="0,00" autoFocus style={INPUT_STYLE} /></div>
            <div>
              <label style={LABEL_STYLE}>Moneda</label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {(['ARS', 'USD'] as Moneda[]).map((m) => (
                  <button key={m} type="button" onClick={() => setMoneda(m)}
                    style={{ ...(moneda === m ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.78rem' }}>
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Cotización: solo al sumar dólares */}
          {pideCotizacion && (
            <div>
              <label style={LABEL_STYLE}>Cotización ($/USD)</label>
              <input type="number" step="0.01" min="0.01" value={cotizacion} onChange={(e) => setCotizacion(e.target.value)} required placeholder="Ej: 1250" style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.35rem' }}>
                A cuánto se consiguieron esos dólares. Es el costo contra el que se calcula la ganancia cuando se vendan.
              </p>
            </div>
          )}

          {/* Fecha */}
          <div><label style={LABEL_STYLE}>Fecha</label><input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} required style={INPUT_STYLE} /></div>

          {/* Descripción */}
          <div>
            <label style={LABEL_STYLE}>
              Detalle {motivo === 'OTRO' ? '' : <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span>}
            </label>
            <textarea value={descripcion} onChange={(e) => setDescripcion(e.target.value)} rows={2} placeholder="Por qué se ajusta la caja" style={{ ...INPUT_STYLE, resize: 'none' }} />
          </div>

          {montoNum > 0 && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.65rem 1rem', display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
              <span style={{ color: 'rgba(100,116,139,0.7)' }}>{tipo === 'INGRESO' ? 'Entra a caja' : 'Sale de caja'}</span>
              <span style={{ color: tipo === 'INGRESO' ? '#34d399' : '#f87171', fontWeight: 700 }}>
                {tipo === 'INGRESO' ? '+' : '−'} {fmtMonto(montoNum, moneda)}
              </span>
            </div>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading || !puedeGuardar} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || !puedeGuardar) ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Ajustar caja'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
