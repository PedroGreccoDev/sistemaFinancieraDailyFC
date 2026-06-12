import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getReporteGanancias } from '../api/reportes'
import { fmtARS, fmtUSD, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import DropdownFilter from '../components/DropdownFilter'
import DateRangePicker from '../components/DateRangePicker'

type Preset = 'hoy' | 'semana' | 'mes' | 'custom'

const FN = "'Bebas Neue', sans-serif"
const FM = "'Manrope', sans-serif"
const CARD = { background: 'linear-gradient(145deg, #0c0c10 0%, #13131a 100%)', border: '1px solid rgba(255,255,255,0.06)', boxShadow: '0 4px 24px rgba(0,0,0,0.4)' }

function getRangeForPreset(preset: Preset, customDesde: string | null, customHasta: string | null) {
  const hoy = todayISO()
  if (preset === 'hoy') return { desde: hoy, hasta: hoy }
  if (preset === 'semana') return { desde: weekStartISO(), hasta: hoy }
  if (preset === 'mes') return { desde: monthStartISO(), hasta: hoy }
  return { desde: customDesde ?? hoy, hasta: customHasta ?? hoy }
}

function MetricCard({ label, value, sub, color = 'default' }: {
  label: string; value: string; sub?: string; color?: 'default' | 'green' | 'red' | 'indigo'
}) {
  const numColor = { default: '#e2e8f0', green: '#4ade80', red: '#f87171', indigo: '#818cf8' }[color]
  return (
    <div style={{ ...CARD, padding: '1rem 1.2rem' }}>
      <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
      <p style={{ fontFamily: FN, fontSize: '1.75rem', color: numColor, letterSpacing: '0.03em', lineHeight: 1, marginBottom: sub ? '0.25rem' : 0 }}>{value}</p>
      {sub && <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.55)' }}>{sub}</p>}
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

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem' }}>
        <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: '#e2e8f0', lineHeight: 1, marginBottom: '0.2rem' }}>Reportes</h1>
        <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Arqueo de caja y ganancias consolidadas</p>
      </div>

      {/* Filtros */}
      <div style={{ position: 'relative', display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '0.75rem', marginBottom: '1.5rem' }}>
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
      </div>

      {isLoading && <div style={{ textAlign: 'center', color: 'rgba(100,116,139,0.6)', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Calculando ganancias…</div>}
      {error && <div style={{ textAlign: 'center', color: '#f87171', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar el reporte.</div>}

      {data && (
        <>
          {/* Sección label */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Ganancias del período</p>

          <div className="grid grid-cols-2 gap-3" style={{ marginBottom: '1rem' }}>
            <MetricCard label="Cheques (spread)" value={fmtARS(data.ganancia_cheques)} sub="Compra-venta de cheques" color="green" />
            <MetricCard label="Préstamos (intereses)" value={fmtARS(data.ganancia_prestamos)} sub="Diferencia crédito / total" color="green" />
            <MetricCard label="Divisas (efectivo)" value={fmtARS(data.ganancia_movimientos_efectivo)} sub="Compra-venta de dólares" color="green" />
            <MetricCard label="Gastos operativos" value={fmtARS(data.gastos_operativos)} sub="Nafta, insumos, etc." color="red" />
          </div>

          {/* Totales destacados */}
          <div className="grid grid-cols-2 gap-3" style={{ marginBottom: '1.5rem' }}>
            <div style={{ ...CARD, padding: '1.1rem 1.2rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>Total bruto</p>
              <p style={{ fontFamily: FN, fontSize: '2.2rem', color: '#e2e8f0', letterSpacing: '0.03em', lineHeight: 1, marginBottom: '0.2rem' }}>{fmtARS(data.total_ganancias)}</p>
              <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>Sin descontar gastos</p>
            </div>
            <div style={{ background: 'linear-gradient(145deg, #3730a3, #4338ca)', border: '1px solid rgba(99,102,241,0.4)', boxShadow: '0 4px 24px rgba(99,102,241,0.2)', padding: '1.1rem 1.2rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(199,210,254,0.7)', marginBottom: '0.3rem' }}>Neto del período</p>
              <p style={{ fontFamily: FN, fontSize: '2.2rem', color: '#fff', letterSpacing: '0.03em', lineHeight: 1, marginBottom: '0.2rem' }}>{fmtARS(data.neto)}</p>
              <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(199,210,254,0.55)' }}>Ganancias − gastos</p>
            </div>
          </div>

          {/* Tabla desglose */}
          <div style={{ ...CARD, overflow: 'hidden', marginBottom: '1.5rem' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '320px' }}>
                <thead>
                  <tr>
                    <th style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left', background: 'rgba(255,255,255,0.025)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>Módulo</th>
                    <th style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'right', background: 'rgba(255,255,255,0.025)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>Importe</th>
                    <th style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'right', background: 'rgba(255,255,255,0.025)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>% del bruto</th>
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
                        onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'}
                        onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                        <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.04)', color: '#e2e8f0' }}>{row.label}</td>
                        <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.04)', textAlign: 'right', fontWeight: 600, color: row.egreso ? '#f87171' : '#4ade80' }}>
                          {row.egreso ? '−' : ''}{fmtARS(row.value)}
                        </td>
                        <td style={{ fontFamily: FM, fontSize: '0.78rem', padding: '0.65rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.04)', textAlign: 'right', color: 'rgba(100,116,139,0.6)' }}>
                          {row.egreso ? '−' : ''}{pct}%
                        </td>
                      </tr>
                    )
                  })}
                  <tr style={{ background: 'rgba(255,255,255,0.025)' }}>
                    <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', fontWeight: 700, color: '#e2e8f0' }}>Neto</td>
                    <td style={{ fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', textAlign: 'right', fontWeight: 700, color: '#818cf8' }}>{fmtARS(data.neto)}</td>
                    <td style={{ fontFamily: FM, fontSize: '0.78rem', padding: '0.65rem 1rem', textAlign: 'right', color: 'rgba(100,116,139,0.5)' }}>—</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Pasivos snapshot */}
          <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)', marginBottom: '0.75rem' }}>Pasivos pendientes (snapshot actual)</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Deudas pendientes ARS', value: fmtARS(data.saldo_pasivos.pendiente_ars), sub: 'Lo que el negocio debe (en $)' },
              { label: 'Deudas pendientes USD', value: fmtUSD(data.saldo_pasivos.pendiente_usd), sub: 'Lo que el negocio debe (en U$D)' },
            ].map(({ label, value, sub }) => (
              <div key={label} style={{ ...CARD, padding: '1rem 1.2rem' }}>
                <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
                <p style={{ fontFamily: FN, fontSize: '1.75rem', color: '#f87171', letterSpacing: '0.03em', lineHeight: 1, marginBottom: '0.2rem' }}>{value}</p>
                <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
