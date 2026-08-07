import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  definirFechaCorte,
  definirSaldoInicial,
  getApertura,
} from '../api/apertura'
import { useAuth } from '../auth/AuthContext'
import { fmtARS, fmtDate, fmtUSD, todayISO } from '../lib/fmt'
import { btnSolid, btnBordered, chip } from '../lib/ui'
import { useToast } from '../lib/toast'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }
const HELP: React.CSSProperties = { fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.75)', lineHeight: 1.5 }

/**
 * Puesta en marcha del sistema: los saldos con los que el negocio arrancó.
 *
 * Son dos cosas distintas y se cargan por separado, porque suelen pasar en
 * momentos distintos: primero se termina de cargar la cartera de cheques vieja
 * (y para eso hace falta la fecha de corte), y después —otro día— se cuenta el
 * efectivo del cajón.
 */
export default function AperturaSistema() {
  const { user } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()

  const { data: cfg, isLoading } = useQuery({
    queryKey: ['apertura'],
    queryFn: getApertura,
  })

  const [fechaCorte, setFechaCorte] = useState('')
  const [guardandoCorte, setGuardandoCorte] = useState(false)

  const [saldoArs, setSaldoArs] = useState('')
  const [saldoUsd, setSaldoUsd] = useState('')
  // Costo promedio de los dólares en mano: sin él quedarían en la caja pero no se
  // podrían vender, porque la venta consume lotes de compra con su costo.
  const [cotizUsd, setCotizUsd] = useState('')
  const [fechaSaldo, setFechaSaldo] = useState('')
  const [guardandoSaldo, setGuardandoSaldo] = useState(false)
  const [confirmando, setConfirmando] = useState(false)

  const [error, setError] = useState<string | null>(null)

  function invalidar() {
    queryClient.invalidateQueries({ queryKey: ['apertura'] })
    queryClient.invalidateQueries({ queryKey: ['reporte-caja'] })
    queryClient.invalidateQueries({ queryKey: ['reporte'] })
    queryClient.invalidateQueries({ queryKey: ['cartera'] })
    queryClient.invalidateQueries({ queryKey: ['movimientos-unificados'] })
  }

  async function handleCorte() {
    if (!fechaCorte) return
    setError(null)
    setGuardandoCorte(true)
    try {
      const r = await definirFechaCorte({
        fecha_corte: fechaCorte,
        operador_id: user?.username ?? 'panel',
      })
      toast(
        'success',
        r.cheques_marcados > 0
          ? `${r.cheques_marcados} cheque(s) marcados como cartera inicial`
          : 'Fecha de corte guardada',
      )
      invalidar()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setGuardandoCorte(false)
    }
  }

  async function handleSaldo() {
    setError(null)
    setGuardandoSaldo(true)
    try {
      await definirSaldoInicial({
        saldo_ars: parseFloat(saldoArs) || 0,
        saldo_usd: parseFloat(saldoUsd) || 0,
        cotizacion_usd: usdNum > 0 ? parseFloat(cotizUsd) || null : null,
        fecha: fechaSaldo,
        operador_id: user?.username ?? 'panel',
        forzar: cfg?.saldo_definido === true,
      })
      toast('success', 'Saldo de apertura cargado')
      setConfirmando(false)
      invalidar()
    } catch (err) {
      setError((err as Error).message)
      setConfirmando(false)
    } finally {
      setGuardandoSaldo(false)
    }
  }

  if (isLoading) {
    return <p style={HELP}>Cargando…</p>
  }

  const corteDefinido = !!cfg?.fecha_corte_carga_inicial
  const saldoDefinido = cfg?.saldo_definido === true

  const usdNum = parseFloat(saldoUsd) || 0
  // Con dólares en mano, la cotización de costo es obligatoria: sin ella el lote
  // no se crea y no se podrían vender.
  const faltaCotiz = usdNum > 0 && (parseFloat(cotizUsd) || 0) <= 0
  const puedeCargar = !!fechaSaldo && (!!saldoArs || !!saldoUsd) && !faltaCotiz

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

      {/* ── Paso 1: cartera preexistente ───────────────────────────── */}
      <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.5rem' }}>
          <h3 style={{ fontFamily: FN, fontSize: '1.25rem', letterSpacing: '0.06em', color: 'var(--text-1)' }}>
            1 · Cartera que ya tenían
          </h3>
          {corteDefinido
            ? <span style={chip('success')}>DEFINIDO</span>
            : <span style={chip('warning')}>PENDIENTE</span>}
        </div>

        <p style={{ ...HELP, marginBottom: '0.875rem' }}>
          Los cheques que ya estaban en cartera antes de usar el sistema se cargan igual
          que cualquier otro, pero <strong>no descuentan plata de la caja</strong>: esa
          plata salió hace tiempo, y el efectivo del paso 2 ya la tiene descontada. Si
          descontaran, se estaría restando dos veces.
          <br />
          Indicá <strong>hasta qué día</strong> están cargando cartera vieja. Desde el día
          siguiente, cada cheque nuevo vuelve a descontar normalmente.
        </p>

        {corteDefinido && (
          <p style={{ ...HELP, marginBottom: '0.875rem', color: 'var(--success)' }}>
            Corte actual: <strong>{fmtDate(cfg!.fecha_corte_carga_inicial)}</strong>
          </p>
        )}

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 12rem' }}>
            <label style={LABEL_STYLE}>Cargan cartera vieja hasta el</label>
            <input type="date" value={fechaCorte} max={todayISO()} onChange={(e) => setFechaCorte(e.target.value)} style={INPUT_STYLE} />
          </div>
          <button
            type="button"
            onClick={handleCorte}
            disabled={!fechaCorte || guardandoCorte}
            style={{ ...btnSolid('primary'), padding: '0.55rem 1.1rem', opacity: (!fechaCorte || guardandoCorte) ? 0.5 : 1 }}
          >
            {guardandoCorte ? 'Guardando…' : corteDefinido ? 'Actualizar corte' : 'Definir corte'}
          </button>
        </div>

        <p style={{ ...HELP, marginTop: '0.6rem', fontSize: '0.68rem' }}>
          Se aplica también hacia atrás: a los cheques ya cargados dentro del período se
          les quita el descuento de caja que no correspondía.
        </p>
      </div>

      {/* ── Paso 2: efectivo inicial ───────────────────────────────── */}
      <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.5rem' }}>
          <h3 style={{ fontFamily: FN, fontSize: '1.25rem', letterSpacing: '0.06em', color: 'var(--text-1)' }}>
            2 · Efectivo con el que arrancaron
          </h3>
          {saldoDefinido
            ? <span style={chip('success')}>CARGADO</span>
            : <span style={chip('warning')}>PENDIENTE</span>}
        </div>

        <p style={{ ...HELP, marginBottom: '0.875rem' }}>
          La plata que había en el cajón el día que empezaron a usar el sistema, en pesos
          y en dólares. Sin esto la caja arranca en cero y da negativa, porque se
          registran las salidas pero nunca se registró lo que había.
          <br />
          La <strong>fecha es la del efectivo</strong>, no la de hoy: podés cargarlo días
          después y los reportes viejos igual quedan bien.
        </p>

        {saldoDefinido && (
          <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.7rem 1rem', marginBottom: '0.875rem' }}>
            <p style={{ ...HELP, color: 'var(--text-1)' }}>
              Cargado por <strong>{cfg!.definido_por}</strong> · {fmtDate(cfg!.fecha_saldo_inicial)}
              <br />
              {fmtARS(cfg!.saldo_inicial_ars ?? '0')} · {fmtUSD(cfg!.saldo_inicial_usd ?? '0')}
              {cfg!.cotizacion_usd_inicial && <> (a ${cfg!.cotizacion_usd_inicial} promedio)</>}
            </p>
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(9rem, 1fr))', gap: '0.75rem' }}>
          <div>
            <label style={LABEL_STYLE}>Efectivo en pesos</label>
            <input type="number" step="0.01" min="0" value={saldoArs} onChange={(e) => setSaldoArs(e.target.value)} placeholder="0,00" style={INPUT_STYLE} />
          </div>
          <div>
            <label style={LABEL_STYLE}>Efectivo en dólares</label>
            <input type="number" step="0.01" min="0" value={saldoUsd} onChange={(e) => setSaldoUsd(e.target.value)} placeholder="0,00" style={INPUT_STYLE} />
          </div>
          <div>
            <label style={LABEL_STYLE}>Fecha del efectivo</label>
            <input type="date" value={fechaSaldo} max={todayISO()} onChange={(e) => setFechaSaldo(e.target.value)} style={INPUT_STYLE} />
          </div>
        </div>

        {/* El efectivo en USD por sí solo no habilita venderlos: la venta consume
            lotes de compra, y hace falta saber a cuánto se consiguieron. */}
        {usdNum > 0 && (
          <div style={{ marginTop: '0.75rem' }}>
            <label style={LABEL_STYLE}>¿A cuánto compraron esos dólares? (promedio, $/USD)</label>
            <input type="number" step="0.01" min="0.01" value={cotizUsd} onChange={(e) => setCotizUsd(e.target.value)} placeholder="Ej: 1350,00" style={{ ...INPUT_STYLE, maxWidth: '14rem' }} />
            <p style={{ ...HELP, marginTop: '0.35rem' }}>
              Es el costo con el que el sistema calcula la ganancia cuando los vendan. Si los
              compraron en tandas a precios distintos, poné el promedio: de ahí en adelante
              cada compra nueva guarda su precio real.
              <br />
              <strong>Sin este dato los dólares quedan en la caja pero no se pueden vender.</strong>
            </p>
          </div>
        )}

        {!confirmando ? (
          <button
            type="button"
            onClick={() => setConfirmando(true)}
            disabled={!puedeCargar}
            style={{ ...btnSolid('primary'), marginTop: '0.875rem', padding: '0.55rem 1.1rem', opacity: puedeCargar ? 1 : 0.5 }}
          >
            {saldoDefinido ? 'Corregir el saldo cargado' : 'Cargar saldo de apertura'}
          </button>
        ) : (
          <div style={{ marginTop: '0.875rem', background: 'color-mix(in srgb, var(--warning) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--warning) 30%, transparent)', borderRadius: 'var(--r-md)', padding: '0.875rem 1rem' }}>
            <p style={{ ...HELP, color: 'var(--text-1)', marginBottom: '0.75rem' }}>
              Vas a fijar la caja de apertura en{' '}
              <strong>{fmtARS(parseFloat(saldoArs) || 0)}</strong> y{' '}
              <strong>{fmtUSD(usdNum)}</strong>
              {usdNum > 0 && <> (comprados a <strong>${cotizUsd}</strong> promedio)</>}, con fecha{' '}
              <strong>{fmtDate(fechaSaldo)}</strong>.
              {saldoDefinido && ' Esto reemplaza el saldo cargado antes.'}
              <br />
              Revisá los números antes de confirmar: de acá sale el saldo de toda la caja.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem' }}>
              <button type="button" onClick={() => setConfirmando(false)} style={{ ...btnBordered('neutral'), padding: '0.5rem 1rem' }}>Volver</button>
              <button type="button" onClick={handleSaldo} disabled={guardandoSaldo} style={{ ...btnSolid('warning'), padding: '0.5rem 1rem', opacity: guardandoSaldo ? 0.6 : 1 }}>
                {guardandoSaldo ? 'Cargando…' : 'Confirmar'}
              </button>
            </div>
          </div>
        )}
      </div>

      {error && <p style={{ fontFamily: FM, fontSize: '0.78rem', color: '#f87171' }}>{error}</p>}
    </div>
  )
}
