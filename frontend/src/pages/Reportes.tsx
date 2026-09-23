import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getReporteCaja } from '../api/reportes'
import { fmtARS, fmtUSD, fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import DropdownFilter from '../components/DropdownFilter'
import DateRangePicker from '../components/DateRangePicker'
import type { CajaMoneda, GastoPorConcepto, Moneda } from '../types'

type Preset = 'hoy' | 'semana' | 'mes' | 'custom'

const FN = "'Bebas Neue', sans-serif"
const FM = "'Manrope', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }

function getRangeForPreset(preset: Preset, customDesde: string | null, customHasta: string | null) {
  const hoy = todayISO()
  if (preset === 'hoy') return { desde: hoy, hasta: hoy }
  if (preset === 'semana') return { desde: weekStartISO(), hasta: hoy }
  if (preset === 'mes') return { desde: monthStartISO(), hasta: hoy }
  return { desde: customDesde ?? hoy, hasta: customHasta ?? hoy }
}

function MetricCard({ label, value, color = 'default', accentColor, prefix, sub }: {
  label: string
  value: string
  color?: 'default' | 'green' | 'red' | 'indigo'
  accentColor?: string
  prefix?: string
  /** Línea chica bajo el número, para lo que el número solo no dice. */
  sub?: string
}) {
  const numColor = { default: 'var(--text-1)', green: 'var(--success)', red: 'var(--danger)', indigo: '#818cf8' }[color]
  return (
    <div className="lift" style={{
      ...CARD,
      padding: '0.65rem 0.875rem',
      minWidth: 0,
      display: 'flex',
      flexDirection: 'column',
      gap: '0.35rem',
      ...(accentColor ? { borderLeft: `3px solid ${accentColor}` } : {}),
    }}>
      <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.65)', lineHeight: 1.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</p>
      <p style={{ fontFamily: FN, fontSize: '1.25rem', color: numColor, letterSpacing: '0.02em', lineHeight: 1, fontVariantNumeric: 'tabular-nums', wordBreak: 'break-all' }}>
        {prefix}{value}
      </p>
      {sub && (
        <p style={{ fontFamily: FM, fontSize: '0.63rem', color: 'rgba(100,116,139,0.55)', lineHeight: 1.25 }}>{sub}</p>
      )}
    </div>
  )
}

/** Tarjeta de un snapshot: un saldo de hoy, no plata que se movió en el período.
 *
 *  La usan los dos bloques del pie —lo que está afuera y lo que se debe— con el
 *  color como única diferencia: verde lo que tiene que volver, rojo lo que hay
 *  que pagar. Cuando eran dos bloques de markup calcado, el segundo se escribía
 *  copiando el primero. */
function SnapshotCard({ label, value, sub, tono }: {
  label: string
  value: string
  sub: string
  tono: 'entra' | 'sale'
}) {
  return (
    <div className="lift" style={{ ...CARD, padding: '0.8rem 1rem', minWidth: 0 }}>
      <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
      <p style={{
        fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)',
        color: tono === 'entra' ? 'var(--success)' : 'var(--danger)',
        letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem',
        overflowWrap: 'anywhere', fontVariantNumeric: 'tabular-nums',
      }}>{value}</p>
      <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
    </div>
  )
}

/** En qué se fue la plata del período, por concepto y de mayor a menor.
 *
 *  A diferencia de los dos snapshots que tiene al lado, **este sigue el filtro de
 *  fecha**: son los gastos de esos días. Por eso lo dice en el subtítulo — dos
 *  recuadros pegados que se leen igual y uno filtra y el otro no es la forma más
 *  fácil de leer mal un número. */
