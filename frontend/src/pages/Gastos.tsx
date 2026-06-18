import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getGastos, createGasto } from '../api/gastos_operativos'
import { fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconPlus } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import type { GastoOperativo, Moneda } from '../types'
import DateRangePicker from '../components/DateRangePicker'
import DropdownFilter from '../components/DropdownFilter'

type PresetFecha = 'HOY' | 'SEMANA' | 'MES' | 'PERSONALIZADO'

const FM     = "'Manrope', sans-serif"
const FN     = "'Bebas Neue', sans-serif"
const FJ     = "'JetBrains Mono', monospace"
const ORANGE = '#fb923c'
const CARD   = {
  background:   'var(--surface-grad)',
  border:       '1px solid var(--bd-006)',
  boxShadow:    'var(--shadow-card)',
  borderRadius: 'var(--r-lg)',
}
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

// ── Modal nuevo gasto ─────────────────────────────────────────────────

function ModalNuevoGasto({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [concepto, setConcepto] = useState('')
  const [monto, setMonto] = useState('')
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [fechaOperacion, setFechaOperacion] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await createGasto({
        concepto: concepto.trim(),
        monto: parseFloat(monto),
        moneda,
        fecha_operacion: fechaOperacion || null,
        observaciones: observaciones.trim() || null,
      })
      toast('success', 'Gasto registrado')
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Registrar gasto</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Gasto operativo de caja</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div><label style={LABEL_STYLE}>Concepto</label><input type="text" value={concepto} onChange={(e) => setConcepto(e.target.value)} placeholder="Nafta, insumos, comida…" required autoFocus style={INPUT_STYLE} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} /></div>
            <div><label style={LABEL_STYLE}>Moneda</label><select value={moneda} onChange={(e) => setMoneda(e.target.value as Moneda)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}><option value="ARS">ARS</option><option value="USD">USD</option></select></div>
          </div>
          <div><label style={LABEL_STYLE}>Fecha <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional, hoy por defecto)</span></label><input type="date" value={fechaOperacion} onChange={(e) => setFechaOperacion(e.target.value)} style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Observaciones <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} /></div>
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
const PALETTE = ['#fb923c', '#60a5fa', '#a78bfa', '#4ade80', '#f472b6', '#fbbf24']
const BAR_MAX = 120 // px, la barra más alta

function getRango(
  preset: PresetFecha,
  customDesde: string | null,
  customHasta: string | null,
): { desde: string | null; hasta: string | null } {
  const hoy = todayISO()
  switch (preset) {
    case 'HOY':           return { desde: hoy, hasta: hoy }
    case 'SEMANA':        return { desde: weekStartISO(), hasta: hoy }
    case 'MES':           return { desde: monthStartISO(), hasta: hoy }
    case 'PERSONALIZADO': return { desde: customDesde, hasta: customHasta }
  }
}

function enRango(fecha: string, desde: string | null, hasta: string | null): boolean {
  if (desde && fecha < desde) return false
  if (hasta && fecha > hasta) return false
  return true
}

