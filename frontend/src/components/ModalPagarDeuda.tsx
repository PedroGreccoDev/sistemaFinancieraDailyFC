import { useState } from 'react'
import { pagarPrestamo, pagarPrestamoConCheque } from '../api/prestamos'
import { cobrarEfectivo } from '../api/fiados'
import {
  cobrarDeudaSimple,
  cobrarDeudaSimpleConCheque,
  cobrarDeudasCliente,
  cobrarDeudasClienteConCheque,
  type VueltoModo,
} from '../api/deudas_simples'
import { cobrarCliente, cobrarClienteConCheque } from '../api/deudores'
import { fmtARS, fmtUSD } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import type { MedioPago, Moneda } from '../types'
import SelectorMedioPago from './SelectorMedioPago'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

// Una deuda concreta a la que se puede imputar un pago de importe libre (parcial
// o total): un préstamo, un fiado o una deuda libre. `saldo` y `moneda` son de la
// deuda (los fiados son siempre ARS; préstamos y deudas libres, en su moneda).
//
// `deudas_cliente` es el caso agregado de "Otras deudas": todas las deudas
// libres abiertas de un cliente en una misma moneda, cobradas de una.
//
// `deuda_general` es el de la pestaña General y va un paso más allá: **toda** la
// deuda del cliente en esa moneda, cruzando cheques fiados y deudas libres. Los
// préstamos no entran —se cobran en Créditos, con `tipo: 'prestamo'` desde su
// propia pantalla—. En los dos el `id` que viaja es el del **cliente**, no el de una
// deuda, y `saldo` es la suma de sus saldos; el backend reparte el importe de la
// operación más vieja a la más nueva.
// Lo que se puede hacer con el sobrante de un cheque que cubre de más. Los dos
// primeros son los de siempre (§5); `A_CAPITAL` solo aparece en un préstamo a
// interés fijo, donde el capital es la otra mitad de lo que el cliente debe.
type SobranteModo = VueltoModo | 'A_CAPITAL'

// Una fila del formulario de cheques. Strings: es lo que hay tipeado en los
// inputs, y se convierte a número recién al calcular.
interface ChequeFila {
  nro: string
  banco: string
  monto: string
  pct: string
  fechaPago: string
}

const filaVacia = (): ChequeFila => ({ nro: '', banco: '', monto: '', pct: '', fechaPago: '' })

export interface DeudaItem {
  tipo: 'prestamo' | 'fiado' | 'deuda_simple' | 'deudas_cliente' | 'deuda_general'
  id: string
  clienteNombre: string
  label: string
  // Solo en un préstamo a interés fijo: lo que queda prestado. Habilita mandar
  // el sobrante de un cheque contra el capital, que es la otra mitad de lo que
  // debe y no está en `saldo` (ahí va el interés devengado impago).
  capitalPendiente?: number
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
  // Por cuál de las dos cajas entra la plata. Efectivo por defecto: es el
  // caso normal, así que el que no mira este control cobra bien igual.
  const [medioPago, setMedioPago] = useState<MedioPago>('EFECTIVO')
  const [cotizacion, setCotizacion] = useState('')
  // A cuánto entran al stock los dólares cobrados. Solo hace falta cuando se
  // cobra en USD una deuda que TAMBIÉN es en USD: ahí no hay cotización de la
  // que sacar el costo, y sin costo esos dólares no se pueden vender después.
  const [cotizStock, setCotizStock] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  // Forma de pago. El cheque está disponible donde el cobro no apunta a una
  // cuota concreta: una deuda libre suelta, todas las del cliente, el total
  // general de la pestaña General y el pago libre de un préstamo. Cobrar con
  // cheque UNA cuota o UN fiado vive en sus propias pantallas, que sí necesitan
  // saber a cuál imputarlo.
  const [forma, setForma] = useState<'efectivo' | 'cheque'>('efectivo')
  const esGeneral = deuda.tipo === 'deuda_general'
  const esPrestamo = deuda.tipo === 'prestamo'
  const chequeDisponible =
    deuda.tipo === 'deuda_simple' || deuda.tipo === 'deudas_cliente' || esGeneral || esPrestamo
  // Un préstamo a interés fijo suma una tercera salida para el sobrante: bajarlo
  // del capital. No es un vuelto —no sale ni entra plata—, es menos plata afuera.
  const capitalPendiente = deuda.capitalPendiente ?? 0
  const puedeIrACapital = esPrestamo && capitalPendiente > 0.009
  const esAgregado = deuda.tipo === 'deudas_cliente' || esGeneral

