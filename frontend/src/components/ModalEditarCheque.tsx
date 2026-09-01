import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { editarCheque } from '../api/cheques'
import { getClientes } from '../api/clientes'
import { fmtARS, fmtNroCheque } from '../lib/fmt'
import { btnBordered, btnSolid } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { Cheque, ChequeTipo } from '../types'
import ClienteSelect from './ClienteSelect'

/**
 * Corregir la carga de un cheque.
 *
 * Vive acá y no dentro de Cartera porque un cheque se corrige desde donde el
 * operador lo está mirando, y no siempre está en la cartera: uno **fiado** no
 * aparece en ninguna de las dos tablas de esa página, así que hasta que este
 * modal se compartió no había forma de tocarlo desde el panel (§1.c: los dos
 * e-cheq cargados como papel del 28/08 se terminaron corrigiendo por la API).
 */

const MODAL_BG = 'var(--modal)'
const FN = "'Bebas Neue', sans-serif"
const FM = "'Manrope', sans-serif"
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

export default function ModalEditarCheque({ cheque, onClose, onSuccess }: { cheque: Cheque; onClose: () => void; onSuccess: () => void }) {
  const tieneVenta = cheque.estado === 'VENDIDO' || cheque.estado === 'FIADO'
  // Puede venir vacío: un e-cheq cargado desde un comprobante de emisión no trae
  // número. Este modal es justamente donde se lo completa.
  const [nroCheque, setNroCheque] = useState(cheque.nro_cheque ?? '')
  const [banco, setBanco] = useState(cheque.banco ?? '')
  const [tipo, setTipo] = useState<ChequeTipo>(cheque.tipo)
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
        nro_cheque: nroCheque.trim() || null,
        banco: banco.trim() || null,
        tipo,
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
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{fmtNroCheque(cheque.nro_cheque)} · {cheque.estado.replace('_', ' ').toLowerCase()}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            {/* Sin `required`: un e-cheq puede estar cargado sin número, y este es
                el lugar donde se lo completa. Vacío se manda como null. */}
            <div><label style={LABEL_STYLE}>Nº de cheque {!cheque.nro_cheque && <span style={{ fontWeight: 400, color: '#fbbf24' }}>(falta)</span>}</label><input type="text" value={nroCheque} onChange={(e) => setNroCheque(e.target.value)} style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>Banco <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opc.)</span></label><input type="text" value={banco} onChange={(e) => setBanco(e.target.value)} style={INPUT_STYLE} /></div>
          </div>
          {/* El mismo selector que el alta. Sin esto no había forma de arreglar un
              e-cheq cargado como papel, que es el error más común de la carga por
              foto: el tipo es una etiqueta y no recalcula nada. */}
          <div>
            <label style={LABEL_STYLE}>Tipo</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
              {(['PAPEL', 'ELECTRONICO'] as ChequeTipo[]).map(t => (
                <button key={t} type="button" onClick={() => setTipo(t)}
                  style={{ ...INPUT_STYLE, cursor: 'pointer', textAlign: 'center', fontWeight: tipo === t ? 700 : 400,
                    color: tipo === t ? 'var(--text-1)' : 'rgba(100,116,139,0.7)',
                    borderColor: tipo === t ? '#a78bfa55' : 'var(--bd-012)',
                    background: tipo === t ? '#a78bfa14' : 'var(--bg)' }}>
                  {t === 'PAPEL' ? 'Papel' : 'E-cheq'}
                </button>
              ))}
            </div>
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