export default function Gastos() {
  const [preset, setPreset]           = useState<PresetFecha>('MES')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker]   = useState(false)
  const [mostrarNuevo, setMostrarNuevo] = useState(false)
  const queryClient = useQueryClient()

  const { data: gastos = [], isLoading } = useQuery({
    queryKey: ['gastos'],
    queryFn:  getGastos,
    refetchInterval: 30_000,
  })

  function handleNuevoSuccess() {
    setMostrarNuevo(false)
    queryClient.invalidateQueries({ queryKey: ['gastos'] })
  }

  const { desde, hasta } = getRango(preset, customDesde, customHasta)

  const gastosFiltrados = useMemo(
    () => gastos.filter(g => enRango(g.fecha_operacion, desde, hasta)),
    [gastos, desde, hasta],
  )

  const totalPeriodo = useMemo(
    () => gastosFiltrados.reduce((acc, g) => acc + parseFloat(g.monto), 0),
    [gastosFiltrados],
  )

  const porConcepto = useMemo(() => {
    const map = new Map<string, { count: number; total: number }>()
    for (const g of gastosFiltrados) {
      const ex = map.get(g.concepto) ?? { count: 0, total: 0 }
      map.set(g.concepto, { count: ex.count + 1, total: ex.total + parseFloat(g.monto) })
    }
    return Array.from(map.entries())
      .map(([concepto, v]) => ({ concepto, ...v }))
      .sort((a, b) => b.total - a.total)
  }, [gastosFiltrados])

  const porDia = useMemo(() => {
    const map = new Map<string, { subtotal: number; items: GastoOperativo[] }>()
    for (const g of gastosFiltrados) {
      const ex = map.get(g.fecha_operacion) ?? { subtotal: 0, items: [] }
      map.set(g.fecha_operacion, {
        subtotal: ex.subtotal + parseFloat(g.monto),
        items:    [...ex.items, g],
      })
    }
    return Array.from(map.entries())
      .map(([fecha, { subtotal, items }]) => ({
        fecha,
        subtotal,
        items: [...items].sort((a, b) =>
          (b.hora_operacion ?? '').localeCompare(a.hora_operacion ?? ''),
        ),
      }))
      .sort((a, b) => b.fecha.localeCompare(a.fecha))
  }, [gastosFiltrados])

  const labelPersonalizado =
    customDesde && customHasta
      ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
      : customDesde
        ? `Desde ${fmtDate(customDesde)}`
        : 'Personalizado'

  const rangoLabel =
    desde && hasta ? `${fmtDate(desde)} → ${fmtDate(hasta)}` : '–'

  function handlePreset(p: PresetFecha) {
    setPreset(p)
    setShowPicker(p === 'PERSONALIZADO')
  }

  const maxTotal = porConcepto[0]?.total ?? 1

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div style={{
        display:        'flex',
        alignItems:     'flex-start',
        justifyContent: 'space-between',
        marginBottom:   '1.25rem',
        flexWrap:       'wrap',
        gap:            '0.75rem',
      }}>
        <h1 style={{
          fontFamily:    FN,
          fontSize:      '2rem',
          letterSpacing: '0.06em',
          color:         'var(--text-1)',
          lineHeight:    1,
          margin:        0,
        }}>
          Gastos
        </h1>

        <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-end', gap: '0.75rem', flexWrap: 'wrap' }}>
          <DropdownFilter
            label="Período"
            value={preset}
            options={[
              { value: 'HOY'           as PresetFecha, label: 'Hoy' },
              { value: 'SEMANA'        as PresetFecha, label: 'Esta semana' },
              { value: 'MES'           as PresetFecha, label: 'Este mes' },
              { value: 'PERSONALIZADO' as PresetFecha, label: labelPersonalizado },
            ]}
            onChange={handlePreset}
          />
          {showPicker && (
            <DateRangePicker
              from={customDesde}
              to={customHasta}
              onChange={(f, t) => { setCustomDesde(f); setCustomHasta(t) }}
              onClose={() => setShowPicker(false)}
            />
          )}
          <div className="hidden sm:block">
            <button
              onClick={() => setMostrarNuevo(true)}
              style={{
                display:      'flex',
                alignItems:   'center',
                gap:          '0.4rem',
                fontFamily:   FM,
                fontSize:     '0.78rem',
                fontWeight:   700,
                padding:      '0.5rem 0.9rem',
                borderRadius: 'var(--r-md)',
                cursor:       'pointer',
                background:   ORANGE,
                color:        '#fff',
                border:       'none',
              }}
            >
              <IconPlus size={15} />
              Registrar gasto
            </button>
          </div>
        </div>
      </div>

      {/* ── Mobile: total en card con borde naranja ──────────────────────── */}
      <div className="sm:hidden">
        <div style={{
          ...CARD,
          borderLeft:   `3px solid ${ORANGE}`,
          padding:      '0.875rem 1rem',
          marginBottom: '1rem',
        }}>
          <p style={{
            fontFamily:     FM,
            fontSize:       '0.6rem',
            fontWeight:     700,
            letterSpacing:  '0.15em',
            textTransform:  'uppercase',
            color:          ORANGE,
            margin:         '0 0 0.2rem',
          }}>
            Total gastado en el período
          </p>
          <p style={{ fontFamily: FN, fontSize: '2rem', color: ORANGE, lineHeight: 1, margin: '0 0 0.2rem' }}>
            {isLoading ? '–' : fmtMonto(totalPeriodo, 'ARS')}
          </p>
          <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)', margin: 0 }}>
            {gastosFiltrados.length} gasto{gastosFiltrados.length !== 1 ? 's' : ''} · {rangoLabel}
          </p>
        </div>
      </div>

      {/* ── Desktop: total como texto destacado (sin caja) ───────────────── */}
      <div className="hidden sm:block" style={{ marginBottom: '1.5rem' }}>
        <p style={{
          fontFamily:    FM,
          fontSize:      '0.63rem',
          fontWeight:    700,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color:         ORANGE,
          margin:        '0 0 0.2rem',
        }}>
          Total gastado en el período
        </p>
        <p style={{ fontFamily: FN, fontSize: '3rem', color: ORANGE, lineHeight: 1, margin: '0 0 0.25rem' }}>
          {isLoading ? '–' : fmtMonto(totalPeriodo, 'ARS')}
        </p>
        <p style={{ fontFamily: FM, fontSize: '0.75rem', color: 'rgba(100,116,139,0.55)', margin: 0 }}>
          {gastosFiltrados.length} gasto{gastosFiltrados.length !== 1 ? 's' : ''} · {rangoLabel}
        </p>
      </div>

      {/* ── Loading ──────────────────────────────────────────────────────── */}
      {isLoading && (
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <SkeletonRows rows={6} />
        </div>
      )}

      {/* ── Sin gastos ───────────────────────────────────────────────────── */}
      {!isLoading && gastosFiltrados.length === 0 && (
        <div style={{ ...CARD, padding: '3rem', textAlign: 'center' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📭</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>
            Sin gastos en el período
          </p>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.4)', marginTop: '0.25rem' }}>
            Probá cambiando el filtro de período
          </p>
        </div>
      )}

      {/* ── Contenido ────────────────────────────────────────────────────── */}
      {!isLoading && gastosFiltrados.length > 0 && (
        <>
          {/* Desktop: gráfico barras verticales por concepto */}
          <div className="hidden sm:block">
            <div style={{ ...CARD, padding: '1.25rem 1.5rem 1.5rem', marginBottom: '1rem' }}>
              <p style={{
                fontFamily:    FM,
                fontSize:      '0.63rem',
                fontWeight:    700,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color:         'rgba(100,116,139,0.7)',
                margin:        '0 0 1.25rem',
              }}>
                Por concepto
              </p>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: '1rem', overflowX: 'auto', paddingBottom: '0.25rem' }}>
                {porConcepto.map(({ concepto, count, total }, idx) => {
                  const color = PALETTE[idx % PALETTE.length]
                  const barH  = Math.max(6, (total / maxTotal) * BAR_MAX)
                  return (
                    <div
                      key={concepto}
                      style={{
                        display:       'flex',
                        flexDirection: 'column',
                        alignItems:    'center',
                        minWidth:      '72px',
                        flex:          '1 0 72px',
                        maxWidth:      '140px',
                      }}
                    >
                      <p style={{
                        fontFamily:    FN,
                        fontSize:      '0.88rem',
                        letterSpacing: '0.02em',
                        color:         'var(--text-1)',
                        margin:        '0 0 0.4rem',
                        textAlign:     'center',
                        whiteSpace:    'nowrap',
                      }}>
                        {fmtMonto(total, 'ARS')}
                      </p>
                      <div style={{
                        height:       `${barH}px`,
                        width:        '100%',
                        background:   `linear-gradient(to bottom, ${color}, ${color}88)`,
                        borderRadius: '4px 4px 0 0',
                      }} />
                      <div style={{ marginTop: '0.5rem', textAlign: 'center', width: '100%' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', marginBottom: '2px' }}>
                          <span style={{
                            width:        '6px',
                            height:       '6px',
                            borderRadius: '50%',
                            background:   color,
                            flexShrink:   0,
                            display:      'inline-block',
                          }} />
                          <span style={{
                            fontFamily: FM,
                            fontSize:   '0.68rem',
                            fontWeight: 600,
                            color:      'var(--text-1)',
                            wordBreak:  'break-word',
                          }}>
                            {concepto}
                          </span>
                        </div>
                        <p style={{ fontFamily: FM, fontSize: '0.6rem', color: 'rgba(100,116,139,0.55)', margin: 0 }}>
                          {count} gasto{count !== 1 ? 's' : ''}
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Detalle por día — ambos layouts */}
          <div style={{ ...CARD, overflow: 'hidden' }}>
            {porDia.map(({ fecha, subtotal, items }) => (
              <div key={fecha}>
                {/* Franja de encabezado del día */}
                <div style={{
                  display:        'flex',
                  alignItems:     'center',
                  justifyContent: 'space-between',
                  padding:        '0.5rem 1rem',
                  background:     'var(--ov-0025)',
                  borderBottom:   '1px solid var(--bd-006)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <span style={{
                      fontFamily:    FJ,
                      fontSize:      '0.68rem',
                      fontWeight:    700,
                      letterSpacing: '0.1em',
                      textTransform: 'uppercase',
                      color:         'var(--text-1)',
                    }}>
                      {fmtDate(fecha)}
                    </span>
                    <span style={{
                      fontFamily:    FM,
                      fontSize:      '0.6rem',
                      color:         'rgba(100,116,139,0.5)',
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                    }}>
                      · {items.length} gasto{items.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <span style={{
                    fontFamily:    FN,
                    fontSize:      '1rem',
                    letterSpacing: '0.02em',
                    color:         'rgba(248,113,113,0.7)',
                  }}>
                    −{fmtMonto(subtotal, 'ARS')}
                  </span>
                </div>

                {/* Ítems del día */}
                {items.map((g) => (
                  <div
                    key={g.id}
                    onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'var(--ov-002)' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
                    style={{
                      display:      'flex',
                      alignItems:   'center',
                      gap:          '0.75rem',
                      padding:      '0.65rem 1rem',
                      borderBottom: '1px solid var(--ov-004)',
                    }}
                  >
                    {/* Avatar cuadrado con inicial del concepto */}
                    <div style={{
                      width:          '34px',
                      height:         '34px',
                      flexShrink:     0,
                      borderRadius:   'var(--r-sm)',
                      background:     'rgba(251,146,60,0.13)',
                      border:         '1px solid rgba(251,146,60,0.25)',
                      display:        'flex',
                      alignItems:     'center',
                      justifyContent: 'center',
                      fontFamily:     FN,
                      fontSize:       '1rem',
                      color:          ORANGE,
                    }}>
                      {g.concepto.charAt(0).toUpperCase()}
                    </div>

                    {/* Concepto + meta */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{
                        fontFamily: FM,
                        fontSize:   '0.82rem',
                        fontWeight: 600,
                        color:      'var(--text-1)',
                        margin:     0,
                        wordBreak:  'break-word',
                      }}>
                        {g.concepto}
                      </p>
                      {(g.hora_operacion || g.observaciones) && (
                        <p style={{
                          fontFamily: FM,
                          fontSize:   '0.68rem',
                          color:      'rgba(100,116,139,0.5)',
                          margin:     '2px 0 0',
                          wordBreak:  'break-word',
                        }}>
                          {[g.hora_operacion?.slice(0, 5), g.observaciones]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                      )}
                    </div>

                    {/* Monto */}
                    <span style={{
                      fontFamily:         FN,
                      fontSize:           '1.1rem',
                      letterSpacing:      '0.02em',
                      color:              '#f87171',
                      whiteSpace:         'nowrap',
                      flexShrink:         0,
                      fontVariantNumeric: 'tabular-nums',
                    }}>
                      −{fmtMonto(g.monto, g.moneda)}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── FAB mobile ───────────────────────────────────────────────────── */}
      <div
        className="sm:hidden"
        style={{
          position: 'fixed',
          bottom:   'calc(1.25rem + env(safe-area-inset-bottom))',
          right:    '1.25rem',
          zIndex:   51,
        }}
      >
        <button
          aria-label="Registrar gasto"
          onClick={() => setMostrarNuevo(true)}
          style={{
            width:          '52px',
            height:         '52px',
            borderRadius:   '50%',
            background:     ORANGE,
            color:          '#fff',
            border:         'none',
            cursor:         'pointer',
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            boxShadow:      '0 4px 16px rgba(251,146,60,0.4)',
          }}
        >
          <IconPlus size={22} />
        </button>
      </div>

      {mostrarNuevo && <ModalNuevoGasto onClose={() => setMostrarNuevo(false)} onSuccess={handleNuevoSuccess} />}
    </div>
  )
}
