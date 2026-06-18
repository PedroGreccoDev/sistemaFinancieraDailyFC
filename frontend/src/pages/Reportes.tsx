import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getReporteGanancias, getCobrosHistorial } from '../api/reportes'
import { fmtARS, fmtUSD, fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import DropdownFilter from '../components/DropdownFilter'
import DateRangePicker from '../components/DateRangePicker'
import type { Moneda } from '../types'

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
      padding: '0.7rem 1rem',
      minWidth: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: '0.6rem',
      ...(accentColor ? { borderLeft: `3px solid ${accentColor}` } : {}),
    }}>
      <p style={{ fontFamily: FM, fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', minWidth: 0 }}>{label}</p>
      <p style={{ fontFamily: FN, fontSize: 'clamp(1.2rem, 4vw, 1.7rem)', color: numColor, letterSpacing: '0.02em', lineHeight: 1.05, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', flexShrink: 0 }}>
        {prefix}{value}
      </p>
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
    if (p !== 'custom') setShowPicker(false)
    else setShowPicker(true)
  }

  const labelPersonalizado =
    customDesde && customHasta ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
    : customDesde ? `Desde ${fmtDate(customDesde)}` : 'Personalizado'

  const { desde, hasta } = getRangeForPreset(preset, customDesde, customHasta)

  const { data, isLoading, error } = useQuery({
    queryKey: ['reporte', desde, hasta],
    queryFn: () => getReporteGanancias(desde, hasta),
    enabled: !!desde && !!hasta,
  })

  const { data: historial } = useQuery({
    queryKey: ['cobros-historial', desde, hasta],
    queryFn: () => getCobrosHistorial(desde, hasta),
    enabled: !!desde && !!hasta,
  })

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>
      {/* Header + Filtro */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Reportes</h1>
          <p className="hidden sm:block" style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Arqueo de caja y ganancias consolidadas</p>
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

      {isLoading && <div style={{ textAlign: 'center', color: 'rgba(100,116,139,0.6)', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Calculando ganancias…</div>}
      {error && <div style={{ textAlign: 'center', color: 'var(--danger)', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar el reporte.</div>}

      {data && (
        <>
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Ganancias del período</p>

          {/* Grilla 2×3 mobile / 3×2 desktop */}
          <div className="grid grid-cols-2 sm:grid-cols-3" style={{ gap: '0.75rem', marginBottom: '1.5rem' }}>
            <MetricCard
              label="Cheques (spread)"
              value={fmtARS(data.ganancia_cheques)}
              color="default"
              accentColor="rgba(34,197,94,0.55)"
            />
            <MetricCard
              label="Préstamos (intereses)"
              value={fmtARS(data.ganancia_prestamos)}
              color="default"
              accentColor="rgba(34,197,94,0.55)"
            />
            <MetricCard
              label="Divisas (efectivo)"
              value={fmtARS(data.ganancia_movimientos_efectivo)}
              color="default"
              accentColor="rgba(34,197,94,0.55)"
            />
            <MetricCard
              label="Gastos operativos"
              value={fmtARS(data.gastos_operativos)}
              color="red"
              accentColor="rgba(239,68,68,0.55)"
              prefix="− "
            />
            <MetricCard
              label="Total bruto"
              value={fmtARS(data.total_ganancias)}
              color="green"
              accentColor="var(--bd-008)"
            />
            {/* Neto: card especial con gradiente índigo */}
            <div className="lift" style={{
              background: 'linear-gradient(145deg, #3730a3, #4338ca)',
              border: '1px solid rgba(99,102,241,0.4)',
              borderLeft: '3px solid rgba(129,140,248,0.6)',
              boxShadow: '0 4px 24px rgba(99,102,241,0.2)',
              borderRadius: 'var(--r-lg)',
              padding: '0.7rem 1rem',
              minWidth: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '0.6rem',
            }}>
              <p style={{ fontFamily: FM, fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(199,210,254,0.7)', minWidth: 0 }}>Neto del período</p>
              <p style={{ fontFamily: FN, fontSize: 'clamp(1.2rem, 4vw, 1.7rem)', color: '#fff', letterSpacing: '0.02em', lineHeight: 1.05, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', flexShrink: 0 }}>{fmtARS(data.neto)}</p>
            </div>
          </div>

          {/* Tabla desglose */}
          <div style={{ ...CARD, overflow: 'hidden', marginBottom: '1.5rem' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '320px' }}>
                <thead>
                  <tr>
                    <th style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)' }}>Módulo</th>
                    <th style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'right', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)' }}>Importe</th>
                    <th style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'right', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)' }}>% del bruto</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: 'Cheques', value: data.ganancia_cheques, egreso: false },
                    { label: 'Préstamos', value: data.ganancia_prestamos, egreso: false },
                    { label: 'Divisas', value: data.ganancia_movimientos_efectivo, egreso: false },
                    { label: 'Gastos operativos', value: data.gastos_operativos, egreso: true },
                  ].map((row) => {
                    const pct = parseFloat(data.total_ganancias) > 0
                      ? ((parseFloat(row.value) / parseFloat(data.total_ganancias)) * 100).toFixed(1)
                      : '0.0'
                    return (
                      <tr key={row.label}
                        onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                        onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                        <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)' }}>{row.label}</td>
                        <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', textAlign: 'right', fontWeight: 600, color: row.egreso ? 'var(--danger)' : 'var(--text-1)', fontVariantNumeric: 'tabular-nums' }}>
                          {row.egreso ? '−' : ''}{fmtARS(row.value)}
                        </td>
                        <td style={{ fontFamily: FM, fontSize: '0.78rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', textAlign: 'right', color: 'rgba(100,116,139,0.6)', fontVariantNumeric: 'tabular-nums' }}>
                          {row.egreso ? '−' : ''}{pct}%
                        </td>
                      </tr>
                    )
                  })}
                  <tr style={{ background: 'var(--ov-0025)' }}>
                    <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', fontWeight: 700, color: 'var(--text-1)', borderTop: '1px solid var(--bd-008)' }}>Neto</td>
                    <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', textAlign: 'right', fontWeight: 700, color: '#818cf8', fontVariantNumeric: 'tabular-nums', borderTop: '1px solid var(--bd-008)' }}>{fmtARS(data.neto)}</td>
                    <td style={{ fontFamily: FM, fontSize: '0.78rem', padding: '0.65rem 1rem', textAlign: 'right', color: 'rgba(100,116,139,0.5)', fontVariantNumeric: 'tabular-nums', borderTop: '1px solid var(--bd-008)' }}>—</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Gráfico de barras */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Distribución del período</p>
          <div style={{ ...CARD, padding: '1.2rem 1.3rem', marginBottom: '1.5rem' }}>
            {(() => {
              const rows = [
                { label: 'Cheques',    value: parseFloat(data.ganancia_cheques),                 color: 'var(--success)' },
                { label: 'Préstamos', value: parseFloat(data.ganancia_prestamos),               color: 'var(--success)' },
                { label: 'Divisas',   value: parseFloat(data.ganancia_movimientos_efectivo),    color: 'var(--success)' },
                { label: 'Gastos',    value: parseFloat(data.gastos_operativos),                color: 'var(--danger)'  },
              ]
              const max = Math.max(1, ...rows.map((r) => Math.abs(r.value)))
              return rows.map((r, i) => (
                <div key={r.label} style={{ marginBottom: i === rows.length - 1 ? 0 : '0.85rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.74rem', marginBottom: '0.35rem' }}>
                    <span style={{ color: 'rgba(100,116,139,0.85)' }}>{r.label}</span>
                    <span style={{ color: 'var(--text-1)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                      {r.color === 'var(--danger)' ? '−' : ''}{fmtARS(r.value)}
                    </span>
                  </div>
                  <div style={{ height: '9px', background: 'var(--ov-004)', borderRadius: 999, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${(Math.abs(r.value) / max) * 100}%`, minWidth: 3, background: r.color, borderRadius: 999, transition: 'width 0.5s cubic-bezier(0.16,1,0.3,1)' }} />
                  </div>
                </div>
              ))
            })()}
          </div>

          {/* Cobros de cuotas (flujo de caja) */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Cobros del período</p>
          <div className="grid grid-cols-1 sm:grid-cols-3" style={{ gap: '0.75rem', marginBottom: '1.5rem' }}>
            <MetricCard
              label="Cuotas cobradas ARS"
              value={fmtARS(data.cobros_cuotas_ars)}
              color="default"
              accentColor="rgba(52,211,153,0.5)"
            />
            <MetricCard
              label="Cuotas cobradas USD"
              value={fmtUSD(data.cobros_cuotas_usd)}
              color="default"
              accentColor="rgba(52,211,153,0.5)"
            />
            <div className="lift" style={{ ...CARD, padding: '0.7rem 1rem', minWidth: 0, display: 'flex', alignItems: 'center', borderLeft: '3px solid rgba(52,211,153,0.2)' }}>
              <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.6)', lineHeight: 1.5 }}>
                Capital + interés recibidos. No afecta las ganancias — la ganancia se imputa al crear el préstamo.
              </p>
            </div>
          </div>

          {/* Historial de cobros */}
          {historial && historial.length > 0 && (
            <>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Historial de cobros</p>
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
                    <tfoot>
                      <tr style={{ background: 'var(--ov-0025)' }}>
                        <td colSpan={3} style={{ fontFamily: FM, fontSize: '0.75rem', padding: '0.6rem 1rem', fontWeight: 700, color: 'var(--text-1)', borderTop: '1px solid var(--bd-008)' }}>
                          Total ({historial.length} cobro{historial.length !== 1 ? 's' : ''})
                        </td>
                        <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.6rem 1rem', textAlign: 'right', fontWeight: 700, color: '#34d399', fontVariantNumeric: 'tabular-nums', borderTop: '1px solid var(--bd-008)', whiteSpace: 'nowrap' }}>
                          {fmtARS(data.cobros_cuotas_ars)}{parseFloat(data.cobros_cuotas_usd) > 0 ? ` + ${fmtUSD(data.cobros_cuotas_usd)}` : ''}
                        </td>
                      </tr>
                    </tfoot>
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