  // Qué hacer con el vuelto cuando el cheque cubre todo y sobra. Solo aplica al
  // cobro agregado: en una deuda suelta el excedente se informa y listo.
  const [vueltoModo, setVueltoModo] = useState<SobranteModo>('QUEDA_DEBIENDO')
  // Fuera del préstamo el sobrante solo tiene dos salidas: el botón del capital
  // ni siquiera se muestra, así que esto nunca cambia lo que el operador eligió.
  const vueltoClasico: VueltoModo = vueltoModo === 'A_CAPITAL' ? 'QUEDA_DEBIENDO' : vueltoModo

  // Los papeles que entrega. Casi siempre es más de uno —"me entregó estos tres
  // al 5%"—: el cliente junta los que tiene y con eso salda. Cada uno entra a
  // cartera por separado, con su nominal y su descuento, y la deuda baja por la
  // suma de los netos.
  const [cheques, setCheques] = useState<ChequeFila[]>([filaVacia()])
  const setFila = (i: number, campo: keyof ChequeFila, valor: string) =>
    setCheques((prev) => prev.map((f, j) => (j === i ? { ...f, [campo]: valor } : f)))
  const agregarFila = () => setCheques((prev) => [...prev, filaVacia()])
  const quitarFila = (i: number) => setCheques((prev) => prev.filter((_, j) => j !== i))

  const saldo = deuda.saldo
  const montoNum = parseFloat(monto) || 0
  const cotizNum = parseFloat(cotizacion) || 0
  const cross = monedaPago !== deuda.moneda
  const cotizStockNum = parseFloat(cotizStock) || 0
  const pideStock = monedaPago === 'USD' && !cross
  const cotizacionStock = monedaPago === 'USD' ? (cross ? cotizNum : cotizStockNum) : null

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

  // ── Cheque: valor neto y qué salda ─────────────────────────────────
  const chNominal = cheques.reduce((acc, f) => acc + (parseFloat(f.monto) || 0), 0)
  // El neto de cada uno y no del total: dos cheques al mismo porcentaje dan lo
  // mismo, pero uno a 30 días y otro a 90 se toman distinto.
  const chValorNeto = Math.round(
    cheques.reduce((acc, f) => {
      const monto = parseFloat(f.monto) || 0
      return acc + (monto > 0 ? monto * (100 - (parseFloat(f.pct) || 0)) / 100 : 0)
    }, 0) * 100,
  ) / 100
  // El cheque siempre es en pesos: si la deuda es en USD hay que convertir.
  const chCross = deuda.moneda !== 'ARS'
  const chEquivalente = chValorNeto > 0 && (!chCross || cotizNum > 0)
    ? Math.round((chCross ? chValorNeto / cotizNum : chValorNeto) * 100) / 100
    : null
  // A diferencia del efectivo, un cheque de más NO es error: la deuda se cancela
  // y el negocio le queda debiendo la diferencia al cliente.
  const chDiferencia = chEquivalente !== null ? Math.round((chEquivalente - saldo) * 100) / 100 : null
  // Lo que sobra, EN PESOS: la diferencia de arriba está en la moneda de la
  // deuda, pero el excedente de un cheque es plata en pesos y en pesos se
  // devuelve. Sin esta conversión, una deuda en USD mostraría "sobran $50"
  // cuando en realidad son 50 dólares.
  const chVueltoArs = chDiferencia !== null && chDiferencia > 0
    ? Math.round((chCross ? chDiferencia * cotizNum : chDiferencia) * 100) / 100
    : 0
  // Cada fila tiene que estar completa: una a medio cargar es un cheque que el
  // operador cree que entregó y no entró.
  const filasCompletas = cheques.every(
    (f) => f.nro.trim().length > 0 && (parseFloat(f.monto) || 0) > 0 && f.pct !== '',
  )
  const puedeEnviarCheque = cheques.length > 0 && filasCompletas && chEquivalente !== null
  // Lo que viaja al backend, ya normalizado.
  const chequesPayload = cheques.map((f) => ({
    nro_cheque: f.nro.trim() || null,
    banco: f.banco.trim() || null,
    monto: parseFloat(f.monto) || 0,
    porcentaje_compra: parseFloat(f.pct) || 0,
    fecha_pago: f.fechaPago || null,
  }))

