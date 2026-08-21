import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { compensar } from '../api/compensaciones'
import { getPasivos } from '../api/pasivos'
import { getClientes } from '../api/clientes'
import { btnBordered, btnSolid } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { Moneda, Pasivo } from '../types'

// Compensar: el cliente le transfiere a un acreedor del negocio y bajan las dos
// deudas, sin que la caja se mueva —esa plata nunca pasó por acá—.
//
// El mismo modal se abre desde los dos lados, porque según el día el operador
// piensa la operación de una forma o de la otra: a veces el disparador es que un
// cliente avisa que pagó (entra por Deudores) y a veces que está mirando lo que
// le debe a un proveedor (entra por Deudas). Lo único que cambia es cuál de los
// dos campos viene fijo.

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

function fmt(monto: number, moneda: Moneda): string {
  const n = monto.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return moneda === 'USD' ? `U$D ${n}` : `$ ${n}`
}

export interface CompensarCliente {
  id: string
  nombre: string
  /** Lo que debe en la moneda elegida; sirve para mostrar el tope. */
  saldo: number
  moneda: Moneda
}

export default function ModalCompensar({
  cliente,
  pasivo,
  onClose,
  onSuccess,
}: {
  /** Fijo cuando se entra desde Deudores; ausente cuando se entra desde Deudas. */
  cliente?: CompensarCliente
  /** Fijo cuando se entra desde Deudas; ausente cuando se entra desde Deudores. */
  pasivo?: Pasivo
  onClose: () => void
  onSuccess: () => void
}) {
  const [clienteId, setClienteId] = useState(cliente?.id ?? '')
  // El acreedor, no una deuda suya: la transferencia se reparte entre todas las
  // que se le deben, de la más vieja a la más nueva.
  const [acreedor, setAcreedor] = useState(pasivo?.acreedor ?? '')
  const [monedaPasivo, setMonedaPasivo] = useState<Moneda>(pasivo?.moneda ?? 'ARS')
  const [monedaDeuda, setMonedaDeuda] = useState<Moneda>(cliente?.moneda ?? 'ARS')
  const [monto, setMonto] = useState('')
  const [moneda, setMoneda] = useState<Moneda>(pasivo?.moneda ?? cliente?.moneda ?? 'ARS')
  // `pasivo` solo fija el acreedor y la moneda: la operación no es contra esa
  // deuda puntual sino contra todo lo que se le debe.
  const [cotizacion, setCotizacion] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  // Solo deudas vivas: no tiene sentido compensar contra algo ya saldado.
  // Siempre se cargan: aunque el acreedor venga fijo, hace falta saber cuánto se
  // le debe en total (puede tener varias deudas) para mostrar el efecto real.
  const { data: pasivos = [] } = useQuery({
    queryKey: ['pasivos', 'PENDIENTE'],
    queryFn: () => getPasivos('PENDIENTE'),
    staleTime: 30_000,
  })
  const { data: clientes = [] } = useQuery({
    queryKey: ['clientes'],
    queryFn: getClientes,
    staleTime: 60_000,
    enabled: !cliente,
  })

  // Todas las deudas vivas con ese acreedor en la moneda elegida: es contra ese
  // total que se imputa, no contra una sola.
  const deudasAcreedor = pasivos.filter(
    (p) => p.acreedor.trim().toLowerCase() === acreedor.trim().toLowerCase()
      && p.moneda === monedaPasivo,
  )
  const saldoPasivo = deudasAcreedor.reduce((t, p) => t + parseFloat(p.saldo_pendiente), 0)
  // Nombres únicos, para el selector: el operador elige a quién, no qué deuda.
  const acreedores = Array.from(new Set(pasivos.map((p) => p.acreedor))).sort()
  const montoNum = parseFloat(monto) || 0
  const cotizNum = parseFloat(cotizacion) || 0

  // Hace falta cotización si lo transferido no está en la moneda de alguna de
  // las dos deudas. La dicta siempre el operador: el sistema no la asume.
  const cruzaPasivo = moneda !== monedaPasivo
  const cruzaDeuda = moneda !== monedaDeuda
  const necesitaCotiz = cruzaPasivo || cruzaDeuda

  // Cuánto baja el pasivo, en su moneda. Transferirle más de lo que se le debe
  // lo dejaría a él debiendo: el backend lo rechaza, y acá se avisa antes.
  const equivalentePasivo =
    montoNum > 0
      ? cruzaPasivo
        ? cotizNum > 0
          ? monedaPasivo === 'USD'
            ? montoNum / cotizNum
            : montoNum * cotizNum
          : 0
        : montoNum
      : 0
  const excedePasivo = deudasAcreedor.length > 0 && equivalentePasivo - saldoPasivo > 0.01

  const invalido =
    loading ||
    !clienteId ||
    !acreedor ||
    deudasAcreedor.length === 0 ||
    montoNum <= 0 ||
    (necesitaCotiz && cotizNum <= 0) ||
    excedePasivo

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const r = await compensar({
        cliente_id: clienteId,
        acreedor,
        moneda_pasivo: monedaPasivo,
        moneda_deuda: monedaDeuda,
        monto: montoNum,
        moneda,
        cotizacion: necesitaCotiz ? cotizNum : null,
        observaciones: observaciones.trim() || null,
      })
      const extra = parseFloat(r.excedente) > 0 ? ` · quedan ${fmt(parseFloat(r.excedente), r.moneda)} a favor` : ''
      toast('success', `Compensado: bajaron las dos deudas${extra}`)
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '440px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Compensar deudas</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>
            El cliente le transfiere a quien vos le debés: bajan las dos y la caja no se mueve
          </p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          {/* Quién transfiere */}
          {cliente ? (
            <div>
              <label style={LABEL_STYLE}>Quien te debe y transfirió</label>
              <p style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-1)' }}>{cliente.nombre}</p>
              <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.7)' }}>
                Te debe {fmt(cliente.saldo, cliente.moneda)}
              </p>
            </div>
          ) : (
            <div>
              <label style={LABEL_STYLE}>Quien te debe y transfirió</label>
              <select value={clienteId} onChange={(e) => setClienteId(e.target.value)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="">— Elegí el cliente —</option>
                {clientes.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
              </select>
            </div>
          )}

          {/* A quién le transfirió */}
          {pasivo ? (
            <div>
              <label style={LABEL_STYLE}>A quién le transfirió (vos le debés)</label>
              <p style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-1)' }}>{pasivo.acreedor}</p>
              <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.7)' }}>
                Le debés {fmt(saldoPasivo, monedaPasivo)}
                {deudasAcreedor.length > 1 && ` en ${deudasAcreedor.length} deudas — se imputa de la más vieja a la más nueva`}
              </p>
            </div>
          ) : (
            <div>
              <label style={LABEL_STYLE}>A quién le transfirió (vos le debés)</label>
              <select value={acreedor} onChange={(e) => setAcreedor(e.target.value)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="">— Elegí el acreedor —</option>
                {acreedores.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              {acreedor && (
                <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.7)', marginTop: '0.25rem' }}>
                  Le debés {fmt(saldoPasivo, monedaPasivo)}
                  {deudasAcreedor.length > 1 && ` en ${deudasAcreedor.length} deudas — se imputa de la más vieja a la más nueva`}
                </p>
              )}
            </div>
          )}
          {/* Si le debés en las dos monedas hay que declarar contra cuál va: no
              se suman entre sí. */}
          {acreedor && new Set(pasivos.filter((p) => p.acreedor === acreedor).map((p) => p.moneda)).size > 1 && (
            <div>
              <label style={LABEL_STYLE}>Contra qué deuda con {acreedor}</label>
              <select value={monedaPasivo} onChange={(e) => setMonedaPasivo(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="ARS">Lo que le debés en pesos</option>
                <option value="USD">Lo que le debés en dólares</option>
              </select>
            </div>
          )}

          {/* Contra qué deuda del cliente imputa. ARS y USD no se suman. */}
          {!cliente && (
            <div>
              <label style={LABEL_STYLE}>Contra qué deuda del cliente</label>
              <select value={monedaDeuda} onChange={(e) => setMonedaDeuda(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="ARS">Su deuda en pesos</option>
                <option value="USD">Su deuda en dólares</option>
              </select>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={LABEL_STYLE}>Cuánto transfirió</label>
              <input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required autoFocus placeholder="0.00" style={INPUT_STYLE} />
            </div>
            <div>
              <label style={LABEL_STYLE}>Moneda</label>
              <select value={moneda} onChange={(e) => setMoneda(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </div>
          </div>

          {necesitaCotiz && (
            <div>
              <label style={LABEL_STYLE}>Cotización ($/USD)</label>
              <input type="number" step="0.0001" min="0.0001" value={cotizacion} onChange={(e) => setCotizacion(e.target.value)} required placeholder="0.00" style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.25rem' }}>
                Las deudas están en monedas distintas: la cotización la ponés vos.
              </p>
            </div>
          )}

          {deudasAcreedor.length > 0 && montoNum > 0 && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.9rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', fontFamily: FM, fontSize: '0.78rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'rgba(100,116,139,0.7)' }}>Le baja a {acreedor}</span>
                <span style={{ fontWeight: 700, color: 'var(--text-1)' }}>{fmt(equivalentePasivo, monedaPasivo)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'rgba(100,116,139,0.7)' }}>Le seguís debiendo</span>
                <span style={{ fontWeight: 700, color: 'var(--text-1)' }}>{fmt(Math.max(saldoPasivo - equivalentePasivo, 0), monedaPasivo)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid var(--bd-006)', paddingTop: '0.35rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.7)' }}>Sale de tu caja</span>
                <span style={{ fontWeight: 700, color: '#34d399' }}>Nada</span>
              </div>
            </div>
          )}

          {excedePasivo && (
            <p style={{ fontFamily: FM, fontSize: '0.72rem', color: '#f87171' }}>
              Le transferiría {fmt(equivalentePasivo, monedaPasivo)} y solo le debés{' '}
              {fmt(saldoPasivo, monedaPasivo)}
              {deudasAcreedor.length > 1 && ' sumando todas sus deudas'}. Si le mandó de
              más, esa diferencia es otra operación: cargala aparte.
            </p>
          )}

          <div>
            <label style={LABEL_STYLE}>Observaciones <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
            <textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} />
          </div>

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={invalido} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: invalido ? 0.6 : 1 }}>
              {loading ? 'Registrando…' : 'Compensar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
