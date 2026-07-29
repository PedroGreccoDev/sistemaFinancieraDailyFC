import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getClientes, createCliente } from '../api/clientes'
import { createDeudaSimple } from '../api/deudas_simples'
import { fmtMonto } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { Cliente, Moneda } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

/**
 * Alta de una "deuda libre" de un cliente (sin cuotas ni cheque): concepto/razón,
 * monto, moneda, fecha y observaciones. Registrarla saca la plata de la caja
 * (egreso); luego se cobra —total o parcial, en cualquier moneda— desde General o
 * la pestaña "Otras deudas". Permite dar de alta un cliente nuevo en el momento.
 */
export default function ModalNuevaDeudaSimple({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [clienteId, setClienteId] = useState('')
  const [concepto, setConcepto] = useState('')
  const [monto, setMonto] = useState('')
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [fecha, setFecha] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [mostrandoNuevoCliente, setMostrandoNuevoCliente] = useState(false)
  const [nuevoNombre, setNuevoNombre] = useState('')
  const [nuevoTelefono, setNuevoTelefono] = useState('')
  const [cargandoCliente, setCargandoCliente] = useState(false)
  const [errorCliente, setErrorCliente] = useState<string | null>(null)

  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const montoNum = parseFloat(monto) || 0

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
    if (!clienteId) { setError('Elegí un cliente.'); return }
    setError(null)
    setLoading(true)
    try {
      await createDeudaSimple({ cliente_id: clienteId, concepto: concepto.trim(), monto: montoNum, moneda, fecha: fecha || null, observaciones: observaciones.trim() || null })
      toast('success', 'Deuda registrada')
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
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Nueva deuda</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Deuda de un cliente con el negocio (sale de caja al registrarla)</p>
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

          {/* Razón / concepto */}
          <div><label style={LABEL_STYLE}>Razón / concepto</label><input type="text" value={concepto} onChange={(e) => setConcepto(e.target.value)} required placeholder="Ej: mercadería, adelanto, saldo…" style={INPUT_STYLE} /></div>

          {/* Monto + Moneda */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required placeholder="0,00" style={INPUT_STYLE} /></div>
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

          {/* Fecha */}
          <div><label style={LABEL_STYLE}>Fecha de la deuda <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional, hoy por defecto)</span></label><input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} style={INPUT_STYLE} /></div>

          {/* Observaciones */}
          <div><label style={LABEL_STYLE}>Observaciones <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} /></div>

          {montoNum > 0 && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.65rem 1rem', display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
              <span style={{ color: 'rgba(100,116,139,0.7)' }}>Sale de caja hoy</span>
              <span style={{ color: '#f87171', fontWeight: 700 }}>{fmtMonto(montoNum, moneda)}</span>
            </div>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading || mostrandoNuevoCliente} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || mostrandoNuevoCliente) ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Registrar deuda'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
