import { useState } from 'react'
import { pagarPrestamo } from '../api/prestamos'
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
import type { Moneda } from '../types'

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
// deuda del cliente en esa moneda, cruzando cheques fiados, deudas libres y
// préstamos. En los dos el `id` que viaja es el del **cliente**, no el de una
// deuda, y `saldo` es la suma de sus saldos; el backend reparte el importe de la
// operación más vieja a la más nueva.
export interface DeudaItem {
  tipo: 'prestamo' | 'fiado' | 'deuda_simple' | 'deudas_cliente' | 'deuda_general'
  id: string
  clienteNombre: string
  label: string
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
  const [cotizacion, setCotizacion] = useState('')
  // A cuánto entran al stock los dólares cobrados. Solo hace falta cuando se
  // cobra en USD una deuda que TAMBIÉN es en USD: ahí no hay cotización de la
  // que sacar el costo, y sin costo esos dólares no se pueden vender después.
  const [cotizStock, setCotizStock] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  // Forma de pago. El cheque está disponible donde el cobro no apunta a una
  // cuota concreta: una deuda libre suelta, todas las del cliente y el total
  // general de la pestaña General. Cobrar con cheque UNA cuota de préstamo o UN
  // fiado vive en sus propias pestañas, que sí necesitan saber a cuál imputarlo.
  const [forma, setForma] = useState<'efectivo' | 'cheque'>('efectivo')
  const esGeneral = deuda.tipo === 'deuda_general'
  const chequeDisponible =
    deuda.tipo === 'deuda_simple' || deuda.tipo === 'deudas_cliente' || esGeneral
  const esAgregado = deuda.tipo === 'deudas_cliente' || esGeneral

  // Qué hacer con el vuelto cuando el cheque cubre todo y sobra. Solo aplica al
  // cobro agregado: en una deuda suelta el excedente se informa y listo.
  const [vueltoModo, setVueltoModo] = useState<VueltoModo>('QUEDA_DEBIENDO')

  const [chNro, setChNro] = useState('')
  const [chBanco, setChBanco] = useState('')
  const [chMonto, setChMonto] = useState('')
  const [chPorcentaje, setChPorcentaje] = useState('')
  const [chFechaPago, setChFechaPago] = useState('')

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
  const chMontoNum = parseFloat(chMonto) || 0
  const chPctNum = parseFloat(chPorcentaje) || 0
  const chValorNeto = chMontoNum > 0 ? Math.round(chMontoNum * (100 - chPctNum)) / 100 : 0
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
  const puedeEnviarCheque =
    chNro.trim().length > 0 && chMontoNum > 0 && chPorcentaje !== '' && chEquivalente !== null

  async function handleSubmitCheque(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (esGeneral) {
        // `deuda.id` es el cliente: el cheque salda TODA su deuda en esa moneda
        // —fiados, deudas libres y préstamos— de la operación más vieja a la más
        // nueva. Si sobra, el vuelto se resuelve según vueltoModo.
        const r = await cobrarClienteConCheque({
          cliente_id: deuda.id,
          moneda_deuda: deuda.moneda,
          nro_cheque_pago: chNro.trim(),
          banco_pago: chBanco.trim() || null,
          monto_cheque: chMontoNum,
          porcentaje_compra_cheque: chPctNum,
          fecha_pago: chFechaPago || null,
          cotizacion: chCross ? cotizNum : null,
          vuelto_modo: chVueltoArs > 0 ? vueltoModo : null,
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
      if (esAgregado) {
        // `deuda.id` es el cliente: el cheque salda sus deudas de la más vieja a
        // la más nueva y, si sobra, el vuelto se resuelve según vueltoModo.
        const r = await cobrarDeudasClienteConCheque({
          cliente_id: deuda.id,
          moneda_deuda: deuda.moneda,
          nro_cheque_pago: chNro.trim(),
          banco_pago: chBanco.trim() || null,
          monto_cheque: chMontoNum,
          porcentaje_compra_cheque: chPctNum,
          fecha_pago: chFechaPago || null,
          cotizacion: chCross ? cotizNum : null,
          vuelto_modo: chVueltoArs > 0 ? vueltoModo : null,
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
        nro_cheque_pago: chNro.trim(),
        banco_pago: chBanco.trim() || null,
        monto_cheque: chMontoNum,
        porcentaje_compra_cheque: chPctNum,
        fecha_pago: chFechaPago || null,
        cotizacion: chCross ? cotizNum : null,
        vuelto_modo: chVueltoArs > 0 ? vueltoModo : null,
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
          cotizacion: cross ? cotizNum : null,
          cotizacion_stock: cotizacionStock,
        })
      } else if (deuda.tipo === 'deuda_simple') {
        await cobrarDeudaSimple(deuda.id, {
          monto_cobrado: montoNum,
          moneda_pago: monedaPago,
          cotizacion: cross ? cotizNum : null,
          cotizacion_stock: cotizacionStock,
        })
      } else if (esGeneral) {
        // `deuda.id` es el cliente: el importe se reparte entre TODAS sus deudas
        // de esa moneda —fiados, deudas libres y préstamos—, la más vieja primero.
        const r = await cobrarCliente({
          cliente_id: deuda.id,
          moneda_deuda: deuda.moneda,
          monto_cobrado: montoNum,
          moneda_pago: monedaPago,
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
                ? 'Se imputa a las operaciones más viejas primero —fiados, deudas y préstamos por igual—, hasta donde alcance.'
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
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div>
                  <label style={LABEL_STYLE}>Nº de cheque</label>
                  <input type="text" value={chNro} onChange={(e) => setChNro(e.target.value)} required autoFocus style={INPUT_STYLE} />
                </div>
                <div>
                  <label style={LABEL_STYLE}>Banco</label>
                  <input type="text" value={chBanco} onChange={(e) => setChBanco(e.target.value)} placeholder="Opcional" style={INPUT_STYLE} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div>
                  <label style={LABEL_STYLE}>Monto del cheque</label>
                  <input type="number" step="0.01" min="0.01" value={chMonto} onChange={(e) => setChMonto(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                </div>
                <div>
                  <label style={LABEL_STYLE}>% de descuento</label>
                  <input type="number" step="0.01" min="0" max="100" value={chPorcentaje} onChange={(e) => setChPorcentaje(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                </div>
              </div>
              <div>
                <label style={LABEL_STYLE}>Fecha de pago del cheque <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
                <input type="date" value={chFechaPago} onChange={(e) => setChFechaPago(e.target.value)} style={INPUT_STYLE} />
              </div>

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
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    {([['QUEDA_DEBIENDO', 'Le quedás debiendo'], ['SALDAR_EFECTIVO', 'Se lo devolvés ahora']] as const).map(([v, txt]) => (
                      <button key={v} type="button" onClick={() => setVueltoModo(v)}
                        style={{ ...(vueltoModo === v ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.72rem' }}>
                        {txt}
                      </button>
                    ))}
                  </div>
                  <p style={{ fontFamily: FM, fontSize: '0.68rem', marginTop: '0.25rem', color: 'rgba(100,116,139,0.55)' }}>
                    {vueltoModo === 'QUEDA_DEBIENDO'
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
