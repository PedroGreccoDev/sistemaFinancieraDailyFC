import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getReporteCaja, getCobrosHistorial } from '../api/reportes'
import { fmtARS, fmtUSD, fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import DropdownFilter from '../components/DropdownFilter'
import DateRangePicker from '../components/DateRangePicker'
import type { CajaMoneda, Moneda } from '../types'

type Preset = 'hoy' | 'semana' | 'mes' | 'custom'

const FN = "'Bebas Neue', sans-serif"
const FM = "'Manrope', sans-serif"
const FJ_OR_MONO = "'JetBrains Mono', monospace"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }

// Etiquetas legibles de cada categoría de movimiento de caja.
const CATEGORIA_LABEL: Record<string, string> = {
  COBRO_CUOTA: 'Cobro de cuota',
  COBRO_FIADO: 'Cobro de fiado',
  VENTA_CHEQUE: 'Venta de cheque',
  COBRO_CHEQUE: 'Cobro de cheque',
  COMPRA_CHEQUE: 'Compra de cheque',
  COMPRA_USD: 'Compra de USD',
  VENTA_USD: 'Venta de USD',
  OTORGAMIENTO_PRESTAMO: 'Préstamo otorgado',
  GASTO: 'Gasto',
  PAGO_PASIVO: 'Pago de deuda',
  VUELTO_PASIVO: 'Vuelto a cliente',
}

function getRangeForPreset(preset: Preset, customDesde: string | null, customHasta: string | null) {
  const hoy = todayISO()
  if (preset === 'hoy') return { desde: hoy, hasta: hoy }
  if (preset === 'semana') return { desde: weekStartISO(), hasta: hoy }
  if (preset === 'mes') return { desde: monthStartISO(), hasta: hoy }
  return { desde: customDesde ?? hoy, hasta: customHasta ?? hoy }
}

function MetricCard({ label, value, color = 'default', accentColor, prefix }: {
  label: string
  value: string
  color?: 'default' | 'green' | 'red' | 'indigo'
  accentColor?: string
  prefix?: string
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
    </div>
  )
}

function CajaBloque({ caja, simbolo }: { caja: CajaMoneda; simbolo: 'ARS' | 'USD' }) {
  const fmt = (v: string | number) => fmtMonto(v, simbolo as Moneda)
  const neto = parseFloat(caja.neto)
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

      {/* Detalle de líneas */}
      {caja.lineas.length === 0 ? (
        <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.55)', padding: '1.2rem 1.1rem' }}>
          Sin movimientos en el período.
        </p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '320px' }}>
            <tbody>
              {caja.lineas.map((l, i) => {
                const ingreso = l.tipo === 'INGRESO'
                return (
                  <tr key={i}
                    onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                    onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                    <td style={{ fontFamily: FJ_OR_MONO, fontSize: '0.7rem', padding: '0.55rem 1.1rem', borderBottom: '1px solid var(--ov-004)', color: 'rgba(100,116,139,0.7)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                      {fmtDate(l.fecha)}
                    </td>
                    <td style={{ fontFamily: FM, fontSize: '0.8rem', padding: '0.55rem 1.1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)' }}>
                      <span style={{ fontWeight: 600 }}>{CATEGORIA_LABEL[l.categoria] ?? l.categoria}</span>
                      {l.medio_pago && (
                        <span style={{ marginLeft: '0.4rem', fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.65)' }}>
                          {l.medio_pago === 'TRANSFERENCIA' ? 'transferencia' : 'efectivo'}
                          {l.cotizacion != null && ` · @ ${l.cotizacion}`}
                        </span>
                      )}
                      {l.detalle && (
                        <span style={{ display: 'block', fontSize: '0.68rem', color: 'rgba(100,116,139,0.55)' }}>{l.detalle}</span>
                      )}
                    </td>
                    <td style={{
                      fontFamily: FM, fontSize: '0.82rem', padding: '0.55rem 1.1rem', borderBottom: '1px solid var(--ov-004)',
                      textAlign: 'right', fontWeight: 600, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums',
                      color: ingreso ? 'var(--success)' : 'var(--danger)',
                    }}>
                      {ingreso ? '+ ' : '− '}{fmt(l.monto)}
                      {l.ganancia != null && (
                        <span style={{ display: 'block', fontSize: '0.62rem', color: 'rgba(100,116,139,0.5)' }}>
                          ganancia {fmtARS(l.ganancia)}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
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

  const { data: historial } = useQuery({
    queryKey: ['cobros-historial', desde, hasta],
    queryFn: () => getCobrosHistorial(desde, hasta),
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
          <div className="grid grid-cols-2 sm:grid-cols-3" style={{ gap: '0.75rem', marginBottom: '1.5rem' }}>
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
          </div>

          {/* Cajas por moneda */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Movimientos de caja</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginBottom: '1.5rem' }}>
            <CajaBloque caja={data.ars} simbolo="ARS" />
            <CajaBloque caja={data.usd} simbolo="USD" />
          </div>

          {/* Historial de cobros de cuotas */}
          {historial && historial.length > 0 && (
            <>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Historial de cobros de cuotas</p>
              <div style={{ ...CARD, overflow: 'hidden', marginBottom: '1.5rem' }}>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '320px' }}>
                    <thead>
                      <tr>
                        {['Cliente', 'Cuota', 'Fecha cobro', 'Importe'].map((h, i) => (
                          <th key={h} style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: i === 3 ? 'right' : 'left', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {historial.map((item) => (
                        <tr key={item.cuota_id}
                          onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                          onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                          <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.6rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.cliente_nombre}</td>
                          <td style={{ fontFamily: FM, fontSize: '0.78rem', padding: '0.6rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'rgba(100,116,139,0.7)', whiteSpace: 'nowrap' }}>
                            Cuota {item.numero_cuota}
                            <span style={{ display: 'block', fontSize: '0.65rem', color: 'rgba(100,116,139,0.45)' }}>vence {fmtDate(item.fecha_vencimiento)}</span>
                          </td>
                          <td style={{ fontFamily: FM, fontSize: '0.78rem', padding: '0.6rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'rgba(100,116,139,0.7)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>{fmtDate(item.fecha_cobro)}</td>
                          <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.6rem 1rem', borderBottom: '1px solid var(--ov-004)', textAlign: 'right', fontWeight: 600, color: 'var(--text-1)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                            {fmtMonto(item.monto, item.moneda as Moneda)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          {/* Pasivos snapshot */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Pasivos pendientes (snapshot actual)</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:max-w-xl">
            {[
              { label: 'Deudas pendientes ARS', value: fmtARS(data.saldo_pasivos.pendiente_ars), sub: 'cuentas a pagar' },
              { label: 'Deudas pendientes USD', value: fmtUSD(data.saldo_pasivos.pendiente_usd), sub: 'cuentas a pagar' },
            ].map(({ label, value, sub }) => (
              <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem', minWidth: 0 }}>
                <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
                <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color: 'var(--danger)', letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere', fontVariantNumeric: 'tabular-nums' }}>{value}</p>
                <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
