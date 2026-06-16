import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getMovimientos } from '../api/movimientos'
import { getGastos } from '../api/gastos_operativos'
import { getCheques } from '../api/cheques'
import { getPrestamos } from '../api/prestamos'
import { fmtUSD, fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import { btnBordered } from '../lib/ui'
import { IconRefresh } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import type { MovimientoEfectivo, GastoOperativo, Cheque, Prestamo } from '../types'
import DateRangePicker from '../components/DateRangePicker'
import DropdownFilter from '../components/DropdownFilter'

type Seccion = 'TODOS' | 'DIVISAS' | 'GASTOS' | 'CHEQUES' | 'PRESTAMOS'
type PresetFecha = 'HOY' | 'SEMANA' | 'MES' | 'PERSONALIZADO'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }

interface MovimientoUnificado {
  id: string
  seccion: Exclude<Seccion, 'TODOS'>
  fecha: string
  descripcion: string
  detalle: string
  monto: string
  moneda: 'ARS' | 'USD'
  esGasto: boolean
}

const SECCION_CONFIG: Record<Exclude<Seccion, 'TODOS'>, { label: string; color: string; bg: string }> = {
  DIVISAS:   { label: 'Divisas',   color: '#60a5fa', bg: 'rgba(96,165,250,0.12)' },
  GASTOS:    { label: 'Gastos',    color: '#fb923c', bg: 'rgba(251,146,60,0.12)' },
  CHEQUES:   { label: 'Cheques',   color: '#a78bfa', bg: 'rgba(167,139,250,0.12)' },
  PRESTAMOS: { label: 'Préstamos', color: '#4ade80', bg: 'rgba(74,222,128,0.12)' },
}

function normalizar(
  divisas: MovimientoEfectivo[],
  gastos: GastoOperativo[],
  cheques: Cheque[],
  prestamos: Prestamo[],
): MovimientoUnificado[] {
  const items: MovimientoUnificado[] = []

  for (const m of divisas) {
    const ganancia = parseFloat(m.ganancia)
    const cotiz = parseFloat(m.cotizacion_aplicada).toLocaleString('es-AR', { minimumFractionDigits: 2 })
    items.push({
      id: m.id, seccion: 'DIVISAS', fecha: m.fecha_operacion.slice(0, 10),
      descripcion: m.tipo === 'COMPRA' ? 'Compra USD' : 'Venta USD',
      detalle: `${fmtUSD(m.monto)} · cotiz. $${cotiz}`,
      monto: m.ganancia, moneda: 'ARS', esGasto: ganancia < 0,
    })
  }

  for (const g of gastos) {
    const hora = g.hora_operacion ? g.hora_operacion.slice(0, 5) : ''
    const detalle = [hora, g.observaciones ?? ''].filter(Boolean).join(' · ')
    items.push({
      id: g.id, seccion: 'GASTOS', fecha: g.fecha_operacion,
      descripcion: g.concepto, detalle,
      monto: g.monto, moneda: g.moneda, esGasto: true,
    })
  }

  for (const c of cheques) {
    items.push({
      id: c.id, seccion: 'CHEQUES', fecha: c.created_at.slice(0, 10),
      descripcion: `Nº ${c.nro_cheque}${c.banco ? ` · ${c.banco}` : ''}`,
      detalle: `${c.estado.replace('_', ' ')} · compra ${parseFloat(c.porcentaje_compra.toString()).toLocaleString('es-AR', { maximumFractionDigits: 2 })}%`,
      monto: c.monto, moneda: 'ARS', esGasto: false,
    })
  }

  for (const p of prestamos) {
    const freq: Record<string, string> = {
      DIARIA: 'diarias', SEMANAL: 'semanales', QUINCENAL: 'quincenales', MENSUAL: 'mensuales', ANUAL: 'anuales',
    }
    items.push({
      id: p.id, seccion: 'PRESTAMOS', fecha: p.fecha_inicio,
      descripcion: 'Préstamo',
      detalle: `${p.cuotas} cuotas ${freq[p.frecuencia] ?? p.frecuencia.toLowerCase()} · ${p.estado}`,
      monto: p.credito, moneda: p.moneda, esGasto: false,
    })
  }

  return items.sort((a, b) => b.fecha.localeCompare(a.fecha))
}

