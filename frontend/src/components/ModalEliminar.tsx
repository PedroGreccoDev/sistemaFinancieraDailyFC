import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { anular, previsualizarAnulacion, type EntidadAnulable } from '../api/anulacion'
import { useAuth } from '../auth/AuthContext'
import { fmtMonto } from '../lib/fmt'
import { btnSolid, btnBordered, chip } from '../lib/ui'
import { useToast } from '../lib/toast'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

/**
 * Confirmación de "Eliminar" para cualquier operación del sistema.
 *
 * Eliminar acá NO borra: **anula**. El registro sale de los listados y sus
 * movimientos de caja se revierten, pero queda guardado con quién lo anuló y por
 * qué, para poder auditar después por qué la caja dio distinto.
 *
 * Antes de confirmar se le pregunta al backend qué impacto tiene la baja y se
 * muestran las líneas de caja que se van a revertir: el operador ve lo que va a
 * pasar en vez de apretar a ciegas. Si el backend devuelve un bloqueo (por
 * ejemplo, un fiado que ya recibió cobros), el botón de confirmar no se habilita.
 */
export default function ModalEliminar({
  entidad,
  id,
  onClose,
  onSuccess,
}: {
  entidad: EntidadAnulable
  id: string
  onClose: () => void
  onSuccess: () => void
}) {
  const { user } = useAuth()
  const toast = useToast()

  const [motivo, setMotivo] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: impacto, isLoading, error: errorPreview } = useQuery({
    queryKey: ['anulacion-preview', entidad, id],
    queryFn: () => previsualizarAnulacion(entidad, id),
    staleTime: 0,
  })

  const bloqueado = !!impacto?.bloqueo
  const puedeConfirmar = !!impacto?.puede_anular && motivo.trim().length > 0 && !loading

  async function handleConfirmar() {
    if (!puedeConfirmar) return
    setError(null)
    setLoading(true)
    try {
      await anular(entidad, id, {
        operador_id: user?.username ?? 'panel',
        motivo: motivo.trim(),
      })
      toast('success', 'Operación eliminada')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '460px', maxHeight: '92dvh', overflowY: 'auto' }}>

        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Eliminar operación</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>
            Se revierten sus movimientos de caja. Queda registrado quién la eliminó y por qué.
          </p>
        </div>

        <div style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

          {isLoading && (
            <p style={{ fontFamily: FM, fontSize: '0.8rem', color: 'rgba(100,116,139,0.7)' }}>Calculando el impacto…</p>
          )}

          {errorPreview && (
            <p style={{ fontFamily: FM, fontSize: '0.78rem', color: '#f87171' }}>{(errorPreview as Error).message}</p>
          )}

          {impacto && (
            <>
              {/* Qué se está por eliminar */}
              <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem' }}>
                <p style={{ ...LABEL_STYLE, marginBottom: '0.35rem' }}>Operación</p>
                <p style={{ fontFamily: FM, fontSize: '0.85rem', color: 'var(--text-1)', fontWeight: 600 }}>{impacto.descripcion}</p>
              </div>

              {/* Bloqueo: no se puede anular y se explica por qué */}
              {bloqueado && (
                <div style={{ background: 'color-mix(in srgb, var(--danger) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--danger) 35%, transparent)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem' }}>
                  <p style={{ ...LABEL_STYLE, color: 'var(--danger)', marginBottom: '0.35rem' }}>No se puede eliminar</p>
                  <p style={{ fontFamily: FM, fontSize: '0.8rem', color: 'var(--text-1)', lineHeight: 1.45 }}>{impacto.bloqueo}</p>
                </div>
              )}

              {/* Movimientos de caja que se revierten */}
              {!bloqueado && (
                <div>
                  <p style={LABEL_STYLE}>Movimientos de caja que se revierten</p>
                  {impacto.lineas.length === 0 ? (
                    <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.7)' }}>
                      Ninguno: esta operación no movió plata.
                    </p>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                      {impacto.lineas.map((l, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', background: 'var(--ov-002)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-sm)', padding: '0.45rem 0.7rem' }}>
                          <div style={{ minWidth: 0 }}>
                            <span style={chip(l.tipo === 'INGRESO' ? 'success' : 'danger')}>{l.tipo}</span>
                            <span style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.8)', marginLeft: '0.45rem' }}>
                              {l.fecha.split('-').reverse().join('/')}
                            </span>
                            {l.detalle && (
                              <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'var(--text-2)', marginTop: '0.15rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {l.detalle}
                              </p>
                            )}
                          </div>
                          <span style={{ fontFamily: FM, fontSize: '0.8rem', fontWeight: 700, color: l.tipo === 'INGRESO' ? 'var(--success)' : '#f87171', whiteSpace: 'nowrap' }}>
                            {fmtMonto(l.monto, l.moneda)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Entidades que se dan de baja junto con esta */}
              {!bloqueado && impacto.arrastra.length > 0 && (
                <div style={{ background: 'color-mix(in srgb, var(--warning) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--warning) 30%, transparent)', borderRadius: 'var(--r-md)', padding: '0.7rem 1rem' }}>
                  <p style={{ ...LABEL_STYLE, color: 'var(--warning)', marginBottom: '0.3rem' }}>También se da de baja</p>
                  <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
                    {impacto.arrastra.map((a, i) => (
                      <li key={i} style={{ fontFamily: FM, fontSize: '0.78rem', color: 'var(--text-1)' }}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Motivo — obligatorio */}
              {!bloqueado && (
                <div>
                  <label style={LABEL_STYLE}>Motivo</label>
                  <input
                    type="text"
                    value={motivo}
                    onChange={(e) => setMotivo(e.target.value)}
                    placeholder="Ej: cargado por error, duplicado, prueba…"
                    autoFocus
                    style={INPUT_STYLE}
                  />
                </div>
              )}
            </>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>
              {bloqueado ? 'Entendido' : 'Cancelar'}
            </button>
            {!bloqueado && (
              <button
                type="button"
                onClick={handleConfirmar}
                disabled={!puedeConfirmar}
                style={{ ...btnSolid('danger'), flex: 1, padding: '0.55rem', opacity: puedeConfirmar ? 1 : 0.5, cursor: puedeConfirmar ? 'pointer' : 'not-allowed' }}
              >
                {loading ? 'Eliminando…' : 'Eliminar'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
