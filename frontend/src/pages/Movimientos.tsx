import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getMovimientos } from '../api/movimientos'
import { getGastos } from '../api/gastos_operativos'
import { getCheques } from '../api/cheques'
import { getPrestamos } from '../api/prestamos'
import { getClientes } from '../api/clientes'
import { fmtUSD, fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import { SkeletonRows } from '../components/Skeleton'
import type { MovimientoEfectivo, GastoOperativo, Cheque, Prestamo } from '../types'
import DateRangePicker from '../components/DateRangePicker'
import DropdownFilter from '../components/DropdownFilter'

type Seccion = 'TODOS' | 'DIVISAS' | 'GASTOS' | 'CHEQUES' | 'PRESTAMOS' | 'COBROS'
type PresetFecha = 'HOY' | 'SEMANA' | 'MES' | 'PERSONALIZADO'

const FM     = "'Manrope', sans-serif"
const FN     = "'Bebas Neue', sans-serif"
const FJ     = "'JetBrains Mono', monospace"
const ACCENT = '#6366f1'
const CARD   = {
  background:   'var(--surface-grad)',
  border:       '1px solid var(--bd-006)',
  boxShadow:    'var(--shadow-card)',
  borderRadius: 'var(--r-lg)',
}

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

const SECCION_CONFIG: Record<Exclude<Seccion, 'TODOS'>, { label: string; color: string; bg: string; initial: string }> = {
  DIVISAS:   { label: 'Divisas',   color: '#60a5fa', bg: 'rgba(96,165,250,0.13)',  initial: 'D' },
  GASTOS:    { label: 'Gastos',    color: '#fb923c', bg: 'rgba(251,146,60,0.13)',   initial: 'G' },
  CHEQUES:   { label: 'Cheques',   color: '#a78bfa', bg: 'rgba(167,139,250,0.13)', initial: 'C' },
  PRESTAMOS: { label: 'Préstamos', color: '#4ade80', bg: 'rgba(74,222,128,0.13)',  initial: 'P' },
  COBROS:    { label: 'Cobros',    color: '#34d399', bg: 'rgba(52,211,153,0.13)',   initial: 'Q' },
}

function normalizar(
  divisas: MovimientoEfectivo[],
  gastos: GastoOperativo[],
  cheques: Cheque[],
  prestamos: Prestamo[],
  clienteMap: Map<string, string>,
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
    for (const c of p.cuotas_detalle) {
      if (c.estado === 'COBRADA' && c.fecha_cobro) {
        items.push({
          id: c.id, seccion: 'COBROS', fecha: c.fecha_cobro,
          descripcion: clienteMap.get(p.cliente_id) ?? '–',
          detalle: `Cuota ${c.numero_cuota} / ${p.cuotas}`,
          monto: c.monto, moneda: p.moneda, esGasto: false,
        })
      }
    }
  }

  return items.sort((a, b) => b.fecha.localeCompare(a.fecha))
}

