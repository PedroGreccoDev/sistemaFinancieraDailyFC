import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getPasivos, createPasivo, editarPasivo,
  pagarAcreedor, cancelarAcreedorConCheque,
} from '../api/pasivos'
import { getChequeCartera } from '../api/cheques'
import { fmtARS, fmtUSD, fmtDate } from '../lib/fmt'
import { chip, btnSolid, btnBordered, btnFlat } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconPlus, IconRefresh } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import type { Cheque, MedioPago, Moneda, Pasivo, PasivoEstado } from '../types'
import DropdownFilter from '../components/DropdownFilter'
import ModalEliminar from '../components/ModalEliminar'
import ModalCompensar from '../components/ModalCompensar'

// La lista es por ACREEDOR, no por deuda: el filtro decide qué deudas se traen,
// pero la pantalla siempre las agrupa bajo quien las cobra.
type Filtro = 'todos' | PasivoEstado

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

function EstadoBadge({ estado }: { estado: PasivoEstado }) {
  const isPending = estado === 'PENDIENTE'
  return (
    <span style={chip(isPending ? 'warning' : 'success')}>
      {isPending ? 'Pendiente' : 'Cancelada'}
    </span>
  )
}

function fmtMoneda(monto: string | number, moneda: Moneda): string {
  return moneda === 'USD' ? fmtUSD(monto) : fmtARS(monto)
}

// ── Agrupación por acreedor ───────────────────────────────────────────
//
// `acreedor` es texto libre y no un cliente con id (§5), así que el que agrupa
// es el nombre. **El criterio tiene que ser el mismo que el del backend**
// (`cargar_pasivos_acreedor`: trim + case-insensitive) o la tarjeta mostraría un
// total y el botón pagaría otro.

function claveAcreedor(nombre: string): string {
  return nombre.trim().toLowerCase()
}

interface GrupoAcreedor {
  clave: string
  /** El nombre tal cual se escribió en la deuda más vieja: es el que viaja al pagar. */
  nombre: string
  /** Todas sus deudas, de la más vieja a la más nueva: el mismo orden en que el
   *  pago las va a imputar. */
  deudas: Pasivo[]
  pendientes: number
  saldoARS: number
  saldoUSD: number
}

function agrupar(pasivos: Pasivo[]): GrupoAcreedor[] {
  const porAcreedor = new Map<string, Pasivo[]>()
  for (const p of pasivos) {
    const clave = claveAcreedor(p.acreedor)
    const lista = porAcreedor.get(clave) ?? []
    lista.push(p)
    porAcreedor.set(clave, lista)
  }

  const grupos = [...porAcreedor.entries()].map(([clave, lista]) => {
    // Por `created_at`: un pasivo no tiene fecha de origen propia más allá de
    // cuándo se cargó, y el vencimiento no sirve —una deuda que vence antes no
    // es más vieja—. Es el orden que usa el reparto del backend.
    const ordenadas = [...lista].sort((a, b) => a.created_at.localeCompare(b.created_at))
    const pendientes = ordenadas.filter((p) => p.estado === 'PENDIENTE')
    const saldoDe = (m: Moneda) =>
      pendientes.filter((p) => p.moneda === m).reduce((acc, p) => acc + parseFloat(p.saldo_pendiente), 0)
    return {
      clave,
      nombre: ordenadas[0].acreedor,
      deudas: ordenadas,
      pendientes: pendientes.length,
      saldoARS: saldoDe('ARS'),
      saldoUSD: saldoDe('USD'),
    }
  })

  // Primero a quien se le debe algo; entre iguales, alfabético.
  grupos.sort((a, b) => (b.pendientes > 0 ? 1 : 0) - (a.pendientes > 0 ? 1 : 0) || a.nombre.localeCompare(b.nombre))
  return grupos
}

/** Lo que se le debe a alguien en una moneda: el objetivo de los botones de la tarjeta. */
interface DeudaAcreedor {
  nombre: string
  moneda: Moneda
  saldo: number
  operaciones: number
  /** Primera cotización cross-moneda ya usada con este acreedor, como default editable. */
  cotizacionPrevia: string | null
}

// ── Modal nueva deuda ─────────────────────────────────────────────────

