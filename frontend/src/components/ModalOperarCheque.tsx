import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { venderCheque, fiarCheque } from '../api/cheques'
import { getClientes } from '../api/clientes'
import { useAuth } from '../auth/AuthContext'
import { fmtARS, fmtNroCheque } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import ClienteSelect from './ClienteSelect'
import SelectorMedioPago from './SelectorMedioPago'
import type { Cheque, MedioPago } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

export type ModoOperar = 'VENDER' | 'FIAR'

/**
 * Saca un cheque de la cartera: vendido (cobrado en el acto) o fiado (a cuenta).
 *
 * Son las dos salidas normales de un cheque, y hasta acá solo existían por
 * WhatsApp y —el fiado— desde la pantalla de Fiados, eligiendo el cheque de una
 * lista. Este modal opera **el cheque que se está mirando**, que es como se
 * decide en el mostrador.
 *
 * Un solo componente para las dos porque el formulario es el mismo (a quién, a
 * qué porcentaje) y lo que cambia es a dónde va la plata:
 *
 * - **Vender**: entra `monto · (1 − %venta)` a la caja elegida y la ganancia
 *   —`monto · (%compra − %venta)`— se reconoce en el acto. El cliente es
 *   opcional: la venta de mostrador no siempre tiene nombre.
 * - **Fiar**: no entra un peso ahora. Se abre una deuda del cliente por ese mismo
 *   neto, que se cobra después —por eso no hay medio de pago que elegir—, y el
 *   cliente es obligatorio: la deuda queda a nombre de alguien.
 *
 * Las dos transiciones son **terminales**: el cheque no vuelve a la cartera salvo
 * con "Revertir".
 */