function GastosBloque({ gastos }: { gastos: GastoPorConcepto[] }) {
  const porMoneda = (['ARS', 'USD'] as const)
    .map((m) => ({ moneda: m, items: gastos.filter((g) => g.moneda === m) }))
    .filter(({ items }) => items.length > 0)

  return (
    <div style={{ ...CARD, overflow: 'hidden' }}>
      {porMoneda.length === 0 ? (
        <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.55)', padding: '1rem' }}>
          Sin gastos en el período.
        </p>
      ) : porMoneda.map(({ moneda, items }) => {
        const total = items.reduce((a, g) => a + parseFloat(g.total), 0)
        const fmt = (v: string | number) => fmtMonto(v, moneda as Moneda)
        return (
          <div key={moneda}>
            {/* Encabezado: la moneda y su total. Las dos nunca se suman. */}
            <div style={{
              display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
              padding: '0.6rem 1rem', background: 'var(--ov-0025)',
              borderBottom: '1px solid var(--bd-006)',
            }}>
              <span style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)' }}>
                Total {moneda}
              </span>
              <span style={{ fontFamily: FN, fontSize: '1.15rem', letterSpacing: '0.02em', color: 'var(--danger)', fontVariantNumeric: 'tabular-nums' }}>
                {fmt(total)}
              </span>
            </div>
            {items.map((g) => (
              <div key={`${moneda}-${g.concepto}`} style={{
                display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                gap: '0.75rem', padding: '0.5rem 1rem', borderBottom: '1px solid var(--ov-004)',
              }}>
                <span style={{ fontFamily: FM, fontSize: '0.8rem', color: 'var(--text-1)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {g.concepto}
                </span>
                <span style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-2)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                  {fmt(g.total)}
                </span>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

function CajaBloque({ caja, simbolo }: { caja: CajaMoneda; simbolo: 'ARS' | 'USD' }) {
  const fmt = (v: string | number) => fmtMonto(v, simbolo as Moneda)
  const neto = parseFloat(caja.neto)
  const cierre = parseFloat(caja.saldo_cierre ?? '0')
  return (
    <div style={{ ...CARD, overflow: 'hidden' }}>
      {/* Encabezado de la caja */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0.8rem 1.1rem', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)',
      }}>
        <span style={{ fontFamily: FN, fontSize: '1.4rem', letterSpacing: '0.04em', color: 'var(--text-1)' }}>
          Caja {caja.moneda}
        </span>
        <div style={{ display: 'flex', gap: '1.2rem', alignItems: 'baseline' }}>
          <span style={{ fontFamily: FM, fontSize: '0.72rem', color: 'var(--success)' }}>
            + {fmt(caja.ingresos_total)}
          </span>
          <span style={{ fontFamily: FM, fontSize: '0.72rem', color: 'var(--danger)' }}>
            − {fmt(caja.egresos_total)}
          </span>
          <span style={{
            fontFamily: FN, fontSize: '1.3rem', letterSpacing: '0.02em',
            color: neto >= 0 ? '#34d399' : '#f87171', fontVariantNumeric: 'tabular-nums',
          }}>
            {fmt(caja.neto)}
          </span>
        </div>
      </div>

      {/* Apertura → cierre. El neto de arriba es el FLUJO del período (un día de
          solo compras da negativo, y está bien); esta franja muestra el SALDO,
          que es la plata que realmente hay en la caja. */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: '0.75rem', flexWrap: 'wrap',
        padding: '0.6rem 1.1rem', borderBottom: '1px solid var(--bd-006)',
      }}>
        <span style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.75)' }}>
          Saldo al abrir&nbsp;
          <strong style={{ color: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}>
            {fmt(caja.saldo_apertura)}
          </strong>
        </span>
        <span style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.75)' }}>
          Saldo al cerrar&nbsp;
          <strong style={{
            color: cierre >= 0 ? 'var(--text-1)' : '#f87171',
            fontSize: '0.85rem', fontVariantNumeric: 'tabular-nums',
          }}>
            {fmt(caja.saldo_cierre)}
          </strong>
        </span>
      </div>

      {/* Las dos cajas por separado. El saldo de arriba es la suma y sirve para
          leer el flujo, pero **el cierre del día se hace contra estos dos**: los
          billetes se cuentan a mano y la cuenta se mira en el banco. */}
      {(caja.efectivo || caja.transferencia) && (
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(11rem, 1fr))',
        }}>
          {([
            ['💵', 'En billetes', caja.efectivo],
            ['🏦', 'En la cuenta', caja.transferencia],
          ] as const).map(([icono, texto, sub]) => sub && (
            <div key={texto} style={{ padding: '0.6rem 1.1rem', borderRight: '1px solid var(--bd-006)' }}>
              <div style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.75)', marginBottom: '0.2rem' }}>
                {icono} {texto}
              </div>
              <div style={{
                fontFamily: FN, fontSize: '1.15rem', letterSpacing: '0.02em',
                color: parseFloat(sub.saldo_cierre) >= 0 ? 'var(--text-1)' : '#f87171',
                fontVariantNumeric: 'tabular-nums',
              }}>
                {fmt(sub.saldo_cierre)}
              </div>
              <div style={{ fontFamily: FM, fontSize: '0.66rem', color: 'rgba(100,116,139,0.6)' }}>
                <span style={{ color: 'var(--success)' }}>+ {fmt(sub.ingresos_total)}</span>
                {'  '}
                <span style={{ color: 'var(--danger)' }}>− {fmt(sub.egresos_total)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Reportes() {
  const [preset, setPreset] = useState<Preset>('mes')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)

  function handlePreset(p: Preset) {
    setPreset(p)
    setShowPicker(p === 'custom')
  }

  const labelPersonalizado =
    customDesde && customHasta ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
    : customDesde ? `Desde ${fmtDate(customDesde)}` : 'Personalizado'

  const { desde, hasta } = getRangeForPreset(preset, customDesde, customHasta)

  const { data, isLoading, error } = useQuery({
    queryKey: ['reporte-caja', desde, hasta],
    queryFn: () => getReporteCaja(desde, hasta),
    enabled: !!desde && !!hasta,
  })

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>
      {/* Header + Filtro */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Reportes</h1>
          <p className="hidden sm:block" style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Caja diaria — ingresos y egresos por moneda</p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.4rem', position: 'relative', flexShrink: 0 }}>
          <DropdownFilter
            label="Período"
            value={preset}
            options={[
              { value: 'hoy' as Preset, label: 'Hoy' },
              { value: 'semana' as Preset, label: 'Esta semana' },
              { value: 'mes' as Preset, label: 'Este mes' },
              { value: 'custom' as Preset, label: labelPersonalizado },
            ]}
            onChange={handlePreset}
          />
          {showPicker && (
            <DateRangePicker
              from={customDesde} to={customHasta}
              onChange={(f, t) => { setCustomDesde(f); setCustomHasta(t) }}
              onClose={() => setShowPicker(false)}
            />
          )}
          <p style={{ fontFamily: FM, fontSize: '0.68rem', fontVariantNumeric: 'tabular-nums', color: 'rgba(100,116,139,0.6)', lineHeight: 1 }}>
            {fmtDate(desde)} — {fmtDate(hasta)}
          </p>
        </div>
      </div>

      {isLoading && <div style={{ textAlign: 'center', color: 'rgba(100,116,139,0.6)', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Calculando caja…</div>}
      {error && <div style={{ textAlign: 'center', color: 'var(--danger)', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar el reporte.</div>}

      {data && (
        <>
          {/* Netos destacados + ganancia de divisas */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Neto del período</p>
          <div className="grid grid-cols-2 sm:grid-cols-4" style={{ gap: '0.75rem', marginBottom: '0.6rem' }}>
            <MetricCard
              label="Neto ARS"
              value={fmtARS(data.ars.neto)}
              color={parseFloat(data.ars.neto) >= 0 ? 'green' : 'red'}
              accentColor="rgba(52,211,153,0.55)"
            />
            <MetricCard
              label="Neto USD"
              value={fmtUSD(data.usd.neto)}
              color={parseFloat(data.usd.neto) >= 0 ? 'green' : 'red'}
              accentColor="rgba(96,165,250,0.55)"
            />
            <MetricCard
              label="Ganancia divisas (FIFO)"
              value={fmtARS(data.ganancia_divisas)}
              color="indigo"
              accentColor="rgba(167,139,250,0.55)"
            />
            {/* Lo que dejaron los cheques que SALIERON de cartera en el período:
                vendidos, cobrados al vencimiento y fiados. Es un dato del
                período —la plata ya está contada en los ingresos de la caja de
                abajo—, por eso va en esta fila y no suma a ningún neto. */}
            <MetricCard
              label="Ganancia cheques"
              value={fmtARS(data.ganancia_cheques.total)}
              color="indigo"
              accentColor="rgba(251,191,36,0.55)"
              sub={`${data.ganancia_cheques.cantidad} cheque${data.ganancia_cheques.cantidad === 1 ? '' : 's'} fuera de cartera`}
            />
          </div>

          {/* De dónde salió esa ganancia, y lo que rebotó. El rechazo va acá y
              NO restado del total (decisión del dueño): el papel se le reclama
              al cliente y el desenlace todavía no se sabe. */}
          <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.6)', marginBottom: '1.5rem', lineHeight: 1.5 }}>
            Cheques — venta {fmtARS(data.ganancia_cheques.ventas)} · cobro al vencimiento{' '}
            {fmtARS(data.ganancia_cheques.cobros)} · fiado {fmtARS(data.ganancia_cheques.fiados)}
            {parseFloat(data.ganancia_cheques.rechazos) > 0 && (
              <span style={{ color: 'var(--danger)', opacity: 0.75 }}>
                {' '}· rechazados {fmtARS(data.ganancia_cheques.rechazos)} (no se descuentan)
              </span>
            )}
          </p>

          {/* Cajas por moneda */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Cierre por caja</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginBottom: '1.5rem' }}>
            <CajaBloque caja={data.ars} simbolo="ARS" />
            <CajaBloque caja={data.usd} simbolo="USD" />
          </div>

          {/* Lo que está afuera. Snapshot de hoy, no del período: un préstamo
              otorgado hace tres meses sigue en la calle aunque el reporte sea de
              hoy. Va ANTES de los pasivos —primero lo que tiene que volver,
              después lo que hay que pagar— y separado por dónde se cobra cada
              uno: los créditos en Créditos, el resto en Deudores. */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Plata en la calle (snapshot actual)</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" style={{ marginBottom: '1.5rem' }}>
            {[
              { label: 'Créditos ARS', value: fmtARS(data.plata_en_calle.creditos_ars), sub: 'préstamos por cobrar' },
              { label: 'Créditos USD', value: fmtUSD(data.plata_en_calle.creditos_usd), sub: 'préstamos por cobrar' },
              { label: 'Deudores ARS', value: fmtARS(data.plata_en_calle.deudores_ars), sub: 'fiados + otras deudas' },
              { label: 'Deudores USD', value: fmtUSD(data.plata_en_calle.deudores_usd), sub: 'otras deudas' },
            ].map(({ label, value, sub }) => (
              <SnapshotCard key={label} label={label} value={value} sub={sub} tono="entra" />
            ))}
          </div>

          {/* Lo que se debe y en qué se fue la plata, uno al lado del otro.
              OJO: no se leen igual. El de la izquierda es un saldo de hoy (no
              mira el filtro de fecha) y el de la derecha son los gastos DEL
              PERÍODO. Cada subtítulo lo aclara, porque pegados invitan a
              leerlos como si fueran la misma clase de número. */}
          <div className="grid grid-cols-1 sm:grid-cols-2" style={{ gap: '1.25rem' }}>
            <div>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Pasivos pendientes (snapshot actual)</p>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: 'Deudas ARS', value: fmtARS(data.saldo_pasivos.pendiente_ars), sub: 'cuentas a pagar' },
                  { label: 'Deudas USD', value: fmtUSD(data.saldo_pasivos.pendiente_usd), sub: 'cuentas a pagar' },
                ].map(({ label, value, sub }) => (
                  <SnapshotCard key={label} label={label} value={value} sub={sub} tono="sale" />
                ))}
              </div>
            </div>

            <div>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Gastos del período, por concepto</p>
              <GastosBloque gastos={data.gastos_periodo} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