  async function handleSubmitCheque(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (esGeneral) {
        // `deuda.id` es el cliente: el cheque salda TODA su deuda en esa moneda
        // —fiados y deudas libres, no préstamos— de la operación más vieja a la
        // más nueva. Si sobra, el vuelto se resuelve según vueltoModo.
        const r = await cobrarClienteConCheque({
          cliente_id: deuda.id,
          moneda_deuda: deuda.moneda,
          cheques: chequesPayload,
          cotizacion: chCross ? cotizNum : null,
          vuelto_modo: chVueltoArs > 0 ? vueltoClasico : null,
        })
        const vuelto = parseFloat(r.vuelto_ars)
        toast(
          'success',
          vuelto > 0
            ? r.vuelto_modo === 'SALDAR_EFECTIVO'
              ? `Saldó ${r.canceladas} operación(es) · le devolviste ${fmtARS(vuelto)} de vuelto`
              : `Saldó ${r.canceladas} operación(es) · le quedás debiendo ${fmtARS(vuelto)}`
            : `Cobrado · saldó ${r.canceladas} operación(es), quedan ${fmtMoneda(parseFloat(r.saldo_restante), deuda.moneda)}`,
        )
        onSuccess()
        return
      }
      if (esPrestamo) {
        // El cheque salda las cuotas —o los períodos de interés— más viejas
        // primero. Si sobra, `sobrante_modo` decide: bajarlo del capital (solo
        // interés fijo), devolverlo o quedar debiéndolo.
        const r = await pagarPrestamoConCheque(deuda.id, {
          cheques: chequesPayload,
          cotizacion: chCross ? cotizNum : null,
          sobrante_modo: chVueltoArs > 0 ? vueltoModo : null,
        })
        const aCapital = parseFloat(r.a_capital)
        const vuelto = parseFloat(r.vuelto_ars)
        const cancelado = r.prestamo.estado === 'CANCELADO'
        toast(
          'success',
          aCapital > 0
            ? `Cobrado · ${fmtARS(aCapital)} bajaron el capital${cancelado ? ' · préstamo cancelado' : ''}`
            : vuelto > 0
              ? r.sobrante_modo === 'SALDAR_EFECTIVO'
                ? `Cobrado · le devolviste ${fmtARS(vuelto)} de vuelto`
                : `Cobrado · le quedás debiendo ${fmtARS(vuelto)}`
              : cancelado
                ? 'Préstamo cancelado con el cheque'
                : `Cobrado · imputado ${fmtMoneda(parseFloat(r.imputado), deuda.moneda)}`,
        )
        onSuccess()
        return
      }
      if (esAgregado) {
        // `deuda.id` es el cliente: el cheque salda sus deudas de la más vieja a
        // la más nueva y, si sobra, el vuelto se resuelve según vueltoModo.
        const r = await cobrarDeudasClienteConCheque({
          cliente_id: deuda.id,
          moneda_deuda: deuda.moneda,
          cheques: chequesPayload,
          cotizacion: chCross ? cotizNum : null,
          vuelto_modo: chVueltoArs > 0 ? vueltoClasico : null,
        })
        const vuelto = parseFloat(r.vuelto_ars)
        toast(
          'success',
          vuelto > 0
            ? r.vuelto_modo === 'SALDAR_EFECTIVO'
              ? `Saldó ${r.canceladas} deuda(s) · le devolviste ${fmtARS(vuelto)} de vuelto`
              : `Saldó ${r.canceladas} deuda(s) · le quedás debiendo ${fmtARS(vuelto)}`
            : `Cobrado · saldó ${r.canceladas} deuda(s), quedan ${fmtMoneda(parseFloat(r.saldo_restante), deuda.moneda)}`,
        )
        onSuccess()
        return
      }
      const r = await cobrarDeudaSimpleConCheque(deuda.id, {
        cheques: chequesPayload,
        cotizacion: chCross ? cotizNum : null,
        vuelto_modo: chVueltoArs > 0 ? vueltoClasico : null,
      })
      const dif = parseFloat(r.diferencia)
      const vuelto = parseFloat(r.vuelto_ars)
      toast(
        'success',
        vuelto > 0
          ? r.vuelto_modo === 'SALDAR_EFECTIVO'
            ? `Deuda saldada · le devolviste ${fmtARS(vuelto)} de vuelto`
            : `Deuda saldada · le quedás debiendo ${fmtARS(vuelto)}`
          : dif < 0
            ? `Cobrado · sigue debiendo ${fmtMoneda(-dif, deuda.moneda)}`
            : 'Deuda saldada con el cheque',
      )
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (deuda.tipo === 'prestamo') {
        await pagarPrestamo(deuda.id, {
          monto_pagado: montoNum,
          moneda_pago: monedaPago,
          medio_pago: medioPago,
          cotizacion: cross ? cotizNum : null,
          cotizacion_stock: cotizacionStock,
        })
      } else if (deuda.tipo === 'deuda_simple') {
        await cobrarDeudaSimple(deuda.id, {
          monto_cobrado: montoNum,
          moneda_pago: monedaPago,
          medio_pago: medioPago,
          cotizacion: cross ? cotizNum : null,
          cotizacion_stock: cotizacionStock,
        })
      } else if (esGeneral) {
        // `deuda.id` es el cliente: el importe se reparte entre TODAS sus deudas
        // de esa moneda —fiados y deudas libres, no préstamos—, la más vieja primero.
        const r = await cobrarCliente({
          cliente_id: deuda.id,
          moneda_deuda: deuda.moneda,
          monto_cobrado: montoNum,
          moneda_pago: monedaPago,
          medio_pago: medioPago,
          cotizacion: cross ? cotizNum : null,
          cotizacion_stock: cotizacionStock,
        })
        const restante = parseFloat(r.saldo_restante)
        toast(
          'success',
          restante <= 0
            ? `Cobrado · ${deuda.clienteNombre} no debe más nada en ${deuda.moneda}`
            : `Cobrado · saldó ${r.canceladas} operación(es), quedan ${fmtMoneda(restante, deuda.moneda)}`,
        )
        onSuccess()
        return
      } else if (deuda.tipo === 'deudas_cliente') {
        // Acá `deuda.id` es el cliente: el importe se reparte entre sus deudas
        // abiertas de esa moneda, la más vieja primero.
        const r = await cobrarDeudasCliente({
          cliente_id: deuda.id,
          moneda_deuda: deuda.moneda,
          monto_cobrado: montoNum,
          moneda_pago: monedaPago,
          medio_pago: medioPago,
          cotizacion: cross ? cotizNum : null,
          cotizacion_stock: cotizacionStock,
        })
        const restante = parseFloat(r.saldo_restante)
        toast(
          'success',
          restante <= 0
            ? `Cobrado · ${deuda.clienteNombre} no debe más nada en ${deuda.moneda}`
            : `Cobrado · saldó ${r.canceladas} deuda(s), quedan ${fmtMoneda(restante, deuda.moneda)}`,
        )
        onSuccess()
        return
      } else {
        await cobrarEfectivo(deuda.id, montoNum, 'panel-web', {
          moneda_pago: monedaPago,
          medio_pago: medioPago,
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
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>
            {esAgregado ? 'Cobrar al cliente' : 'Pagar deuda'}
          </h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{deuda.clienteNombre} · {deuda.label}</p>
        </div>
        <form onSubmit={forma === 'cheque' ? handleSubmitCheque : handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', padding: '0.75rem 1rem', borderRadius: 'var(--r-md)', display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
            <span style={{ color: 'rgba(100,116,139,0.65)' }}>Saldo pendiente</span>
            <span style={{ fontWeight: 700, color: '#fbbf24' }}>{fmtMoneda(saldo, deuda.moneda)}</span>
          </div>

          {esAgregado && (
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)', marginTop: '-0.4rem' }}>
              {esGeneral
                ? 'Se imputa a las operaciones más viejas primero —fiados y deudas por igual—, hasta donde alcance. Los préstamos se cobran en Créditos.'
                : 'Se imputa a las deudas más viejas primero, hasta donde alcance.'}
            </p>
          )}

          {/* Con qué paga el cliente */}
          {chequeDisponible && (
            <div>
              <label style={LABEL_STYLE}>Cómo paga</label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {([['efectivo', 'Efectivo'], ['cheque', 'Con cheque']] as const).map(([v, txt]) => (
                  <button key={v} type="button" onClick={() => { setForma(v); setError(null) }}
                    style={{ ...(forma === v ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.78rem' }}>
                    {txt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {forma === 'cheque' ? (
            <>
              {cheques.map((fila, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', paddingTop: i > 0 ? '0.6rem' : 0, borderTop: i > 0 ? '1px solid var(--bd-006)' : 'none' }}>
                  {cheques.length > 1 && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontFamily: FM, fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>
                        Cheque {i + 1} de {cheques.length}
                      </span>
                      <button type="button" onClick={() => quitarFila(i)} style={{ ...btnBordered('danger'), fontSize: '0.68rem', padding: '0.2rem 0.6rem' }}>
                        Quitar
                      </button>
                    </div>
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                    <div>
                      <label style={LABEL_STYLE}>Nº de cheque</label>
                      <input type="text" value={fila.nro} onChange={(e) => setFila(i, 'nro', e.target.value)} required autoFocus={i === 0} style={INPUT_STYLE} />
                    </div>
                    <div>
                      <label style={LABEL_STYLE}>Banco</label>
                      <input type="text" value={fila.banco} onChange={(e) => setFila(i, 'banco', e.target.value)} placeholder="Opcional" style={INPUT_STYLE} />
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.75rem' }}>
                    <div>
                      <label style={LABEL_STYLE}>Monto</label>
                      <input type="number" step="0.01" min="0.01" value={fila.monto} onChange={(e) => setFila(i, 'monto', e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                    </div>
                    <div>
                      <label style={LABEL_STYLE}>% de dcto.</label>
                      <input type="number" step="0.01" min="0" max="100" value={fila.pct} onChange={(e) => setFila(i, 'pct', e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                    </div>
                    <div>
                      <label style={LABEL_STYLE}>Fecha de pago</label>
                      <input type="date" value={fila.fechaPago} onChange={(e) => setFila(i, 'fechaPago', e.target.value)} style={INPUT_STYLE} />
                    </div>
                  </div>
                </div>
              ))}
              <button type="button" onClick={agregarFila} style={{ ...btnBordered('primary'), padding: '0.4rem', fontSize: '0.72rem' }}>
                + Agregar otro cheque
              </button>

              {chCross && (
                <div>
                  <label style={LABEL_STYLE}>Cotización (pesos por 1 USD)</label>
                  <input type="number" step="0.0001" min="0.0001" value={cotizacion} onChange={(e) => setCotizacion(e.target.value)} required style={INPUT_STYLE} />
                  <p style={{ fontFamily: FM, fontSize: '0.68rem', marginTop: '0.25rem', color: 'rgba(100,116,139,0.55)' }}>
                    El cheque es en pesos y la deuda en USD: la cotización define cuántos dólares salda.
                  </p>
                </div>
              )}

              {chValorNeto > 0 && (
                <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.65rem 1rem', fontFamily: FM, fontSize: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'rgba(100,116,139,0.7)' }}>Vale (neto)</span>
                    <span style={{ fontWeight: 700, color: 'var(--text-1)' }}>{fmtARS(chValorNeto)}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)' }}>
                    <span>{cheques.length === 1 ? 'Nominal' : `${cheques.length} cheques · nominal`}</span>
                    <span>{fmtARS(chNominal)}</span>
                  </div>
                  {chDiferencia !== null && (
                    <span style={{ color: chDiferencia > 0 ? '#fbbf24' : chDiferencia < 0 ? 'rgba(100,116,139,0.8)' : '#4ade80' }}>
                      {chDiferencia > 0
                        ? `Cancela ${esAgregado ? 'todas sus deudas' : 'la deuda'} y sobran ${fmtMoneda(chDiferencia, deuda.moneda)}`
                        : chDiferencia < 0
                          ? `Sigue debiendo ${fmtMoneda(-chDiferencia, deuda.moneda)}`
                          : `Cancela ${esAgregado ? 'todas sus deudas' : 'la deuda'} justo`}
                    </span>
                  )}
                  <span style={{ color: 'rgba(100,116,139,0.55)', fontSize: '0.68rem' }}>
                    El cheque entra a cartera. No mueve la caja hasta que lo vendas o lo cobres.
                  </span>
                </div>
              )}

              {/* El cheque cubre todo y sobra: hay que decidir qué se hace con
                  el vuelto. Vale igual para una deuda suelta que para todas las
                  del cliente — es la misma situación. */}
              {chVueltoArs > 0 && (
                <div>
                  <label style={LABEL_STYLE}>Qué hacés con los {fmtARS(chVueltoArs)} que sobran</label>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {([
                      // La opción del capital solo existe en un préstamo a interés
                      // fijo con plata todavía afuera: es el único lugar donde el
                      // sobrante tiene contra qué imputarse.
                      ...(puedeIrACapital ? [['A_CAPITAL', 'Baja el capital'] as const] : []),
                      ['QUEDA_DEBIENDO', 'Le quedás debiendo'] as const,
                      ['SALDAR_EFECTIVO', 'Se lo devolvés ahora'] as const,
                    ]).map(([v, txt]) => (
                      <button key={v} type="button" onClick={() => setVueltoModo(v)}
                        style={{ ...(vueltoModo === v ? btnSolid('primary') : btnBordered('neutral')), flex: '1 1 30%', padding: '0.45rem', fontSize: '0.72rem' }}>
                        {txt}
                      </button>
                    ))}
                  </div>
                  <p style={{ fontFamily: FM, fontSize: '0.68rem', marginTop: '0.25rem', color: 'rgba(100,116,139,0.55)' }}>
                    {vueltoModo === 'A_CAPITAL'
                      ? `Devuelve capital: quedan ${fmtARS(Math.max(0, capitalPendiente - chVueltoArs))} prestados y el interés se calcula sobre eso. No mueve la caja.`
                      : vueltoModo === 'QUEDA_DEBIENDO'
                        ? 'Se anota como deuda del negocio a su favor, en Deudas. No mueve la caja.'
                        : 'Sale de la caja de pesos hoy, como vuelto.'}
                  </p>
                </div>
              )}

              {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
              <div style={{ display: 'flex', gap: '0.75rem' }}>
                <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Volver</button>
                <button type="submit" disabled={loading || !puedeEnviarCheque} style={{ ...btnSolid('success'), flex: 1, padding: '0.55rem', opacity: (loading || !puedeEnviarCheque) ? 0.5 : 1 }}>
                  {loading ? 'Registrando…' : 'Recibir cheque'}
                </button>
              </div>
            </>
          ) : (
          <>
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

          {/* Va pegado al monto porque son la misma decisión: cuánta plata y por
              dónde. El cheque no lo lleva —no mueve efectivo, entra a cartera—. */}
          <SelectorMedioPago
            valor={medioPago}
            onChange={setMedioPago}
            label="¿Cómo te pagaron?"
            ayuda="Entra a la caja que elijas. El efectivo se cuenta en el cajón y la transferencia se ve en el banco."
          />

          {cross && (
            <div>
              <label style={LABEL_STYLE}>Cotización (pesos por 1 USD)</label>
              <input type="number" step="0.0001" min="0.0001" value={cotizacion} onChange={(e) => setCotizacion(e.target.value)} required style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.68rem', marginTop: '0.25rem', color: 'rgba(100,116,139,0.55)' }}>
                Pagás en {monedaPago}; la deuda es en {deuda.moneda}. La cotización imputa cuánto se salda.
              </p>
            </div>
          )}

          {/* Cobrar en dólares los hace entrar al stock vendible, y para eso hace
              falta su costo: contra él se calcula la ganancia el día que se vendan.
              Cuando el cobro cruza monedas la cotización de arriba ya sirve; acá
              (dólares contra una deuda en dólares) no hay ninguna. */}
          {pideStock && (
            <div>
              <label style={LABEL_STYLE}>¿A cuánto tomás el dólar? (pesos por 1 USD)</label>
              <input type="number" step="0.0001" min="0.0001" value={cotizStock} onChange={(e) => setCotizStock(e.target.value)} required style={INPUT_STYLE} />
              <p style={{ fontFamily: FM, fontSize: '0.68rem', marginTop: '0.25rem', color: 'rgba(100,116,139,0.55)' }}>
                Es el costo con el que esos dólares entran al stock. Sin él no se pueden vender después.
              </p>
            </div>
          )}

          {equivalente !== null && !superaSaldo && (
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: cancelaTotal ? '#4ade80' : '#fbbf24' }}>
              {cross && `Salda ${fmtMoneda(equivalente, deuda.moneda)} de la deuda · `}
              {cancelaTotal
                ? (esAgregado ? 'Salda todas sus deudas' : 'Salda la deuda completamente')
                : `Saldo restante: ${fmtMoneda(saldo - equivalente, deuda.moneda)}`}
            </p>
          )}
          {superaSaldo && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#f87171' }}>El pago equivale a {fmtMoneda(equivalente!, deuda.moneda)} y supera el saldo pendiente</p>}
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Volver</button>
            <button type="submit" disabled={loading || !puedeEnviar} style={{ ...btnSolid('success'), flex: 1, padding: '0.55rem', opacity: (loading || !puedeEnviar) ? 0.5 : 1 }}>{loading ? 'Registrando…' : 'Confirmar pago'}</button>
          </div>
          </>
          )}
        </form>
      </div>
    </div>
  )
}
