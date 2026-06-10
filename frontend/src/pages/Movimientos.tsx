import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getMovimientos } from '../api/movimientos'
import { getGastos } from '../api/gastos_operativos'
import { getCheques } from '../api/cheques'
import { getPrestamos } from '../api/prestamos'
import { fmtUSD, fmtMonto, fmtDate, todayISO, weekStartISO, monthStartISO } from '../lib/fmt'
import type { MovimientoEfectivo, GastoOperativo, Cheque, Prestamo } from '../types'
import DateRangePicker from '../components/DateRangePicker'

// ── Tipos ────────────────────────────────────────────────────────────────────

type Seccion = 'TODOS' | 'DIVISAS' | 'GASTOS' | 'CHEQUES' | 'PRESTAMOS'
type PresetFecha = 'HOY' | 'SEMANA' | 'MES' | 'PERSONALIZADO'

interface MovimientoUnificado {
  id: string
  seccion: Exclude<Seccion, 'TODOS'>
  fecha: string          // YYYY-MM-DD (para ordenar y filtrar)
  descripcion: string
  detalle: string
  monto: string
  moneda: 'ARS' | 'USD'
  esGasto: boolean       // para colorear el monto en rojo
}

// ── Configuración visual por sección ─────────────────────────────────────────

const SECCION_CONFIG: Record<Exclude<Seccion, 'TODOS'>, { label: string; badge: string }> = {
  DIVISAS:   { label: 'Divisas',   badge: 'bg-blue-500/15 text-blue-500 dark:text-blue-400' },
  GASTOS:    { label: 'Gastos',    badge: 'bg-orange-500/15 text-orange-500 dark:text-orange-400' },
  CHEQUES:   { label: 'Cheques',   badge: 'bg-purple-500/15 text-purple-500 dark:text-purple-400' },
  PRESTAMOS: { label: 'Préstamos', badge: 'bg-green-500/15 text-green-500 dark:text-green-400' },
}

// ── Normalización ─────────────────────────────────────────────────────────────

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
      id: m.id,
      seccion: 'DIVISAS',
      fecha: m.fecha_operacion.slice(0, 10),
      descripcion: m.tipo === 'COMPRA' ? 'Compra USD' : 'Venta USD',
      detalle: `${fmtUSD(m.monto)} · cotiz. $${cotiz}`,
      monto: m.ganancia,
      moneda: 'ARS',
      esGasto: ganancia < 0,
    })
  }

  for (const g of gastos) {
    items.push({
      id: g.id,
      seccion: 'GASTOS',
      fecha: g.fecha_operacion,
      descripcion: g.concepto,
      detalle: g.observaciones ?? '',
      monto: g.monto,
      moneda: g.moneda,
      esGasto: true,
    })
  }

  for (const c of cheques) {
    items.push({
      id: c.nro_cheque,
      seccion: 'CHEQUES',
      fecha: c.created_at.slice(0, 10),
      descripcion: `Nº ${c.nro_cheque}`,
      detalle: `${c.estado.replace('_', ' ')} · compra ${parseFloat(c.porcentaje_compra.toString()).toLocaleString('es-AR', { maximumFractionDigits: 2 })}%`,
      monto: c.monto,
      moneda: 'ARS',
      esGasto: false,
    })
  }

  for (const p of prestamos) {
    const freq: Record<string, string> = {
      DIARIA: 'diarias', SEMANAL: 'semanales', QUINCENAL: 'quincenales',
      MENSUAL: 'mensuales', ANUAL: 'anuales',
    }
    items.push({
      id: p.id,
      seccion: 'PRESTAMOS',
      fecha: p.fecha_inicio,
      descripcion: `Préstamo`,
      detalle: `${p.cuotas} cuotas ${freq[p.frecuencia] ?? p.frecuencia.toLowerCase()} · ${p.estado}`,
      monto: p.credito,
      moneda: p.moneda,
      esGasto: false,
    })
  }

  return items.sort((a, b) => b.fecha.localeCompare(a.fecha))
}

// ── Filtro de fecha ───────────────────────────────────────────────────────────

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