export default function ModalOperarCheque({
  cheque,
  modo,
  onClose,
  onSuccess,
}: {
  cheque: Cheque
  modo: ModoOperar
  onClose: () => void
  onSuccess: () => void
}) {
  const { user } = useAuth()
  const toast = useToast()
  const vender = modo === 'VENDER'

  const [pct, setPct] = useState('')
  const [clienteId, setClienteId] = useState('')
  const [motivo, setMotivo] = useState('')
  const [medioPago, setMedioPago] = useState<MedioPago>('EFECTIVO')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: clientes = [] } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const nominal = parseFloat(cheque.monto)
  const pctCompra = parseFloat(cheque.porcentaje_compra)
  const pctNum = parseFloat(pct)
  const pctValido = !Number.isNaN(pctNum) && pctNum >= 0 && pctNum <= 100
  // Lo que el cliente pone por el cheque: el nominal menos el descuento pactado.
  // Vendido, eso entra a la caja; fiado, es el saldo que queda a cobrarle.
  const neto = pctValido ? nominal * (100 - pctNum) / 100 : null
  // Lo que costó comprarlo. La diferencia entre los dos porcentajes es la ganancia.
  const costo = nominal * (100 - pctCompra) / 100
  const ganancia = pctValido ? nominal * (pctCompra - pctNum) / 100 : null
  const aPerdida = ganancia !== null && ganancia < 0

  const faltaCliente = !vender && !clienteId
  const puedeEnviar = pctValido && !faltaCliente && !loading

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!puedeEnviar) return
    setError(null)
    setLoading(true)
    try {
      // El backend exige motivo no vacío en toda operación manual. Se completa
      // solo si el operador no escribió nada: es un dato de auditoría, no una
      // decisión de negocio, y pedirlo obligatorio le agregaría un paso a la
      // operación más frecuente del día. El bot hace lo mismo.
      const texto = motivo.trim() || (vender ? 'Venta registrada desde el panel' : 'Fiado registrado desde el panel')
      const operador_id = user?.username ?? 'panel-web'
      if (vender) {
        await venderCheque(cheque.id, {
          porcentaje_venta: pctNum,
          cliente_destino_id: clienteId || null,
          motivo: texto,
          operador_id,
          medio_pago: medioPago,
        })
        toast('success', 'Cheque vendido')
      } else {
        await fiarCheque(cheque.id, {
          cliente_destino_id: clienteId,
          porcentaje_venta: pctNum,
          motivo: texto,
          operador_id,
        })
        toast('success', 'Cheque fiado')
      }
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
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>
            {vender ? 'Vender cheque' : 'Fiar cheque'}
          </h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>
            {vender ? 'Sale de la cartera y entra la plata a la caja' : 'Sale de la cartera y queda como deuda del cliente'}
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

          {/* Qué cheque se está operando: se entra por su fila, pero el modal tapa
              la tabla y sin esto no queda a la vista cuál era. */}
          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem' }}>
            <p style={{ ...LABEL_STYLE, marginBottom: '0.35rem' }}>Cheque</p>
            <p style={{ fontFamily: FM, fontSize: '0.85rem', color: 'var(--text-1)', fontWeight: 600 }}>
              {fmtNroCheque(cheque.nro_cheque)}{cheque.banco ? ` — ${cheque.banco}` : ''}
            </p>
            <p style={{ fontFamily: FM, fontSize: '0.75rem', color: 'rgba(100,116,139,0.75)', marginTop: '0.2rem' }}>
              {fmtARS(nominal)} · comprado al {pctCompra.toFixed(2)}% ({fmtARS(costo)})
            </p>
          </div>

          <div>
            <label style={LABEL_STYLE}>% de {vender ? 'venta' : 'fiado'}</label>
            <input type="number" step="0.0001" min="0" max="100" value={pct} onChange={(e) => setPct(e.target.value)} placeholder="0,00" required autoFocus style={INPUT_STYLE} />
          </div>

          <ClienteSelect
            label={vender ? 'Cliente destino (a quién se lo vendí)' : 'Cliente (a quién se lo fío)'}
            value={clienteId}
            onChange={setClienteId}
            clientes={clientes}
            placeholder={vender ? '— Sin asignar —' : '— Elegir cliente —'}
          />
          {faltaCliente && (
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.75)', marginTop: '-0.5rem' }}>
              La deuda del fiado queda a nombre de un cliente: elegí cuál.
            </p>
          )}

          {/* Solo al vender: el fiado no mueve un peso hoy, así que no hay caja
              por la cual elegir. */}
          {vender && <SelectorMedioPago valor={medioPago} onChange={setMedioPago} label="¿Cómo te lo pagan?" />}

          {neto !== null && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.9rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', fontFamily: FM, fontSize: '0.78rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'rgba(100,116,139,0.7)' }}>Nominal</span>
                <span style={{ fontWeight: 600, color: 'var(--text-1)' }}>{fmtARS(nominal)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '0.3rem', borderTop: '1px solid var(--bd-006)' }}>
                <span style={{ fontWeight: 700, color: vender ? 'var(--text-1)' : '#fbbf24' }}>{vender ? 'Entra a caja' : 'Saldo a cobrarle'}</span>
                <span style={{ fontWeight: 700, color: vender ? 'var(--text-1)' : '#fbbf24' }}>{fmtARS(neto)}</span>
              </div>
              {/* Al fiar, el cheque todavía no deja ganancia: se reconoce cuando el
                  cliente paga. Mostrarla acá sería contar una plata que no entró. */}
              {vender && ganancia !== null && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'rgba(100,116,139,0.7)' }}>Ganancia</span>
                  <span style={{ fontWeight: 700, color: aPerdida ? '#f87171' : '#4ade80' }}>{fmtARS(ganancia)}</span>
                </div>
              )}
            </div>
          )}

          {/* Vender por debajo de lo que costó es una decisión posible —sacarse de
              encima un cheque dudoso—: avisa y deja seguir. */}
          {aPerdida && vender && (
            <p style={{ fontFamily: FM, fontSize: '0.72rem', color: '#fbbf24' }}>
              Lo estás vendiendo a menos de lo que costó ({fmtARS(costo)}): la operación queda a pérdida.
            </p>
          )}

          <div>
            <label style={LABEL_STYLE}>Motivo <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opc.)</span></label>
            <input type="text" value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder={vender ? 'Ej: se lo vendí a Benja' : 'Ej: se lo fío hasta fin de mes'} style={INPUT_STYLE} />
          </div>

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={!puedeEnviar} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: puedeEnviar ? 1 : 0.5, cursor: puedeEnviar ? 'pointer' : 'not-allowed' }}>
              {loading ? (vender ? 'Vendiendo…' : 'Fiando…') : (vender ? 'Vender' : 'Fiar')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