function ModalNuevaDeuda({ acreedorFijo, onClose, onSuccess }: { acreedorFijo?: string; onClose: () => void; onSuccess: () => void }) {
  const [acreedor, setAcreedor] = useState(acreedorFijo ?? '')
  const [concepto, setConcepto] = useState('')
  const [monto, setMonto] = useState('')
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [fechaVenc, setFechaVenc] = useState('')
  const [observaciones, setObservaciones] = useState('')
  // Le prestaron plata al negocio: además de la deuda, el efectivo entró al cajón.
  const [entroPlata, setEntroPlata] = useState(false)
  const [fechaIngreso, setFechaIngreso] = useState('')
  // Solo si le prestaron dólares: costo con el que entran al stock vendible.
  const [cotizacionIngreso, setCotizacionIngreso] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const pideCotizacion = entroPlata && moneda === 'USD'

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await createPasivo({
        acreedor: acreedor.trim(),
        concepto: concepto.trim(),
        monto: parseFloat(monto),
        moneda,
        fecha_vencimiento: fechaVenc || null,
        observaciones: observaciones.trim() || null,
        // Sin la marca no viaja el campo: el backend lo lee como deuda que no
        // movió la caja, que es el caso normal.
        ...(entroPlata ? {
          ingreso_caja: true,
          fecha_ingreso: fechaIngreso || null,
          // Sin esto los dólares figuran en la caja pero no se pueden vender.
          ...(moneda === 'USD' ? { cotizacion_ingreso_usd: parseFloat(cotizacionIngreso) } : {}),
        } : {}),
      })
      toast('success', entroPlata ? 'Deuda registrada y plata ingresada a caja' : 'Deuda registrada')
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>{acreedorFijo ? 'Sumar deuda' : 'Nueva deuda'}</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{acreedorFijo ? `Otra deuda con ${acreedorFijo}` : entroPlata ? 'Anota la deuda y suma la plata que entró a la caja' : 'Registrar una deuda del negocio (no mueve la caja)'}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div>
            <label style={LABEL_STYLE}>A quién le debo</label>
            <input type="text" value={acreedor} onChange={(e) => setAcreedor(e.target.value)} required readOnly={!!acreedorFijo} style={{ ...INPUT_STYLE, ...(acreedorFijo ? { opacity: 0.6, cursor: 'not-allowed' } : {}) }} />
            {/* Es una deuda NUEVA, no una edición de las que ya tiene: cada una
                conserva su fecha y su propia línea de caja. */}
            {acreedorFijo && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.3rem' }}>Se agrega a lo que ya le debés; las deudas anteriores no se tocan.</p>}
          </div>
          <div><label style={LABEL_STYLE}>Concepto / razón</label><input type="text" value={concepto} onChange={(e) => setConcepto(e.target.value)} required style={INPUT_STYLE} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>Moneda</label><select value={moneda} onChange={(e) => setMoneda(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}><option value="ARS">ARS</option><option value="USD">USD</option></select></div>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', fontFamily: FM, fontSize: '0.76rem', color: 'var(--text-2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={entroPlata} onChange={(e) => { setEntroPlata(e.target.checked); if (!e.target.checked) setFechaIngreso('') }} style={{ cursor: 'pointer' }} />
            Me prestaron la plata (entró a la caja)
          </label>
          {entroPlata && (
            <div>
              <label style={LABEL_STYLE}>Día que entró <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(vacío = hoy)</span></label>
              <input type="date" value={fechaIngreso} onChange={(e) => setFechaIngreso(e.target.value)} style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.3rem' }}>Suma {monto ? fmtMoneda(monto, moneda) : 'el monto'} a la caja {moneda} de ese día. Marcala solo si el efectivo entró de verdad.</p>
            </div>
          )}
          {pideCotizacion && (
            <div>
              <label style={LABEL_STYLE}>¿A cuánto tomás el dólar? <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>($ por USD)</span></label>
              <input type="number" step="0.01" min="0.01" value={cotizacionIngreso} onChange={(e) => setCotizacionIngreso(e.target.value)} required placeholder="1250.00" style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.3rem' }}>Es el costo con el que esos dólares entran al stock: contra eso se calcula la ganancia si los vendés. Sin esto no se pueden vender.</p>
            </div>
          )}
          <div><label style={LABEL_STYLE}>Vencimiento <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><input type="date" value={fechaVenc} onChange={(e) => setFechaVenc(e.target.value)} style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Observaciones <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} /></div>
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: loading ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Registrar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal editar deuda ────────────────────────────────────────────────

function ModalEditarDeuda({ pasivo, onClose, onSuccess }: { pasivo: Pasivo; onClose: () => void; onSuccess: () => void }) {
  const [acreedor, setAcreedor] = useState(pasivo.acreedor)
  const [concepto, setConcepto] = useState(pasivo.concepto)
  const [monto, setMonto] = useState(pasivo.monto)
  const [moneda, setMoneda] = useState<Moneda>(pasivo.moneda)
  const [fechaVenc, setFechaVenc] = useState(pasivo.fecha_vencimiento ?? '')
  const [observaciones, setObservaciones] = useState(pasivo.observaciones ?? '')
  const [entroPlata, setEntroPlata] = useState(pasivo.ingreso_caja)
  const [fechaIngreso, setFechaIngreso] = useState(pasivo.fecha_ingreso ?? '')
  const [cotizacionIngreso, setCotizacionIngreso] = useState(pasivo.cotizacion_ingreso_usd ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  // Los campos que mueven plata se bloquean si la deuda está cancelada o ya tuvo
  // pagos parciales (saldo distinto del monto original). Coincide con el backend.
  const tienePagos = parseFloat(pasivo.saldo_pendiente) !== parseFloat(pasivo.monto)
  const dineroBloqueado = pasivo.estado === 'CANCELADA' || tienePagos

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await editarPasivo(pasivo.id, {
        acreedor: acreedor.trim(),
        concepto: concepto.trim(),
        fecha_vencimiento: fechaVenc || null,
        observaciones: observaciones.trim() || null,
        ...(dineroBloqueado ? {} : { monto: parseFloat(monto), moneda }),
        // La línea de caja del alta se rehace sola en el backend; los pagos ya
        // hechos no se tocan, así que esto se puede corregir aunque haya pagos.
        ingreso_caja: entroPlata,
        ...(entroPlata ? {
          fecha_ingreso: fechaIngreso || null,
          ...(moneda === 'USD' ? { cotizacion_ingreso_usd: parseFloat(cotizacionIngreso) } : {}),
        } : {}),
      })
      toast('success', 'Deuda actualizada')
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Editar deuda</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Corregir la carga de la deuda</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div><label style={LABEL_STYLE}>A quién le debo</label><input type="text" value={acreedor} onChange={(e) => setAcreedor(e.target.value)} required style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Concepto / razón</label><input type="text" value={concepto} onChange={(e) => setConcepto(e.target.value)} required style={INPUT_STYLE} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required disabled={dineroBloqueado} style={{ ...INPUT_STYLE, opacity: dineroBloqueado ? 0.5 : 1, cursor: dineroBloqueado ? 'not-allowed' : 'auto' }} /></div>
            <div><label style={LABEL_STYLE}>Moneda</label><select value={moneda} onChange={(e) => setMoneda(e.target.value as Moneda)} disabled={dineroBloqueado} style={{ ...INPUT_STYLE, cursor: dineroBloqueado ? 'not-allowed' : 'pointer', opacity: dineroBloqueado ? 0.5 : 1 }}><option value="ARS">ARS</option><option value="USD">USD</option></select></div>
          </div>
          {dineroBloqueado && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(251,191,36,0.85)', marginTop: '-0.4rem' }}>Monto y moneda no se pueden cambiar: la deuda está cancelada o ya tiene pagos. Para deberle más, usá "Sumar deuda" en su fila.</p>}
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', fontFamily: FM, fontSize: '0.76rem', color: 'var(--text-2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={entroPlata} onChange={(e) => { setEntroPlata(e.target.checked); if (!e.target.checked) setFechaIngreso('') }} style={{ cursor: 'pointer' }} />
            Me prestaron la plata (entró a la caja)
          </label>
          {entroPlata && (
            <div>
              <label style={LABEL_STYLE}>Día que entró <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(vacío = el día del alta)</span></label>
              <input type="date" value={fechaIngreso} onChange={(e) => setFechaIngreso(e.target.value)} style={INPUT_STYLE} />
            </div>
          )}
          {entroPlata && moneda === 'USD' && (
            <div>
              <label style={LABEL_STYLE}>¿A cuánto tomás el dólar? <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>($ por USD)</span></label>
              <input type="number" step="0.01" min="0.01" value={cotizacionIngreso} onChange={(e) => setCotizacionIngreso(e.target.value)} required style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.3rem' }}>Costo con el que esos dólares entran al stock. Si ya vendiste una parte, no se puede cambiar.</p>
            </div>
          )}
          {entroPlata !== pasivo.ingreso_caja && (
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(251,191,36,0.85)', marginTop: '-0.4rem' }}>
              {entroPlata
                ? `Al guardar, ${fmtMoneda(pasivo.monto, pasivo.moneda)} se suman a la caja ${pasivo.moneda}.`
                : `Al guardar, se quita de la caja el ingreso de ${fmtMoneda(pasivo.monto, pasivo.moneda)}.`}
            </p>
          )}
          <div><label style={LABEL_STYLE}>Vencimiento <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><input type="date" value={fechaVenc} onChange={(e) => setFechaVenc(e.target.value)} style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Observaciones <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} /></div>
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

// ── Modal pagar al acreedor (efectivo / transferencia) ────────────────
//
// El pago no se dirige a una deuda: se imputa de la más vieja a la más nueva
// cruzando todas las que se le tienen en esa moneda. Por eso lo que viaja es el
// nombre y no un id.

function ModalPagarAcreedor({ deuda, onClose, onSuccess }: { deuda: DeudaAcreedor; onClose: () => void; onSuccess: () => void }) {
  const [monto, setMonto] = useState('')
  const [monedaPago, setMonedaPago] = useState<Moneda>(deuda.moneda)
  const [medioPago, setMedioPago] = useState<MedioPago>('EFECTIVO')
  const [cotizacion, setCotizacion] = useState(deuda.cotizacionPrevia ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

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
  const cancelaTotal = equivalente !== null && Math.abs(equivalente - deuda.saldo) < 0.01
  const superaSaldo = equivalente !== null && equivalente - deuda.saldo >= 0.01
  const faltaCotiz = cross && cotizNum <= 0
  const puedeEnviar = montoNum > 0 && !faltaCotiz && equivalente !== null && !superaSaldo

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const r = await pagarAcreedor({
        acreedor: deuda.nombre,
        moneda_deuda: deuda.moneda,
        monto_pagado: montoNum,
        moneda_pago: monedaPago,
        medio_pago: medioPago,
        cotizacion: cross ? cotizNum : null,
      })
      toast('success', r.cancelados > 0
        ? `Pago registrado — ${r.cancelados} deuda(s) saldada(s)`
        : 'Pago registrado')
      onSuccess()
    }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '380px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)' }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Pagar deuda</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{deuda.nombre}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', padding: '0.75rem 1rem', borderRadius: 'var(--r-md)', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
              <span style={{ color: 'rgba(100,116,139,0.65)' }}>Le debés en {deuda.moneda}</span>
              <span style={{ fontWeight: 700, color: '#f87171' }}>{fmtMoneda(deuda.saldo, deuda.moneda)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.72rem' }}>
              <span style={{ color: 'rgba(100,116,139,0.5)' }}>En {deuda.operaciones} deuda{deuda.operaciones > 1 ? 's' : ''}</span>
              <span style={{ color: 'rgba(100,116,139,0.5)' }}>se salda de la más vieja</span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <div style={{ flex: 1 }}>
              <label style={LABEL_STYLE}>Medio</label>
              <select value={medioPago} onChange={(e) => setMedioPago(e.target.value as MedioPago)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="EFECTIVO">Efectivo</option>
                <option value="TRANSFERENCIA">Transferencia</option>
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={LABEL_STYLE}>Moneda de pago</label>
              <select value={monedaPago} onChange={(e) => setMonedaPago(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="ARS">ARS (pesos)</option>
                <option value="USD">USD</option>
              </select>
            </div>
          </div>

          <div>
            <label style={LABEL_STYLE}>Monto a pagar ({monedaPago})</label>
            <input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required style={INPUT_STYLE} />
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
              {cancelaTotal ? 'Cancela todo lo que le debés' : `Le seguirías debiendo: ${fmtMoneda(deuda.saldo - equivalente, deuda.moneda)}`}
            </p>
          )}
          {superaSaldo && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#f87171' }}>El pago equivale a {fmtMoneda(equivalente!, deuda.moneda)} y supera lo que le debés</p>}
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

// ── Modal pagar con cheque de cartera ─────────────────────────────────
//
// El cheque es un instrumento en pesos: solo entra contra las deudas en ARS.

function ModalChequeAcreedor({ deuda, onClose, onSuccess }: { deuda: DeudaAcreedor; onClose: () => void; onSuccess: () => void }) {
  const [chequeSeleccionado, setChequeSeleccionado] = useState<Cheque | null>(null)
  const [porcentajeVenta, setPorcentajeVenta] = useState('')
  const [vueltoModo, setVueltoModo] = useState<'SALDAR_EFECTIVO' | 'QUEDA_DEBIENDO'>('SALDAR_EFECTIVO')
  const [operadorId, setOperadorId] = useState('')
  const [motivo, setMotivo] = useState(`Cancelación de deuda con ${deuda.nombre}`)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const { data: cheques, isLoading: loadingCheques } = useQuery({ queryKey: ['cheques', 'cartera'], queryFn: getChequeCartera })

  function handleSelectCheque(id: string) {
    const found = cheques?.find((c) => c.id === id) ?? null
    setChequeSeleccionado(found)
    if (found) setPorcentajeVenta(found.porcentaje_compra)
  }

  const montoNum = chequeSeleccionado ? parseFloat(chequeSeleccionado.monto) : 0
  const pctNum = parseFloat(porcentajeVenta) || 0
  const valorNeto = montoNum > 0 ? parseFloat((montoNum * (100 - pctNum) / 100).toFixed(2)) : null
  const diferencia = valorNeto !== null ? parseFloat((valorNeto - deuda.saldo).toFixed(2)) : null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!chequeSeleccionado) return
    setError(null)
    setLoading(true)
    try {
      const r = await cancelarAcreedorConCheque({
        acreedor: deuda.nombre,
        cheque_id: chequeSeleccionado.id,
        porcentaje_venta: pctNum,
        operador_id: operadorId.trim(),
        motivo: motivo.trim(),
        vuelto_modo: diferencia !== null && diferencia > 0 ? vueltoModo : null,
      })
      toast('success', r.cancelados > 0
        ? `Pagado con cheque — ${r.cancelados} deuda(s) saldada(s)`
        : 'Pagado con cheque')
      onSuccess()
    }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Pagar con cheque</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Entregar un cheque de cartera al acreedor</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', padding: '0.75rem 1rem', borderRadius: 'var(--r-md)', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            {[
              { label: 'Acreedor', value: deuda.nombre, color: 'var(--text-1)' },
              { label: `Le debés (${deuda.operaciones} deuda${deuda.operaciones > 1 ? 's' : ''})`, value: fmtARS(deuda.saldo), color: '#f87171' },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.65)' }}>{label}</span>
                <span style={{ fontWeight: 700, color }}>{value}</span>
              </div>
            ))}
          </div>

          <div>
            <label style={LABEL_STYLE}>Cheque a entregar</label>
            {loadingCheques ? <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.5)' }}>Cargando cheques…</p>
              : !cheques || cheques.length === 0 ? <p style={{ fontFamily: FM, fontSize: '0.78rem', color: '#fbbf24' }}>No hay cheques en cartera.</p>
              : <select value={chequeSeleccionado?.id ?? ''} onChange={(e) => handleSelectCheque(e.target.value)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                  <option value="">— Seleccioná un cheque —</option>
                  {cheques.map((c) => <option key={c.id} value={c.id}>#{c.nro_cheque}{c.banco ? ` · ${c.banco}` : ''} — {fmtARS(c.monto)}{c.fecha_pago ? ` — vence ${fmtDate(c.fecha_pago)}` : ''}</option>)}
                </select>}
          </div>

          <div>
            <label style={LABEL_STYLE}>% venta aplicado</label>
            <input type="number" step="0.0001" min="0" max="100" value={porcentajeVenta} onChange={(e) => setPorcentajeVenta(e.target.value)} required style={INPUT_STYLE} />
            {chequeSeleccionado && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.5)', marginTop: '0.25rem' }}>% compra original: {chequeSeleccionado.porcentaje_compra}%</p>}
          </div>

          {chequeSeleccionado && valorNeto !== null && diferencia !== null && (
            <div style={{ background: diferencia >= 0 ? 'rgba(74,222,128,0.06)' : 'rgba(251,191,36,0.06)', border: `1px solid ${diferencia >= 0 ? 'rgba(74,222,128,0.2)' : 'rgba(251,191,36,0.2)'}`, padding: '0.75rem 1rem', borderRadius: 'var(--r-md)', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {[
                { label: 'Nominal cheque', value: fmtARS(chequeSeleccionado.monto) },
                { label: `Valor neto (${pctNum}%)`, value: fmtARS(valorNeto) },
              ].map(({ label, value }) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                  <span style={{ color: 'rgba(100,116,139,0.65)' }}>{label}</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-1)' }}>{value}</span>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.3rem', borderTop: '1px solid var(--bd-006)' }}>
                <span style={{ fontWeight: 700, color: diferencia >= 0 ? '#4ade80' : '#fbbf24' }}>{diferencia >= 0 ? 'Cancela todo lo que le debés' : 'Le seguirías debiendo'}</span>
                <span style={{ fontWeight: 700, color: diferencia >= 0 ? '#4ade80' : '#fbbf24' }}>{diferencia >= 0 ? (diferencia > 0 ? `+${fmtARS(diferencia)}` : '✓') : fmtARS(-diferencia)}</span>
              </div>
            </div>
          )}

          {/* Vuelto: el cheque cubre de más → el operador decide qué hacer con la diferencia */}
          {diferencia !== null && diferencia > 0 && (
            <div>
              <label style={LABEL_STYLE}>Vuelto a favor del cliente ({fmtARS(diferencia)})</label>
              <select value={vueltoModo} onChange={(e) => setVueltoModo(e.target.value as 'SALDAR_EFECTIVO' | 'QUEDA_DEBIENDO')} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                <option value="SALDAR_EFECTIVO">Le pago el vuelto (efectivo/transferencia)</option>
                <option value="QUEDA_DEBIENDO">Queda como deuda a favor del cliente</option>
              </select>
            </div>
          )}

          <div><label style={LABEL_STYLE}>Operador</label><input type="text" value={operadorId} onChange={(e) => setOperadorId(e.target.value)} required placeholder="Nombre del operador" style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Motivo</label><input type="text" value={motivo} onChange={(e) => setMotivo(e.target.value)} required style={INPUT_STYLE} /></div>

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Volver</button>
            <button type="submit" disabled={loading || !chequeSeleccionado || !cheques || cheques.length === 0} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || !chequeSeleccionado) ? 0.5 : 1 }}>{loading ? 'Registrando…' : 'Confirmar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Fila de un acreedor ───────────────────────────────────────────────
//
// Una fila por acreedor, igual que Deudores: el resumen de lo que se le debe y,
// desplegando, el detalle de dónde sale ese total.

const TH: React.CSSProperties = { fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)', whiteSpace: 'nowrap' }
const TD: React.CSSProperties = { fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)' }
const TD_SUB: React.CSSProperties = { ...TD, fontSize: '0.76rem', padding: '0.45rem 1rem', borderBottom: '1px solid var(--ov-002)' }

/** Lo que se le debe a alguien en una moneda: el objetivo de los botones de pago. */
function objetivoDe(grupo: GrupoAcreedor, moneda: Moneda): DeudaAcreedor {
  const deLaMoneda = grupo.deudas.filter((p) => p.estado === 'PENDIENTE' && p.moneda === moneda)
  return {
    nombre: grupo.nombre,
    moneda,
    saldo: moneda === 'ARS' ? grupo.saldoARS : grupo.saldoUSD,
    operaciones: deLaMoneda.length,
    cotizacionPrevia: deLaMoneda.find((p) => p.cotizacion_pago)?.cotizacion_pago ?? null,
  }
}

/** La deuda más vieja de esa moneda: la que se compensa contra un cliente. */
function primeraPendiente(grupo: GrupoAcreedor, moneda: Moneda): Pasivo | undefined {
  return grupo.deudas.find((p) => p.estado === 'PENDIENTE' && p.moneda === moneda)
}

// Los botones que saldan un total. El operador no elige contra qué deuda va la
// plata —el backend la imputa de la más vieja a la más nueva—, así que viven por
// acreedor y moneda, nunca en el renglón de una deuda.
function AccionesMoneda({
  grupo, moneda, onPagar, onCheque, onCompensar,
}: {
  grupo: GrupoAcreedor
  moneda: Moneda
  onPagar: (d: DeudaAcreedor) => void
  onCheque: (d: DeudaAcreedor) => void
  onCompensar: (p: Pasivo) => void
}) {
  const objetivo = objetivoDe(grupo, moneda)
  const primera = primeraPendiente(grupo, moneda)
  const color = moneda === 'USD' ? '#38bdf8' : '#fbbf24'
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap' }}>
      <div>
        <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>
          Total {moneda} · {objetivo.operaciones} deuda{objetivo.operaciones > 1 ? 's' : ''}
        </p>
        <p style={{ fontFamily: FN, fontSize: '1.25rem', color, lineHeight: 1.1, overflowWrap: 'anywhere' }}>{fmtMoneda(objetivo.saldo, moneda)}</p>
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <button onClick={() => onPagar(objetivo)} style={{ ...btnSolid('success'), fontSize: '0.72rem', padding: '0.4rem 0.9rem' }}>Pagar</button>
        {/* Un cheque es un instrumento en pesos: contra una deuda en dólares no hay
            con qué imputarlo sin una cotización que nadie dictó. */}
        {moneda === 'ARS' && (
          <button onClick={() => onCheque(objetivo)} style={{ ...btnBordered('primary'), fontSize: '0.72rem', padding: '0.4rem 0.8rem' }}>Con cheque</button>
        )}
        {primera && (
          <button onClick={() => onCompensar(primera)} title="Se la cubrió un cliente que te debe" style={{ ...btnBordered('neutral'), fontSize: '0.72rem', padding: '0.4rem 0.8rem' }}>Compensar</button>
        )}
      </div>
    </div>
  )
}

/** El renglón de una deuda suelta dentro del detalle de un acreedor. */
function DetalleDeuda({ pasivo }: { pasivo: Pasivo }) {
  return (
    <>
      {pasivo.concepto}
      {pasivo.ingreso_caja && <span title={`La plata entró a la caja el ${fmtDate(pasivo.fecha_ingreso ?? '')}`} style={{ color: 'rgba(52,211,153,0.85)', marginLeft: '0.35rem' }}>· entró a caja</span>}
      {pasivo.fecha_vencimiento && <span style={{ color: 'rgba(100,116,139,0.5)', marginLeft: '0.35rem' }}>· vence {fmtDate(pasivo.fecha_vencimiento)}</span>}
    </>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function Pasivos() {
  const [filtro, setFiltro] = useState<Filtro>('PENDIENTE')
  const [pagando, setPagando] = useState<DeudaAcreedor | null>(null)
  const [conCheque, setConCheque] = useState<DeudaAcreedor | null>(null)
  const [pasivoEditar, setPasivoEditar] = useState<Pasivo | null>(null)
  const [pasivoEliminar, setPasivoEliminar] = useState<Pasivo | null>(null)
  const [pasivoCompensar, setPasivoCompensar] = useState<Pasivo | null>(null)
  // `''` = alta suelta (el operador tipea el acreedor); un nombre = "Sumar deuda"
  // desde la tarjeta de ese acreedor.
  const [creando, setCreando] = useState<string | null>(null)
  const [expandidos, setExpandidos] = useState<Set<string>>(new Set())
  const queryClient = useQueryClient()

  function toggle(clave: string) {
    setExpandidos((prev) => {
      const siguiente = new Set(prev)
      if (siguiente.has(clave)) siguiente.delete(clave)
      else siguiente.add(clave)
      return siguiente
    })
  }

  const estado = filtro === 'todos' ? undefined : filtro as PasivoEstado
  const { data: pasivos, isLoading, error, refetch } = useQuery({
    queryKey: ['pasivos', filtro],
    queryFn: () => getPasivos(estado),
    refetchInterval: 30_000,
  })

  const grupos = useMemo(() => agrupar(pasivos ?? []), [pasivos])

  const pendientes = pasivos?.filter((p) => p.estado === 'PENDIENTE') ?? []
  const totalARS = pendientes.filter((p) => p.moneda === 'ARS').reduce((acc, p) => acc + parseFloat(p.saldo_pendiente), 0)
  const totalUSD = pendientes.filter((p) => p.moneda === 'USD').reduce((acc, p) => acc + parseFloat(p.saldo_pendiente), 0)
  const conSaldo = grupos.filter((g) => g.pendientes > 0).length

  function invalidar() {
    queryClient.invalidateQueries({ queryKey: ['pasivos'] })
    queryClient.invalidateQueries({ queryKey: ['cheques'] })
    // Pagar y anular mueven líneas de caja: el reporte y el feed quedan desactualizados.
    queryClient.invalidateQueries({ queryKey: ['reporte-caja'] })
    queryClient.invalidateQueries({ queryKey: ['reporte'] })
    queryClient.invalidateQueries({ queryKey: ['movimientos-unificados'] })
  }

  function handleSuccess() {
    setPagando(null); setConCheque(null); setPasivoEditar(null)
    setPasivoEliminar(null); setCreando(null)
    invalidar()
  }

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Deudas</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Lo que el negocio le debe a cada uno: compras a deber, plata prestada y vueltos, en una sola cuenta</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button onClick={() => setCreando('')} style={{ ...btnSolid('primary'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', padding: '0.45rem 0.875rem' }}><IconPlus size={15} />Nueva deuda</button>
          <button onClick={() => refetch()} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}><IconRefresh size={14} />Actualizar</button>
        </div>
      </div>

      {/* KPIs */}
      {filtro !== 'CANCELADA' && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
          {[
            { label: 'Saldo pendiente ARS', value: fmtARS(totalARS) },
            { label: 'Saldo pendiente USD', value: fmtUSD(totalUSD) },
          ].map(({ label, value }) => (
            <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
              <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color: '#f87171', letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
              <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{conSaldo} acreedor(es)</p>
            </div>
          ))}
        </div>
      )}

      {/* Filtros */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '0.75rem', marginBottom: '1rem' }}>
        <DropdownFilter
          label="Estado"
          value={filtro}
          options={[
            { value: 'todos' as Filtro, label: 'Todos' },
            { value: 'PENDIENTE' as Filtro, label: 'Pendientes' },
            { value: 'CANCELADA' as Filtro, label: 'Cancelados' },
          ]}
          onChange={(v) => setFiltro(v as Filtro)}
        />
      </div>

      {/* Lista — una fila por acreedor; el detalle de sus deudas se despliega */}
      <div style={{ ...CARD, overflow: 'hidden' }}>
        {isLoading && <SkeletonRows rows={6} />}
        {error && <div style={{ padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar las deudas.</div>}
        {!isLoading && !error && grupos.length === 0 && (
          <div style={{ padding: '3rem', textAlign: 'center' }}>
            <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>✅</p>
            <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>Sin deudas registradas</p>
          </div>
        )}
        {!isLoading && !error && grupos.length > 0 && (
          <>
            {/* Mobile: tarjetas por acreedor */}
            <div className="sm:hidden">
              {grupos.map((g) => (
                <div key={`m-${g.clave}`} style={{ borderBottom: '1px solid var(--ov-004)' }}>
                  <div style={{ padding: '0.85rem 1rem' }}>
                    <button type="button" onClick={() => toggle(g.clave)}
                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', width: '100%', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left' }}>
                      <span style={{ minWidth: 0 }}>
                        <span style={{ display: 'block', fontFamily: FM, fontSize: '0.86rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word' }}>
                          <span style={{ color: 'rgba(100,116,139,0.6)', marginRight: '0.35rem' }}>{expandidos.has(g.clave) ? '▾' : '▸'}</span>
                          {g.nombre}
                        </span>
                        <span style={{ display: 'block', fontFamily: FM, fontSize: '0.7rem', color: 'rgba(148,163,184,0.7)', marginTop: '1px' }}>
                          {g.pendientes > 0 ? `${g.pendientes} pendiente(s)` : 'Sin saldo'} · {g.deudas.length} en total
                        </span>
                      </span>
                      <span style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                        {g.saldoARS > 0.009 && <span style={{ display: 'block', fontFamily: FM, fontSize: '0.9rem', fontWeight: 700, color: '#fbbf24' }}>{fmtARS(g.saldoARS)}</span>}
                        {g.saldoUSD > 0.009 && <span style={{ display: 'block', fontFamily: FM, fontSize: '0.9rem', fontWeight: 700, color: '#38bdf8' }}>{fmtUSD(g.saldoUSD)}</span>}
                        {g.pendientes === 0 && <span style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.5)' }}>—</span>}
                      </span>
                    </button>

                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.65rem', flexWrap: 'wrap' }}>
                      <button onClick={() => setCreando(g.nombre)} style={{ ...btnBordered('neutral'), flex: '1 1 auto', fontSize: '0.72rem', padding: '0.4rem' }}>+ Sumar deuda</button>
                      {g.saldoARS > 0.009 && <button onClick={() => setPagando(objetivoDe(g, 'ARS'))} style={{ ...btnFlat('success'), flex: '1 1 auto', fontSize: '0.72rem', padding: '0.4rem' }}>Pagar ARS</button>}
                      {g.saldoUSD > 0.009 && <button onClick={() => setPagando(objetivoDe(g, 'USD'))} style={{ ...btnFlat('success'), flex: '1 1 auto', fontSize: '0.72rem', padding: '0.4rem' }}>Pagar USD</button>}
                    </div>
                  </div>

                  {expandidos.has(g.clave) && (
                    <div style={{ background: 'var(--ov-002)', padding: '0.25rem 1rem 0.75rem' }}>
                      {g.deudas.map((p) => (
                        <div key={p.id} style={{ padding: '0.6rem 0', borderTop: '1px solid var(--ov-004)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                            <span style={{ fontFamily: FM, fontSize: '0.78rem', color: 'var(--text-1)', wordBreak: 'break-word' }}><DetalleDeuda pasivo={p} /></span>
                            <EstadoBadge estado={p.estado} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', marginTop: '0.2rem' }}>
                            <span style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.6)' }}>Original {fmtMoneda(p.monto, p.moneda)}</span>
                            <span style={{ fontFamily: FM, fontSize: '0.8rem', fontWeight: 700, color: p.estado === 'PENDIENTE' ? '#fbbf24' : 'rgba(100,116,139,0.5)', whiteSpace: 'nowrap' }}>{fmtMoneda(p.saldo_pendiente, p.moneda)}</span>
                          </div>
                          <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.5rem' }}>
                            <button onClick={() => setPasivoEditar(p)} style={{ ...btnBordered('neutral'), flex: 1, fontSize: '0.7rem', padding: '0.35rem' }}>Editar</button>
                            <button onClick={() => setPasivoEliminar(p)} style={{ ...btnBordered('danger'), flex: '0 0 auto', fontSize: '0.7rem', padding: '0.35rem 0.6rem' }}>Eliminar</button>
                          </div>
                        </div>
                      ))}

                      {/* El total y sus botones, uno por moneda: ARS y USD son cajas
                          distintas y no se suman entre sí. */}
                      {g.saldoARS > 0.009 && (
                        <div style={{ marginTop: '0.6rem', paddingTop: '0.6rem', borderTop: '1px solid var(--bd-006)' }}>
                          <AccionesMoneda grupo={g} moneda="ARS" onPagar={setPagando} onCheque={setConCheque} onCompensar={setPasivoCompensar} />
                        </div>
                      )}
                      {g.saldoUSD > 0.009 && (
                        <div style={{ marginTop: '0.6rem', paddingTop: '0.6rem', borderTop: '1px solid var(--bd-006)' }}>
                          <AccionesMoneda grupo={g} moneda="USD" onPagar={setPagando} onCheque={setConCheque} onCompensar={setPasivoCompensar} />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Desktop: tabla */}
            <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '720px' }}>
                <thead>
                  <tr>
                    <th style={TH}>Acreedor</th>
                    <th style={TH}>Deudas</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Saldo ARS</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Saldo USD</th>
                    <th style={{ ...TH, padding: '0.625rem 1rem' }} />
                  </tr>
                </thead>
                <tbody>
                  {grupos.map((g) => {
                    const abierto = expandidos.has(g.clave)
                    return [
                      <tr key={g.clave}
                        onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                        onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                        <td style={{ ...TD, fontWeight: 600 }}>
                          <button type="button" onClick={() => toggle(g.clave)}
                            style={{ background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.45rem', textAlign: 'left' }}>
                            <span style={{ color: 'rgba(100,116,139,0.6)' }}>{abierto ? '▾' : '▸'}</span>
                            {g.nombre}
                          </button>
                        </td>
                        <td style={{ ...TD, color: 'rgba(100,116,139,0.7)', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                          {g.pendientes > 0 ? `${g.pendientes} pendiente(s)` : 'Sin saldo'} · {g.deudas.length} en total
                        </td>
                        <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: g.saldoARS > 0.009 ? '#fbbf24' : 'rgba(100,116,139,0.45)' }}>{g.saldoARS > 0.009 ? fmtARS(g.saldoARS) : '—'}</td>
                        <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: g.saldoUSD > 0.009 ? '#38bdf8' : 'rgba(100,116,139,0.45)' }}>{g.saldoUSD > 0.009 ? fmtUSD(g.saldoUSD) : '—'}</td>
                        <td style={{ ...TD, textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                            <button onClick={() => setCreando(g.nombre)} style={{ ...btnBordered('neutral'), fontSize: '0.68rem', padding: '2px 8px' }}>+ Sumar deuda</button>
                            {g.saldoARS > 0.009 && <button onClick={() => setPagando(objetivoDe(g, 'ARS'))} style={{ ...btnFlat('success'), fontSize: '0.68rem', padding: '2px 8px' }}>Pagar ARS</button>}
                            {g.saldoUSD > 0.009 && <button onClick={() => setPagando(objetivoDe(g, 'USD'))} style={{ ...btnFlat('success'), fontSize: '0.68rem', padding: '2px 8px' }}>Pagar USD</button>}
                          </div>
                        </td>
                      </tr>,
                      ...(abierto ? [
                        <tr key={`${g.clave}-detalle`}>
                          <td colSpan={5} style={{ padding: 0, background: 'var(--ov-002)', borderBottom: '1px solid var(--ov-004)' }}>
                            {/* Sin botón de pago por renglón: acá se le paga al acreedor,
                                no a una deuda. Editar y Eliminar sí, que corrigen la carga. */}
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                              <tbody>
                                {g.deudas.map((p) => (
                                  <tr key={p.id}>
                                    <td style={{ ...TD_SUB, color: 'rgba(148,163,184,0.85)', paddingLeft: '2.5rem', maxWidth: '320px', whiteSpace: 'normal', wordBreak: 'break-word' }}><DetalleDeuda pasivo={p} /></td>
                                    <td style={{ ...TD_SUB, textAlign: 'right', color: 'rgba(100,116,139,0.6)' }}>{fmtMoneda(p.monto, p.moneda)}</td>
                                    <td style={{ ...TD_SUB, textAlign: 'right', fontWeight: 700, color: p.estado === 'PENDIENTE' ? '#fbbf24' : 'rgba(100,116,139,0.5)' }}>{fmtMoneda(p.saldo_pendiente, p.moneda)}</td>
                                    <td style={{ ...TD_SUB, whiteSpace: 'nowrap' }}><EstadoBadge estado={p.estado} /></td>
                                    <td style={{ ...TD_SUB, textAlign: 'right' }}>
                                      <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'flex-end' }}>
                                        <button onClick={() => setPasivoEditar(p)} style={{ ...btnBordered('neutral'), fontSize: '0.66rem', padding: '2px 7px' }}>Editar</button>
                                        <button onClick={() => setPasivoEliminar(p)} style={{ ...btnBordered('danger'), fontSize: '0.66rem', padding: '2px 7px' }}>Eliminar</button>
                                      </div>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>

                            {(g.saldoARS > 0.009 || g.saldoUSD > 0.009) && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', padding: '0.75rem 1rem 0.9rem 2.5rem', borderTop: '1px solid var(--bd-006)' }}>
                                {g.saldoARS > 0.009 && <AccionesMoneda grupo={g} moneda="ARS" onPagar={setPagando} onCheque={setConCheque} onCompensar={setPasivoCompensar} />}
                                {g.saldoUSD > 0.009 && <AccionesMoneda grupo={g} moneda="USD" onPagar={setPagando} onCheque={setConCheque} onCompensar={setPasivoCompensar} />}
                              </div>
                            )}
                          </td>
                        </tr>,
                      ] : []),
                    ]
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {creando !== null && <ModalNuevaDeuda acreedorFijo={creando || undefined} onClose={() => setCreando(null)} onSuccess={handleSuccess} />}
      {pagando && <ModalPagarAcreedor deuda={pagando} onClose={() => setPagando(null)} onSuccess={handleSuccess} />}
      {conCheque && <ModalChequeAcreedor deuda={conCheque} onClose={() => setConCheque(null)} onSuccess={handleSuccess} />}
      {pasivoEditar && <ModalEditarDeuda pasivo={pasivoEditar} onClose={() => setPasivoEditar(null)} onSuccess={handleSuccess} />}
      {pasivoEliminar && <ModalEliminar entidad="pasivo" id={pasivoEliminar.id} onClose={() => setPasivoEliminar(null)} onSuccess={handleSuccess} />}
      {pasivoCompensar && (
        <ModalCompensar
          pasivo={pasivoCompensar}
          onClose={() => setPasivoCompensar(null)}
          onSuccess={() => { setPasivoCompensar(null); handleSuccess() }}
        />
      )}
    </div>
  )
}