function getRango(preset: PresetFecha, customDesde: string | null, customHasta: string | null) {
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

export default function Movimientos() {
  const [seccion, setSeccion]         = useState<Seccion>('TODOS')
  const [preset, setPreset]           = useState<PresetFecha>('MES')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker]   = useState(false)

  const { data: divisas   = [], isLoading: loadingDiv } = useQuery({ queryKey: ['movimientos'],    queryFn: getMovimientos,       refetchInterval: 30_000 })
  const { data: gastos    = [], isLoading: loadingGas } = useQuery({ queryKey: ['gastos'],         queryFn: getGastos,            refetchInterval: 30_000 })
  const { data: cheques   = [], isLoading: loadingChe } = useQuery({ queryKey: ['cheques-todos'],  queryFn: () => getCheques(),   refetchInterval: 30_000 })
  const { data: prestamos = [], isLoading: loadingPre } = useQuery({ queryKey: ['prestamos-todos'], queryFn: () => getPrestamos(), refetchInterval: 30_000 })
  const { data: clientes  = [] }                        = useQuery({ queryKey: ['clientes'],        queryFn: getClientes,          staleTime: 60_000 })

  const isLoading = loadingDiv || loadingGas || loadingChe || loadingPre

  const clienteMap = useMemo(() => new Map(clientes.map((c) => [c.id, c.nombre])), [clientes])

  const todos = useMemo(
    () => normalizar(divisas, gastos, cheques, prestamos, clienteMap),
    [divisas, gastos, cheques, prestamos, clienteMap],
  )

  const { desde, hasta } = getRango(preset, customDesde, customHasta)

  const filtrados = useMemo(() =>
    todos.filter(item => {
      if (seccion !== 'TODOS' && item.seccion !== seccion) return false
      return enRango(item.fecha, desde, hasta)
    }),
    [todos, seccion, desde, hasta],
  )

  const porDia = useMemo(() => {
    const map = new Map<string, { subtotalGastos: number; items: MovimientoUnificado[] }>()
    for (const item of filtrados) {
      const ex = map.get(item.fecha) ?? { subtotalGastos: 0, items: [] }
      map.set(item.fecha, {
        subtotalGastos: ex.subtotalGastos + (item.esGasto ? parseFloat(item.monto) : 0),
        items: [...ex.items, item],
      })
    }
    return Array.from(map.entries())
      .map(([fecha, { subtotalGastos, items }]) => ({ fecha, subtotalGastos, items }))
      .sort((a, b) => b.fecha.localeCompare(a.fecha))
  }, [filtrados])

  const rangoLabel = desde && hasta ? `${fmtDate(desde)} → ${fmtDate(hasta)}` : '–'

  const labelPersonalizado =
    customDesde && customHasta
      ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
      : customDesde ? `Desde ${fmtDate(customDesde)}` : 'Personalizado'

  function handlePreset(p: PresetFecha) {
    setPreset(p)
    setShowPicker(p === 'PERSONALIZADO')
  }

  const secciones: Seccion[] = ['TODOS', 'DIVISAS', 'GASTOS', 'CHEQUES', 'PRESTAMOS', 'COBROS']

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem',
      }}>
        {/* Izquierda: título + badge + rango */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
          <h1 style={{
            fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em',
            color: 'var(--text-1)', lineHeight: 1, margin: 0,
          }}>
            Movimientos
          </h1>
          <span style={{
            fontFamily: FM, fontSize: '0.72rem', fontWeight: 700,
            background: `${ACCENT}22`, color: ACCENT,
            border: `1px solid ${ACCENT}44`,
            padding: '0.22rem 0.7rem', borderRadius: '999px',
            whiteSpace: 'nowrap',
          }}>
            {isLoading ? '–' : filtrados.length} en el período
          </span>
          <span style={{
            fontFamily: FM, fontSize: '0.72rem',
            color: 'rgba(100,116,139,0.5)',
            whiteSpace: 'nowrap',
          }}>
            {rangoLabel}
          </span>
        </div>

        {/* Derecha: filtros */}
        <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-end', gap: '0.75rem', flexWrap: 'wrap' }}>
          <DropdownFilter
            label="Sección"
            value={seccion}
            options={secciones.map(s => ({ value: s, label: s === 'TODOS' ? 'Todos' : SECCION_CONFIG[s].label }))}
            onChange={setSeccion}
          />
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
              from={customDesde} to={customHasta}
              onChange={(f, t) => { setCustomDesde(f); setCustomHasta(t) }}
              onClose={() => setShowPicker(false)}
            />
          )}
        </div>
      </div>

      {/* ── Loading ──────────────────────────────────────────────────────── */}
      {isLoading && (
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <SkeletonRows rows={6} />
        </div>
      )}

      {/* ── Sin movimientos ───────────────────────────────────────────────── */}
      {!isLoading && filtrados.length === 0 && (
        <div style={{ ...CARD, padding: '3rem', textAlign: 'center' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📭</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>
            Sin movimientos en el período
          </p>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.4)', marginTop: '0.25rem' }}>
            Probá cambiando el filtro de fecha o sección
          </p>
        </div>
      )}

      {/* ── Lista agrupada por día ───────────────────────────────────────── */}
      {!isLoading && filtrados.length > 0 && (
        <div style={{ ...CARD, overflow: 'hidden' }}>
          {porDia.map(({ fecha, subtotalGastos, items }) => (
            <div key={fecha}>

              {/* Franja de encabezado del día */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '0.5rem 1rem',
                background: 'var(--ov-0025)',
                borderBottom: '1px solid var(--bd-006)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{
                    fontFamily: FJ, fontSize: '0.68rem', fontWeight: 700,
                    letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-1)',
                  }}>
                    {fmtDate(fecha)}
                  </span>
                  <span style={{
                    fontFamily: FM, fontSize: '0.6rem', color: 'rgba(100,116,139,0.5)',
                    letterSpacing: '0.08em', textTransform: 'uppercase',
                  }}>
                    · {items.length} movimiento{items.length !== 1 ? 's' : ''}
                  </span>
                </div>
                {subtotalGastos > 0 && (
                  <span style={{
                    fontFamily: FN, fontSize: '1rem', letterSpacing: '0.02em',
                    color: 'rgba(248,113,113,0.7)',
                  }}>
                    −{fmtMonto(subtotalGastos, 'ARS')}
                  </span>
                )}
              </div>

              {/* Ítems del día */}
              {items.map(item => {
                const cfg = SECCION_CONFIG[item.seccion]
                const initial = item.seccion === 'GASTOS'
                  ? item.descripcion.charAt(0).toUpperCase()
                  : cfg.initial
                const montoFmt = fmtMonto(item.monto, item.moneda)
                return (
                  <div
                    key={`${item.seccion}-${item.id}`}
                    onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'var(--ov-002)' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '0.75rem',
                      padding: '0.65rem 1rem',
                      borderBottom: '1px solid var(--ov-004)',
                    }}
                  >
                    {/* Avatar con inicial de sección */}
                    <div style={{
                      width: '34px', height: '34px', flexShrink: 0,
                      borderRadius: 'var(--r-sm)',
                      background: cfg.bg,
                      border: `1px solid ${cfg.color}40`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: FN, fontSize: '1rem', color: cfg.color,
                    }}>
                      {initial}
                    </div>

                    {/* Descripción + badge de sección + detalle */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '2px' }}>
                        <p style={{
                          fontFamily: FM, fontSize: '0.82rem', fontWeight: 600,
                          color: 'var(--text-1)', margin: 0, wordBreak: 'break-word',
                        }}>
                          {item.descripcion}
                        </p>
                        <span style={{
                          fontFamily: FM, fontSize: '0.58rem', fontWeight: 700,
                          color: cfg.color, background: cfg.bg,
                          padding: '1px 7px', borderRadius: '999px',
                          flexShrink: 0,
                        }}>
                          {cfg.label}
                        </span>
                      </div>
                      {item.detalle && (
                        <p style={{
                          fontFamily: FM, fontSize: '0.68rem',
                          color: 'rgba(100,116,139,0.5)', margin: 0, wordBreak: 'break-word',
                        }}>
                          {item.detalle}
                        </p>
                      )}
                    </div>

                    {/* Monto */}
                    <span style={{
                      fontFamily: FN, fontSize: '1.1rem', letterSpacing: '0.02em',
                      color: item.esGasto ? '#f87171' : 'var(--text-1)',
                      whiteSpace: 'nowrap', flexShrink: 0,
                      fontVariantNumeric: 'tabular-nums',
                    }}>
                      {item.esGasto ? `−${montoFmt}` : montoFmt}
                    </span>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