// ── Componente ────────────────────────────────────────────────────────────────

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

  const todos = useMemo(
    () => normalizar(divisas, gastos, cheques, prestamos),
    [divisas, gastos, cheques, prestamos],
  )

  const { desde, hasta } = getRangoDeFecha(preset, customDesde, customHasta)

  const filtrados = useMemo(() => {
    return todos.filter((item) => {
      if (seccion !== 'TODOS' && item.seccion !== seccion) return false
      return enRango(item.fecha, desde, hasta)
    })
  }, [todos, seccion, desde, hasta])

  function handleRefetch() {
    refetchDiv(); refetchGas(); refetchChe(); refetchPre()
  }

  function handlePreset(p: PresetFecha) {
    setPreset(p)
    if (p !== 'PERSONALIZADO') setShowPicker(false)
    else setShowPicker(true)
  }

  // Etiqueta del botón personalizado
  const labelPersonalizado =
    customDesde && customHasta
      ? `${fmtDate(customDesde)} — ${fmtDate(customHasta)}`
      : customDesde
      ? `Desde ${fmtDate(customDesde)}`
      : 'Personalizado'

  const secciones: Seccion[] = ['TODOS', 'DIVISAS', 'GASTOS', 'CHEQUES', 'PRESTAMOS']
  const presets: { key: PresetFecha; label: string }[] = [
    { key: 'HOY', label: 'Hoy' },
    { key: 'SEMANA', label: 'Esta semana' },
    { key: 'MES', label: 'Este mes' },
    { key: 'PERSONALIZADO', label: labelPersonalizado },
  ]

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Movimientos</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {filtrados.length} registro{filtrados.length !== 1 ? 's' : ''}
            {desde || hasta ? ` · ${desde ? fmtDate(desde) : '…'} → ${hasta ? fmtDate(hasta) : '…'}` : ''}
          </p>
        </div>
        <button
          onClick={handleRefetch}
          className="text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 border border-slate-200 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          Actualizar
        </button>
      </div>

      {/* Filtro de sección */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {secciones.map((s) => (
          <button
            key={s}
            onClick={() => setSeccion(s)}
            className={`px-3.5 py-1.5 rounded-full text-sm font-medium transition-colors ${
              seccion === s
                ? 'bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            {s === 'TODOS' ? 'Todos' : SECCION_CONFIG[s].label}
          </button>
        ))}
      </div>

      {/* Filtro de fecha */}
      <div className="relative flex flex-wrap gap-1.5 mb-6">
        {presets.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => handlePreset(key)}
            className={`px-3.5 py-1.5 rounded-full text-sm font-medium transition-colors ${
              preset === key
                ? 'bg-blue-600 text-white'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            {label}
          </button>
        ))}

        {/* Calendar popover */}
        {showPicker && (
          <DateRangePicker
            from={customDesde}
            to={customHasta}
            onChange={(f, t) => { setCustomDesde(f); setCustomHasta(t) }}
            onClose={() => setShowPicker(false)}
          />
        )}
      </div>

      {/* Lista unificada */}
      <div className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
        {isLoading && (
          <div className="p-12 text-center text-slate-400">Cargando movimientos…</div>
        )}

        {!isLoading && filtrados.length === 0 && (
          <div className="p-12 text-center text-slate-400">
            <p className="text-3xl mb-3">📭</p>
            <p className="font-medium text-slate-500">Sin movimientos en el período</p>
            <p className="text-xs mt-1">Probá cambiando el filtro de fecha o sección</p>
          </div>
        )}

        {!isLoading && filtrados.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/80">
                <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-400 uppercase tracking-wide whitespace-nowrap">Fecha</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-400 uppercase tracking-wide">Sección</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-slate-400 uppercase tracking-wide">Descripción</th>
                <th className="text-right px-4 py-2.5 text-xs font-medium text-slate-400 uppercase tracking-wide">Monto</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-700/60">
              {filtrados.map((item) => {
                const cfg = SECCION_CONFIG[item.seccion]
                const montoFmt = fmtMonto(item.monto, item.moneda)
                return (
                  <tr
                    key={`${item.seccion}-${item.id}`}
                    className="hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-xs text-slate-400 dark:text-slate-500 font-mono whitespace-nowrap">
                      {fmtDate(item.fecha)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cfg.badge}`}>
                        {cfg.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium text-slate-800 dark:text-slate-100 truncate max-w-xs">
                        {item.descripcion}
                      </p>
                      {item.detalle && (
                        <p className="text-xs text-slate-400 dark:text-slate-500 truncate max-w-xs mt-0.5">
                          {item.detalle}
                        </p>
                      )}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold tabular-nums whitespace-nowrap ${
                      item.esGasto
                        ? 'text-red-500 dark:text-red-400'
                        : 'text-slate-800 dark:text-slate-100'
                    }`}>
                      {item.esGasto ? `−${montoFmt}` : montoFmt}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
