import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getChequeCartera, getCheques, chequeFotoUrl } from '../api/cheques'
import { fmtARS, fmtDate, daysUntil, todayISO, weekStartISO, monthStartISO, yearStartISO } from '../lib/fmt'
import { btnBordered } from '../lib/ui'
import { IconRefresh, IconCamera } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import ChequeFotoModal from '../components/ChequeFotoModal'
import type { Cheque } from '../types'
import DropdownFilter from '../components/DropdownFilter'
import DateRangePicker from '../components/DateRangePicker'

type FilterPreset = 'hoy' | 'semana' | 'mes' | 'anio' | 'custom'

const FN = "'Bebas Neue', sans-serif"
const FM = "'Manrope', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const TH = { fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' as const, color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left' as const, background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)', whiteSpace: 'nowrap' as const }
const TD = { fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)' }

function presetRange(preset: FilterPreset, desde: string | null, hasta: string | null): [string, string] {
  const hoy = todayISO()
  if (preset === 'hoy')    return [hoy, hoy]
  if (preset === 'semana') return [weekStartISO(), hoy]
  if (preset === 'mes')    return [monthStartISO(), hoy]
  if (preset === 'anio')   return [yearStartISO(), hoy]
  return [desde ?? hoy, hasta ?? hoy]
}

function filterByRange(cheques: Cheque[], start: string, end: string): Cheque[] {
  return cheques.filter(c => {
    if (!c.ultimo_evento_manual_at) return false
    const fecha = c.ultimo_evento_manual_at.slice(0, 10)
    return fecha >= start && fecha <= end
  })
}

function diasBadge(dias: number | null) {
  if (dias === null) return <span style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)' }}>Sin fecha</span>
  const s = (color: string, label: string) => (
    <span style={{ fontFamily: FM, fontSize: '0.7rem', fontWeight: 700, color, background: `${color}18`, border: `1px solid ${color}35`, padding: '1px 7px' }}>{label}</span>
  )
  if (dias < 0)   return s('#f87171', `Vencido ${Math.abs(dias)}d`)
  if (dias === 0) return s('#fb923c', 'Hoy')
  if (dias <= 7)  return s('#fbbf24', `${dias}d`)
  if (dias <= 30) return s('#a3e635', `${dias}d`)
  return s('#4ade80', `${dias}d`)
}

function totalCartera(cheques: Cheque[]): number {
  return cheques.reduce((acc, c) => acc + parseFloat(c.monto), 0)
}

/** Miniatura clickeable de la foto del cheque (solo si tiene_foto). */
function FotoThumb({ cheque, onOpen, size = 52 }: { cheque: Cheque; onOpen: (c: Cheque) => void; size?: number }) {
  if (!cheque.tiene_foto) {
    return <span style={{ display: 'inline-block', width: size, height: size, flexShrink: 0 }} />
  }
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onOpen(cheque) }}
      title="Ver foto del cheque"
      style={{ padding: 0, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', overflow: 'hidden', cursor: 'pointer', width: size, height: size, flexShrink: 0, background: 'var(--ov-0025)', display: 'block' }}
    >
      <img src={chequeFotoUrl(cheque.id)} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
    </button>
  )
}

