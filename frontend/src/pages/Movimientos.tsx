import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getMovimientos, editarMovimiento } from '../api/movimientos'
import { getMovimientosUnificados } from '../api/reportes'
import { fmtUSD, fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import { SkeletonRows } from '../components/Skeleton'
import type { MovimientoEfectivo, MovimientoUnificado, MovimientoGrupo, MovimientoFlujo } from '../types'
import DateRangePicker from '../components/DateRangePicker'
import DropdownFilter from '../components/DropdownFilter'
import ModalEliminar from '../components/ModalEliminar'

type GrupoFiltro = 'TODOS' | MovimientoGrupo
type FlujoFiltro = 'TODOS' | MovimientoFlujo
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
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

// ── Modal editar divisa (compra/venta USD) ────────────────────────────

function ModalEditarDivisa({ mov, editableDinero, onClose, onSuccess }: { mov: MovimientoEfectivo; editableDinero: boolean; onClose: () => void; onSuccess: () => void }) {
  const [monto, setMonto] = useState(mov.monto)
  const [cotiz, setCotiz] = useState(mov.cotizacion_aplicada)
  const [observaciones, setObservaciones] = useState(mov.observaciones ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const montoNum = parseFloat(monto) || 0
  const cotizNum = parseFloat(cotiz) || 0
  const pesos = montoNum * cotizNum
  const esCompra = mov.tipo === 'COMPRA'

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await editarMovimiento(mov.id, {
        observaciones: observaciones.trim() || null,
        ...(editableDinero ? { monto: montoNum, cotizacion_aplicada: cotizNum } : {}),
      })
      toast('success', 'Operación actualizada')
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '400px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Editar {esCompra ? 'compra' : 'venta'} USD</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Operación de divisas</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          {!editableDinero && (
            <div style={{ background: 'color-mix(in srgb, var(--warning) 8%, transparent)', border: '1px solid color-mix(in srgb, var(--warning) 25%, transparent)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.8rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--warning)', lineHeight: 1.4 }}>
                {esCompra
                  ? 'Este lote ya fue consumido por una o más ventas (FIFO): no se puede cambiar el monto ni la cotización. Corregilo con una operación inversa.'
                  : 'Hay ventas posteriores que dependen de esta imputación FIFO: solo se puede editar la última venta.'}
              </p>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Cantidad USD</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required disabled={!editableDinero} style={{ ...INPUT_STYLE, opacity: editableDinero ? 1 : 0.5, cursor: editableDinero ? 'auto' : 'not-allowed' }} /></div>
            <div><label style={LABEL_STYLE}>Cotización ($/USD)</label><input type="number" step="0.000001" min="0.000001" value={cotiz} onChange={(e) => setCotiz(e.target.value)} required disabled={!editableDinero} style={{ ...INPUT_STYLE, opacity: editableDinero ? 1 : 0.5, cursor: editableDinero ? 'auto' : 'not-allowed' }} /></div>
          </div>
          {editableDinero && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.9rem', display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
              <span style={{ color: 'rgba(100,116,139,0.7)' }}>Pesos {esCompra ? 'que salen' : 'que entran'}</span>
              <span style={{ fontWeight: 700, color: 'var(--text-1)' }}>{fmtMonto(pesos, 'ARS')}</span>
            </div>
          )}
          <div><label style={LABEL_STYLE}>Observaciones <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} /></div>
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: loading ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Guardar cambios'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Config de presentación por grupo de operación ─────────────────────

const GRUPO_CONFIG: Record<MovimientoGrupo, { label: string; color: string; bg: string; initial: string }> = {
  COBROS:        { label: 'Cobros',        color: '#34d399', bg: 'rgba(52,211,153,0.13)', initial: 'Q' },
  CHEQUES:       { label: 'Cheques',       color: '#a78bfa', bg: 'rgba(167,139,250,0.13)', initial: 'C' },
  DIVISAS:       { label: 'Divisas',       color: '#60a5fa', bg: 'rgba(96,165,250,0.13)', initial: 'D' },
  GASTOS:        { label: 'Gastos',        color: '#fb923c', bg: 'rgba(251,146,60,0.13)', initial: 'G' },
  OTORGAMIENTOS: { label: 'Otorgamientos', color: '#f472b6', bg: 'rgba(244,114,182,0.13)', initial: 'O' },
  PASIVOS:       { label: 'Pasivos',       color: '#f87171', bg: 'rgba(248,113,113,0.13)', initial: 'P' },
  APERTURA:      { label: 'Apertura',      color: '#facc15', bg: 'rgba(250,204,21,0.13)',  initial: 'A' },
  OTROS:         { label: 'Otros',         color: '#94a3b8', bg: 'rgba(148,163,184,0.13)', initial: '•' },
}

// Un grupo que el backend agregue y el front todavía no conozca cae en OTROS.
// Sin esto, `cfg.initial` sobre un `undefined` tira la página entera a blanco.
const cfgGrupo = (g: MovimientoGrupo) => GRUPO_CONFIG[g] ?? GRUPO_CONFIG.OTROS

// Etiqueta corta de cada categoría, para la línea secundaria de detalle.
const CATEGORIA_LABEL: Record<string, string> = {
  COBRO_CUOTA:           'Cobro de cuota',
  COBRO_FIADO:           'Cobro de fiado',
  COBRO_DEUDA:           'Cobro de deuda',
  VENTA_CHEQUE:          'Venta de cheque',
  COMPRA_CHEQUE:         'Compra de cheque',
  COBRO_CHEQUE:          'Cobro de cheque',
  COMPRA_USD:            'Compra de USD',
  VENTA_USD:             'Venta de USD',
  GASTO:                 'Gasto',
  OTORGAMIENTO_PRESTAMO: 'Préstamo otorgado',
  OTORGAMIENTO_DEUDA:    'Deuda otorgada',
  PAGO_PASIVO:           'Pago de pasivo',
  VUELTO_PASIVO:         'Vuelto de pasivo',
  INGRESO_CHEQUE:        'Ingreso a cartera',
  SALDO_INICIAL:         'Saldo inicial de caja',
}

function detalleSecundario(m: MovimientoUnificado): string {
  const partes: string[] = [CATEGORIA_LABEL[m.categoria] ?? m.categoria]
  if (m.flujo === 'NEUTRO') partes.push('sin movimiento de efectivo')
  if (m.medio_pago) partes.push(m.medio_pago === 'EFECTIVO' ? 'efectivo' : 'transferencia')
  if (m.cotizacion) {
    const c = parseFloat(m.cotizacion).toLocaleString('es-AR', { minimumFractionDigits: 2 })
    partes.push(`cotiz. $${c}`)
  }
  if (m.categoria === 'VENTA_USD' && m.ganancia) {
    const g = parseFloat(m.ganancia)
    partes.push(`${g >= 0 ? 'ganancia' : 'pérdida'} ${fmtMonto(Math.abs(g).toString(), 'ARS')}`)
  }
  return partes.join(' · ')
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

interface ResumenDia {
  ingresosARS: number; egresosARS: number
  ingresosUSD: number; egresosUSD: number
}

export default function Movimientos() {
  const [grupo, setGrupo]             = useState<GrupoFiltro>('TODOS')
  const [flujo, setFlujo]             = useState<FlujoFiltro>('TODOS')
  const [preset, setPreset]           = useState<PresetFecha>('MES')
  const [customDesde, setCustomDesde] = useState<string | null>(null)
  const [customHasta, setCustomHasta] = useState<string | null>(null)
  const [showPicker, setShowPicker]   = useState(false)
  const [editarDivisaId, setEditarDivisaId] = useState<string | null>(null)
  const [eliminarDivisaId, setEliminarDivisaId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { desde, hasta } = getRango(preset, customDesde, customHasta)
  const rangoListo = Boolean(desde && hasta)

  // Feed unificado (libro de caja + ingresos de cheques), filtrado por fecha en el backend.
  const { data: movimientos = [], isLoading, isFetching } = useQuery({
    queryKey: ['movimientos-unificados', desde, hasta],
    queryFn: () => getMovimientosUnificados(desde as string, hasta as string),
    enabled: rangoListo,
    refetchInterval: 30_000,
  })

  // Solo para el modal de edición de divisas: necesita el MovimientoEfectivo completo (FIFO).
  const { data: divisas = [] } = useQuery({ queryKey: ['movimientos'], queryFn: getMovimientos, staleTime: 30_000 })

  // ID de la última venta de divisas (la única editable en monto/cotización, por FIFO).
  const ultimaVentaId = useMemo(() => {
    const ventas = divisas.filter((m) => m.tipo === 'VENTA')
    if (ventas.length === 0) return null
    return ventas.reduce((a, b) =>
      `${b.fecha_operacion}|${b.created_at}` > `${a.fecha_operacion}|${a.created_at}` ? b : a,
    ).id
  }, [divisas])

  function dineroEditable(mov: MovimientoEfectivo): boolean {
    return mov.tipo === 'COMPRA'
      ? parseFloat(mov.usd_restante) === parseFloat(mov.monto)
      : mov.id === ultimaVentaId
  }

  function handleEditDivisa() {
    setEditarDivisaId(null)
    queryClient.invalidateQueries({ queryKey: ['movimientos'] })
    queryClient.invalidateQueries({ queryKey: ['movimientos-unificados'] })
  }

  function handleEliminarDivisa() {
    setEliminarDivisaId(null)
    queryClient.invalidateQueries({ queryKey: ['movimientos'] })
    queryClient.invalidateQueries({ queryKey: ['movimientos-unificados'] })
    // Sacar la operación de la cadena reimputa el FIFO: cambian ganancias del reporte.
    queryClient.invalidateQueries({ queryKey: ['reporte-caja'] })
    queryClient.invalidateQueries({ queryKey: ['reporte'] })
  }

  const movEditar = editarDivisaId ? divisas.find((m) => m.id === editarDivisaId) ?? null : null

  const filtrados = useMemo(() =>
    movimientos.filter((m) => {
      if (grupo !== 'TODOS' && m.grupo !== grupo) return false
      if (flujo !== 'TODOS' && m.flujo !== flujo) return false
      return true
    }),
    [movimientos, grupo, flujo],
  )

  const porDia = useMemo(() => {
    const map = new Map<string, { resumen: ResumenDia; items: MovimientoUnificado[] }>()
    for (const m of filtrados) {
      const ex = map.get(m.fecha) ?? { resumen: { ingresosARS: 0, egresosARS: 0, ingresosUSD: 0, egresosUSD: 0 }, items: [] }
      const monto = parseFloat(m.monto) || 0
      const r = ex.resumen
      // El saldo inicial es apertura, no plata que entró ese día: se lista pero
      // no suma a los chips (mismo criterio que el reporte de caja).
      if (m.grupo !== 'APERTURA') {
        if (m.flujo === 'INGRESO') { if (m.moneda === 'ARS') r.ingresosARS += monto; else r.ingresosUSD += monto }
        else if (m.flujo === 'EGRESO') { if (m.moneda === 'ARS') r.egresosARS += monto; else r.egresosUSD += monto }
      }
      ex.items.push(m)
      map.set(m.fecha, ex)
    }
    return Array.from(map.entries())
      .map(([fecha, v]) => ({ fecha, ...v }))
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

  const gruposFiltro: GrupoFiltro[] = ['TODOS', 'COBROS', 'CHEQUES', 'DIVISAS', 'GASTOS', 'OTORGAMIENTOS', 'PASIVOS', 'APERTURA']

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
            {rangoLabel}{isFetching && !isLoading ? ' · actualizando…' : ''}
          </span>
        </div>

        {/* Derecha: filtros */}
        <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-end', gap: '0.75rem', flexWrap: 'wrap' }}>
          <DropdownFilter
            label="Operación"
            value={grupo}
            options={gruposFiltro.map(g => ({ value: g, label: g === 'TODOS' ? 'Todas' : cfgGrupo(g).label }))}
            onChange={setGrupo}
          />
          <DropdownFilter
            label="Flujo"
            value={flujo}
            options={[
              { value: 'TODOS'   as FlujoFiltro, label: 'Todos' },
              { value: 'INGRESO' as FlujoFiltro, label: 'Ingresos' },
              { value: 'EGRESO'  as FlujoFiltro, label: 'Egresos' },
              { value: 'NEUTRO'  as FlujoFiltro, label: 'Sin efectivo' },
            ]}
            onChange={setFlujo}
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
      {rangoListo && isLoading && (
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <SkeletonRows rows={6} />
        </div>
      )}

      {/* ── Rango incompleto (personalizado sin fechas) ──────────────────── */}
      {!rangoListo && (
        <div style={{ ...CARD, padding: '3rem', textAlign: 'center' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📅</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>
            Elegí un rango de fechas
          </p>
        </div>
      )}

      {/* ── Sin movimientos ───────────────────────────────────────────────── */}
      {rangoListo && !isLoading && filtrados.length === 0 && (
        <div style={{ ...CARD, padding: '3rem', textAlign: 'center' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📭</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>
            Sin movimientos en el período
          </p>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.4)', marginTop: '0.25rem' }}>
            Probá cambiando el filtro de fecha, operación o flujo
          </p>
        </div>
      )}

      {/* ── Lista agrupada por día ───────────────────────────────────────── */}
      {rangoListo && !isLoading && filtrados.length > 0 && (
        <div style={{ ...CARD, overflow: 'hidden' }}>
          {porDia.map(({ fecha, resumen, items }) => (
            <div key={fecha}>

              {/* Franja de encabezado del día */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '0.5rem 1rem', gap: '0.5rem', flexWrap: 'wrap',
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
                <ResumenChips resumen={resumen} />
              </div>

              {/* Ítems del día */}
              {items.map(m => {
                const cfg = cfgGrupo(m.grupo)
                const initial = m.grupo === 'GASTOS'
                  ? m.descripcion.charAt(0).toUpperCase()
                  : cfg.initial
                const montoFmt = fmtMonto(m.monto, m.moneda)
                // El libro de caja guarda las divisas con referencia_tipo
                // 'movimiento_efectivo' (svc_movimientos._REF). Comparar contra
                // 'movimiento' hacía que los botones nunca aparecieran.
                const esDivisaEditable = m.grupo === 'DIVISAS' && m.referencia_tipo === 'movimiento_efectivo' && m.referencia_id != null
                const color = m.flujo === 'EGRESO' ? '#f87171'
                  : m.flujo === 'NEUTRO' ? 'rgba(100,116,139,0.7)'
                  : 'var(--text-1)'
                const prefijo = m.flujo === 'EGRESO' ? '−' : m.flujo === 'INGRESO' ? '+' : ''
                return (
                  <div
                    key={`${m.id}`}
                    onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'var(--ov-002)' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '0.75rem',
                      padding: '0.65rem 1rem',
                      borderBottom: '1px solid var(--ov-004)',
                    }}
                  >
                    {/* Avatar con inicial de grupo */}
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

                    {/* Descripción + badge de grupo + detalle */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '2px' }}>
                        <p style={{
                          fontFamily: FM, fontSize: '0.82rem', fontWeight: 600,
                          color: 'var(--text-1)', margin: 0, wordBreak: 'break-word',
                        }}>
                          {m.descripcion}
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
                      <p style={{
                        fontFamily: FM, fontSize: '0.68rem',
                        color: 'rgba(100,116,139,0.5)', margin: 0, wordBreak: 'break-word',
                      }}>
                        {detalleSecundario(m)}
                      </p>
                    </div>

                    {/* Monto */}
                    <span style={{
                      fontFamily: FN, fontSize: '1.1rem', letterSpacing: '0.02em',
                      color, whiteSpace: 'nowrap', flexShrink: 0,
                      fontVariantNumeric: 'tabular-nums',
                    }}>
                      {prefijo}{montoFmt}
                    </span>

                    {/* Editar/Eliminar — solo divisas (las demás operaciones se
                        manejan en su propia página, donde está su contexto). */}
                    {esDivisaEditable && (
                      <>
                        <button
                          onClick={() => setEditarDivisaId(m.referencia_id)}
                          title="Editar operación de divisas"
                          style={{ ...btnBordered('neutral'), fontSize: '0.66rem', padding: '2px 9px', flexShrink: 0 }}
                        >
                          Editar
                        </button>
                        <button
                          onClick={() => setEliminarDivisaId(m.referencia_id)}
                          title="Eliminar la operación y revertir su impacto en caja"
                          style={{ ...btnBordered('danger'), fontSize: '0.66rem', padding: '2px 9px', flexShrink: 0 }}
                        >
                          Eliminar
                        </button>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}

      {movEditar && (
        <ModalEditarDivisa
          mov={movEditar}
          editableDinero={dineroEditable(movEditar)}
          onClose={() => setEditarDivisaId(null)}
          onSuccess={handleEditDivisa}
        />
      )}
      {eliminarDivisaId && (
        <ModalEliminar
          entidad="movimiento_efectivo"
          id={eliminarDivisaId}
          onClose={() => setEliminarDivisaId(null)}
          onSuccess={handleEliminarDivisa}
        />
      )}
    </div>
  )
}

// Chips compactos de ingresos/egresos del día, por moneda (solo los no-cero).
function ResumenChips({ resumen }: { resumen: ResumenDia }) {
  const chips: { texto: string; color: string }[] = []
  if (resumen.ingresosARS > 0) chips.push({ texto: `+${fmtMonto(resumen.ingresosARS.toString(), 'ARS')}`, color: '#34d399' })
  if (resumen.egresosARS > 0)  chips.push({ texto: `−${fmtMonto(resumen.egresosARS.toString(), 'ARS')}`, color: '#f87171' })
  if (resumen.ingresosUSD > 0) chips.push({ texto: `+${fmtUSD(resumen.ingresosUSD.toString())}`, color: '#34d399' })
  if (resumen.egresosUSD > 0)  chips.push({ texto: `−${fmtUSD(resumen.egresosUSD.toString())}`, color: '#f87171' })
  if (chips.length === 0) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
      {chips.map((c, i) => (
        <span key={i} style={{ fontFamily: FN, fontSize: '1rem', letterSpacing: '0.02em', color: c.color }}>
          {c.texto}
        </span>
      ))}
    </div>
  )
}
