import { useState } from 'react'
import { revertirCheque } from '../api/anulacion'
import { useAuth } from '../auth/AuthContext'
import { fmtARS } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { Cheque } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

/**
 * Deshace la venta/cobro/fiado de un cheque y lo devuelve a EN CARTERA.
 *
 * No es lo mismo que eliminar: el cheque **sigue existiendo** y queda disponible
 * para volver a venderse. Se borra el ingreso que había generado; el egreso de
 * cuando se compró el cheque se conserva, porque esa plata salió igual.
 */
export default function ModalRevertirCheque({
  cheque,
  onClose,
  onSuccess,
}: {
  cheque: Cheque
  onClose: () => void
  onSuccess: () => void
}) {
  const { user } = useAuth()
  const toast = useToast()

  const [motivo, setMotivo] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Lo que entró a caja al venderlo: monto · (1 − %venta). Es lo que se revierte.
  const ingreso =
    cheque.porcentaje_venta != null
      ? parseFloat(cheque.monto) * (100 - parseFloat(cheque.porcentaje_venta)) / 100
      : null

  async function handleConfirmar() {
    if (!motivo.trim() || loading) return
    setError(null)
    setLoading(true)
    try {
      await revertirCheque(cheque.id, {
        operador_id: user?.username ?? 'panel',
        motivo: motivo.trim(),
      })
      toast('success', 'Cheque devuelto a cartera')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>

        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)' }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Volver a cartera</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>
            El cheque vuelve a estar disponible para venderse o fiarse.
          </p>
        </div>

        <div style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem' }}>
            <p style={{ ...LABEL_STYLE, marginBottom: '0.35rem' }}>Cheque</p>
            <p style={{ fontFamily: FM, fontSize: '0.85rem', color: 'var(--text-1)', fontWeight: 600 }}>
              Nº {cheque.nro_cheque}{cheque.banco ? ` — ${cheque.banco}` : ''}
            </p>
            <p style={{ fontFamily: FM, fontSize: '0.75rem', color: 'rgba(100,116,139,0.75)', marginTop: '0.2rem' }}>
              {fmtARS(cheque.monto)} · hoy está {cheque.estado.replace('_', ' ')}
            </p>
          </div>

          <div style={{ background: 'color-mix(in srgb, var(--warning) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--warning) 30%, transparent)', borderRadius: 'var(--r-md)', padding: '0.7rem 1rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'var(--text-1)', lineHeight: 1.5 }}>
              {ingreso != null ? (
                <>Se saca de la caja el ingreso de <strong>{fmtARS(ingreso)}</strong> que generó esta operación. El egreso de cuando compraste el cheque se mantiene.</>
              ) : (
                <>Se revierte el ingreso que generó esta operación. El egreso de cuando compraste el cheque se mantiene.</>
              )}
            </p>
          </div>

          <div>
            <label style={LABEL_STYLE}>Motivo</label>
            <input
              type="text"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              placeholder="Ej: se cayó la venta, cargué mal el estado…"
              autoFocus
              style={INPUT_STYLE}
            />
          </div>

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button
              type="button"
              onClick={handleConfirmar}
              disabled={!motivo.trim() || loading}
              style={{ ...btnSolid('warning'), flex: 1, padding: '0.55rem', opacity: (!motivo.trim() || loading) ? 0.5 : 1, cursor: (!motivo.trim() || loading) ? 'not-allowed' : 'pointer' }}
            >
              {loading ? 'Revirtiendo…' : 'Volver a cartera'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