export default function Cartera() {
  const [preset, setPreset] = useState<FilterPreset>('mes')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)
  const [fotoCheque, setFotoCheque] = useState<Cheque | null>(null)

  function handlePreset(p: FilterPreset) {
    setPreset(p)
    if (p !== 'custom') setShowPicker(false)
    else setShowPicker(true)
  }

  const labelPersonalizado =
    customDesde && customHasta ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
    : customDesde ? `Desde ${fmtDate(customDesde)}` : 'Personalizado'

  const { data: cheques, isLoading, error, refetch } = useQuery({ queryKey: ['cartera'], queryFn: getChequeCartera, refetchInterval: 30_000 })
  const { data: vendidos } = useQuery({ queryKey: ['cheques-vendidos'], queryFn: () => getCheques('VENDIDO'), refetchInterval: 60_000 })

  const sorted = cheques
    ? [...cheques].sort((a, b) => {
        if (!a.fecha_pago && !b.fecha_pago) return 0
        if (!a.fecha_pago) return 1
        if (!b.fecha_pago) return -1
        return a.fecha_pago.localeCompare(b.fecha_pago)
      })
    : []

  const [rangeStart, rangeEnd] = presetRange(preset, customDesde, customHasta)
  const filteredVendidos = vendidos
    ? [...filterByRange(vendidos, rangeStart, rangeEnd)].sort((a, b) => (b.ultimo_evento_manual_at ?? '').localeCompare(a.ultimo_evento_manual_at ?? ''))
    : []
  const totalGanancia = filteredVendidos.reduce((acc, c) => acc + parseFloat(c.ganancia), 0)

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>

      {/* Header cartera */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Cartera</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Cheques en stock</p>
        </div>
        <button onClick={() => refetch()} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}>
          <IconRefresh size={14} />Actualizar
        </button>
      </div>

      {/* KPIs */}
      {cheques && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
          {[
            { label: 'En cartera', value: String(cheques.length), color: 'var(--text-strong)', sub: 'cheque(s) en stock' },
            { label: 'Total', value: fmtARS(totalCartera(cheques)), color: 'var(--text-strong)', sub: 'valor nominal' },
          ].map(({ label, value, color, sub }) => (
            <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
              <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color, letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
              <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tabla cartera */}
      <div style={{ ...CARD, overflow: 'hidden', marginBottom: '2.5rem' }}>
        {isLoading && <SkeletonRows rows={6} />}
        {error && <div style={{ padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar la cartera.</div>}
        {cheques && cheques.length === 0 && <div style={{ padding: '3rem', textAlign: 'center', color: 'rgba(100,116,139,0.6)', fontFamily: FM, fontSize: '0.82rem' }}>La cartera está vacía</div>}
        {sorted.length > 0 && (
          <>
          {/* Mobile: tarjetas */}
          <div className="sm:hidden">
            {sorted.map((cheque) => {
              const dias = cheque.fecha_pago ? daysUntil(cheque.fecha_pago) : null
              return (
                <div key={cheque.id} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', padding: '0.8rem 1rem', borderBottom: '1px solid var(--ov-004)' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.65rem', minWidth: 0 }}>
                    {cheque.tiene_foto && <FotoThumb cheque={cheque} onOpen={setFotoCheque} size={60} />}
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem', color: 'var(--text-1)', wordBreak: 'break-word' }}>{cheque.nro_cheque}</p>
                      <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.7)', marginTop: '2px' }}>Pago {fmtDate(cheque.fecha_pago)}</p>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <p style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-1)' }}>{fmtARS(cheque.monto)}</p>
                    <div style={{ marginTop: '4px' }}>{diasBadge(dias)}</div>
                  </div>
                </div>
              )
            })}
          </div>
          {/* Desktop: tabla */}
          <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '540px' }}>
              <thead>
                <tr>
                  <th style={{ ...TH, width: '76px', textAlign: 'center' }} aria-label="Foto">
                    <span style={{ display: 'inline-flex', color: 'rgba(100,116,139,0.7)' }}><IconCamera size={14} /></span>
                  </th>
                  <th style={TH}>Nº Cheque</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Monto</th>
                  <th style={{ ...TH, textAlign: 'right' }} className="hidden sm:table-cell">Compra %</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Fecha pago</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Vence</th>
                  <th style={TH} className="hidden sm:table-cell">Ingresado</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((cheque) => {
                  const dias = cheque.fecha_pago ? daysUntil(cheque.fecha_pago) : null
                  return (
                    <tr key={cheque.id} style={{ transition: 'background 0.1s' }}
                      onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                      onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                      <td style={{ ...TD, width: '76px', padding: '0.5rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'center' }}><FotoThumb cheque={cheque} onOpen={setFotoCheque} /></div>
                      </td>
                      <td style={{ ...TD, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.78rem' }}>{cheque.nro_cheque}</td>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 600 }}>{fmtARS(cheque.monto)}</td>
                      <td style={{ ...TD, textAlign: 'right', color: 'rgba(148,163,184,0.7)' }} className="hidden sm:table-cell">{parseFloat(cheque.porcentaje_compra).toFixed(2)}%</td>
                      <td style={{ ...TD, textAlign: 'center', color: 'rgba(148,163,184,0.7)' }}>{fmtDate(cheque.fecha_pago)}</td>
                      <td style={{ ...TD, textAlign: 'center' }}>{diasBadge(dias)}</td>
                      <td style={{ ...TD, color: 'rgba(100,116,139,0.6)', fontSize: '0.72rem' }} className="hidden sm:table-cell">{fmtDate(cheque.created_at.slice(0, 10))}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>

      {/* Historial de ventas */}
      <div style={{ marginBottom: '1.25rem', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Historial de Ventas</h2>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Cheques vendidos por período</p>
        </div>
      </div>

      <div style={{ position: 'relative', display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '0.75rem', marginBottom: '1rem' }}>
        <DropdownFilter
          label="Período"
          value={preset}
          options={[
            { value: 'hoy' as FilterPreset, label: 'Hoy' },
            { value: 'semana' as FilterPreset, label: 'Esta semana' },
            { value: 'mes' as FilterPreset, label: 'Este mes' },
            { value: 'anio' as FilterPreset, label: 'Este año' },
            { value: 'custom' as FilterPreset, label: labelPersonalizado },
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

      <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
        {[
          { label: 'Cheques vendidos', value: String(filteredVendidos.length), color: 'var(--text-strong)', sub: 'en el período' },
          { label: 'Ganancia del período', value: fmtARS(totalGanancia), color: '#4ade80', sub: 'spread acumulado' },
        ].map(({ label, value, color, sub }) => (
          <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
            <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color, letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
            <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
          </div>
        ))}
      </div>

      <div style={{ ...CARD, overflow: 'hidden' }}>
        {filteredVendidos.length === 0 ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'rgba(100,116,139,0.6)', fontFamily: FM, fontSize: '0.82rem' }}>Sin ventas en el período</div>
        ) : (
          <>
          {/* Mobile: tarjetas */}
          <div className="sm:hidden">
            {filteredVendidos.map((c) => {
              return (
                <div key={c.id} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', padding: '0.8rem 1rem', borderBottom: '1px solid var(--ov-004)' }}>
                  <div style={{ minWidth: 0 }}>
                    <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem', color: 'var(--text-1)', wordBreak: 'break-word' }}>{c.nro_cheque}</p>
                    <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.7)', marginTop: '2px' }}>
                      {fmtARS(c.monto)} · {fmtDate(c.ultimo_evento_manual_at?.slice(0, 10) ?? null)}
                    </p>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>Ganancia</p>
                    <p style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: '#4ade80', marginTop: '2px' }}>{fmtARS(c.ganancia)}</p>
                  </div>
                </div>
              )
            })}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.8rem 1rem', background: 'var(--ov-0025)' }}>
              <span style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 700, color: 'rgba(148,163,184,0.8)' }}>Total ganancia</span>
              <span style={{ fontFamily: FM, fontSize: '0.9rem', fontWeight: 700, color: '#4ade80' }}>{fmtARS(totalGanancia)}</span>
            </div>
          </div>
          {/* Desktop: tabla */}
          <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '620px' }}>
              <thead>
                <tr>
                  <th style={TH}>Nº Cheque</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Monto</th>
                  <th style={{ ...TH, textAlign: 'right' }} className="hidden sm:table-cell">% Compra</th>
                  <th style={{ ...TH, textAlign: 'right' }} className="hidden sm:table-cell">% Venta</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Ganancia</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Fecha venta</th>
                </tr>
              </thead>
              <tbody>
                {filteredVendidos.map(c => {
                  return (
                    <tr key={c.id}
                      onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                      onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                      <td style={{ ...TD, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.78rem' }}>{c.nro_cheque}</td>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 600 }}>{fmtARS(c.monto)}</td>
                      <td style={{ ...TD, textAlign: 'right', color: 'rgba(148,163,184,0.65)' }} className="hidden sm:table-cell">{parseFloat(c.porcentaje_compra).toFixed(2)}%</td>
                      <td style={{ ...TD, textAlign: 'right', color: 'rgba(148,163,184,0.65)' }} className="hidden sm:table-cell">
                        {c.porcentaje_venta !== null ? `${parseFloat(c.porcentaje_venta).toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 600, color: '#4ade80' }}>{fmtARS(c.ganancia)}</td>
                      <td style={{ ...TD, textAlign: 'center', color: 'rgba(148,163,184,0.65)', fontSize: '0.72rem' }}>
                        {fmtDate(c.ultimo_evento_manual_at?.slice(0, 10) ?? null)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '1px solid var(--bd-010)', background: 'var(--ov-0025)' }}>
                  <td colSpan={4} style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'rgba(148,163,184,0.8)', borderBottom: 'none' }} className="hidden sm:table-cell">Total</td>
                  <td colSpan={4} style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'rgba(148,163,184,0.8)', borderBottom: 'none' }} className="sm:hidden">Total</td>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#4ade80', borderBottom: 'none' }}>{fmtARS(totalGanancia)}</td>
                  <td style={{ ...TD, borderBottom: 'none' }} />
                </tr>
              </tfoot>
            </table>
          </div>
          </>
        )}
      </div>

      {fotoCheque && <ChequeFotoModal cheque={fotoCheque} onClose={() => setFotoCheque(null)} />}
    </div>
  )
}