function getRangoDeFecha(preset: PresetFecha, customDesde: string | null, customHasta: string | null) {
  const hoy = todayISO()
  switch (preset) {
    case 'HOY':    return { desde: hoy, hasta: hoy }
    case 'SEMANA': return { desde: weekStartISO(), hasta: hoy }
    case 'MES':    return { desde: monthStartISO(), hasta: hoy }
    case 'PERSONALIZADO': return { desde: customDesde, hasta: customHasta }
  }
}

function enRango(fecha: string, desde: string | null, hasta: string | null): boolean {
  if (desde && fecha < desde) return false
  if (hasta && fecha > hasta) return false
  return true
}

export default function Movimientos() {
  const [seccion, setSeccion] = useState<Seccion>('TODOS')
  const [preset, setPreset] = useState<PresetFecha>('MES')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)

  const { data: divisas = [], isLoading: loadingDiv, refetch: refetchDiv } =
    useQuery({ queryKey: ['movimientos'], queryFn: getMovimientos, refetchInterval: 30_000 })
  const { data: gastos = [], isLoading: loadingGas, refetch: refetchGas } =
    useQuery({ queryKey: ['gastos'], queryFn: getGastos, refetchInterval: 30_000 })
  const { data: cheques = [], isLoading: loadingChe, refetch: refetchChe } =
    useQuery({ queryKey: ['cheques-todos'], queryFn: () => getCheques(), refetchInterval: 30_000 })
  const { data: prestamos = [], isLoading: loadingPre, refetch: refetchPre } =
    useQuery({ queryKey: ['prestamos-todos'], queryFn: () => getPrestamos(), refetchInterval: 30_000 })

  const isLoading = loadingDiv || loadingGas || loadingChe || loadingPre

  const todos = useMemo(() => normalizar(divisas, gastos, cheques, prestamos), [divisas, gastos, cheques, prestamos])

  const { desde, hasta } = getRangoDeFecha(preset, customDesde, customHasta)

  const filtrados = useMemo(() => {
    return todos.filter((item) => {
      if (seccion !== 'TODOS' && item.seccion !== seccion) return false
      return enRango(item.fecha, desde, hasta)
    })
  }, [todos, seccion, desde, hasta])

  function handleRefetch() { refetchDiv(); refetchGas(); refetchChe(); refetchPre() }

  function handlePreset(p: PresetFecha) {
    setPreset(p)
    if (p !== 'PERSONALIZADO') setShowPicker(false)
    else setShowPicker(true)
  }

  const labelPersonalizado =
    customDesde && customHasta ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
    : customDesde ? `Desde ${fmtDate(customDesde)}` : 'Personalizado'

  const secciones: Seccion[] = ['TODOS', 'DIVISAS', 'GASTOS', 'CHEQUES', 'PRESTAMOS']

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>Movimientos</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>
            {filtrados.length} registro{filtrados.length !== 1 ? 's' : ''}
            {desde || hasta ? ` · ${desde ? fmtDate(desde) : '…'} → ${hasta ? fmtDate(hasta) : '…'}` : ''}
          </p>
        </div>
        <button onClick={handleRefetch} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}>
          <IconRefresh size={14} />Actualizar
        </button>
      </div>

      {/* Filtros */}
      <div style={{ position: 'relative', display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '0.75rem', marginBottom: '1rem' }}>
        <DropdownFilter
          label="Sección"
          value={seccion}
          options={secciones.map((s) => ({ value: s, label: s === 'TODOS' ? 'Todos' : SECCION_CONFIG[s].label }))}
          onChange={setSeccion}
        />
        <DropdownFilter
          label="Período"
          value={preset}
          options={[
            { value: 'HOY' as PresetFecha, label: 'Hoy' },
            { value: 'SEMANA' as PresetFecha, label: 'Esta semana' },
            { value: 'MES' as PresetFecha, label: 'Este mes' },
            { value: 'PERSONALIZADO' as PresetFecha, label: labelPersonalizado },
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

      {/* Tabla */}
      <div style={{ ...CARD, overflow: 'hidden' }}>
        {isLoading && <SkeletonRows rows={6} />}
        {!isLoading && filtrados.length === 0 && (
          <div style={{ padding: '3rem', textAlign: 'center' }}>
            <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📭</p>
            <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>Sin movimientos en el período</p>
            <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.4)', marginTop: '0.25rem' }}>Probá cambiando el filtro de fecha o sección</p>
          </div>
        )}
        {!isLoading && filtrados.length > 0 && (
          <>
          {/* Mobile: tarjetas */}
          <div className="sm:hidden">
            {filtrados.map((item) => {
              const cfg = SECCION_CONFIG[item.seccion]
              const montoFmt = fmtMonto(item.monto, item.moneda)
              return (
                <div key={`m-${item.seccion}-${item.id}`} style={{ display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--ov-004)' }}>
                  {/* Franja de color */}
                  <div style={{ width: '3px', flexShrink: 0, background: cfg.color, borderRadius: '0 2px 2px 0', margin: '6px 0' }} />
                  {/* Contenido */}
                  <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', padding: '0.7rem 1rem 0.7rem 0.75rem' }}>
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontFamily: FM, fontSize: '0.84rem', fontWeight: 600, color: 'var(--text-1)', wordBreak: 'break-word', marginBottom: '3px' }}>{item.descripcion}</p>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                        <span style={{ fontFamily: FM, fontSize: '0.58rem', fontWeight: 700, color: cfg.color, background: cfg.bg, padding: '1px 7px', borderRadius: '999px', border: `1px solid ${cfg.color}30` }}>{cfg.label}</span>
                        <span style={{ fontFamily: FM, fontSize: '0.68rem', fontWeight: 500, color: 'rgba(100,116,139,0.55)' }}>{fmtDate(item.fecha)}</span>
                      </div>
                      {item.detalle && <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.45)', wordBreak: 'break-word', marginTop: '3px' }}>{item.detalle}</p>}
                    </div>
                    <span style={{ fontFamily: FN, fontSize: '1.05rem', letterSpacing: '0.02em', color: item.esGasto ? '#f87171' : 'var(--text-1)', whiteSpace: 'nowrap', flexShrink: 0 }}>
                      {item.esGasto ? `−${montoFmt}` : montoFmt}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
          {/* Desktop: tabla */}
          <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '480px' }}>
              <thead>
                <tr>
                  {['Fecha', 'Sección', 'Descripción', 'Monto'].map((h, i) => (
                    <th key={h} style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: i === 3 ? 'right' : 'left', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtrados.map((item) => {
                  const cfg = SECCION_CONFIG[item.seccion]
                  const montoFmt = fmtMonto(item.monto, item.moneda)
                  return (
                    <tr key={`${item.seccion}-${item.id}`}
                      onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                      onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                      <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.72rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'rgba(100,116,139,0.6)', whiteSpace: 'nowrap' }}>
                        {fmtDate(item.fecha)}
                      </td>
                      <td style={{ padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', whiteSpace: 'nowrap' }}>
                        <span style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, color: cfg.color, background: cfg.bg, padding: '2px 9px', borderRadius: '999px', border: `1px solid ${cfg.color}30` }}>
                          {cfg.label}
                        </span>
                      </td>
                      <td style={{ padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)' }}>
                        <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-1)', whiteSpace: 'normal', wordBreak: 'break-word', maxWidth: '260px' }}>{item.descripcion}</p>
                        {item.detalle && (
                          <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.55)', whiteSpace: 'normal', wordBreak: 'break-word', maxWidth: '260px', marginTop: '1px' }}>{item.detalle}</p>
                        )}
                      </td>
                      <td style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 700, padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', textAlign: 'right', color: item.esGasto ? '#f87171' : 'var(--text-1)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                        {item.esGasto ? `−${montoFmt}` : montoFmt}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>
    </div>
  )
}
