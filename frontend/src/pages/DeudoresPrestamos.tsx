import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getPrestamos, createPrestamo, cobrarCuotasLote, cobrarCuotasConChequeLote, editarPrestamo,
  cobrarInteres, abonarCapital, cancelarInteresFijo, editarInteresFijo,
} from '../api/prestamos'
import { getClientes, createCliente } from '../api/clientes'
import { fmtMonto, fmtDate, daysUntil } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import { Skeleton } from '../components/Skeleton'
import { IconPlus } from '../components/icons'
import SelectorMedioPago from '../components/SelectorMedioPago'
import ModalPagarDeuda, { type DeudaItem } from '../components/ModalPagarDeuda'
import ModalEliminar from '../components/ModalEliminar'
import type { Prestamo, Cuota, MedioPago, Moneda, Frecuencia, PrestamoTipo, Cliente } from '../types'

type Semaforo = 'mora' | 'proximo' | 'ok' | 'cancelado'

// ── Préstamo a interés fijo ───────────────────────────────────────────────
// El capital no se amortiza: queda prestado hasta que el cliente lo devuelve, y
// cada 30 días se cobra un interés fijo en plata. Estos helpers son el espejo
// de `svc_prestamos` en el backend — se calculan acá y no vienen del API porque
// todo sale de datos que la fila ya trae.

const CICLO_DIAS = 30

const esInteresFijo = (p: Prestamo) => p.tipo_prestamo === 'INTERES_FIJO'

/** Los períodos devengados, del más viejo al más nuevo. */
function periodos(p: Prestamo): Cuota[] {
  return [...p.cuotas_detalle].sort((a, b) => a.numero_cuota - b.numero_cuota)
}

/** El último período devengado: el ciclo en curso, esté cobrado o no. */
function periodoVigente(p: Prestamo): Cuota | null {
  const todos = periodos(p)
  return todos.length ? todos[todos.length - 1] : null
}

function saldoCuota(c: Cuota): number {
  return parseFloat(c.monto) - parseFloat(c.monto_pagado || '0')
}

/** Los períodos anteriores al vigente que quedaron impagos. Se acumulan: el
 *  interés nuevo no reemplaza al viejo, se suma. */
function periodosEnMora(p: Prestamo): Cuota[] {
  return periodos(p).slice(0, -1).filter((c) => c.estado !== 'COBRADA')
}

function moraAcumulada(p: Prestamo): number {
  return periodosEnMora(p).reduce((acc, c) => acc + saldoCuota(c), 0)
}

function capitalPendiente(p: Prestamo): number {
  return parseFloat(p.capital_pendiente || '0')
}

/** Cuándo arranca el próximo período que todavía no se devengó. */
function proximaFechaCobro(p: Prestamo): string | null {
  if (!p.dia_cobro) return null
  const base = new Date(`${p.dia_cobro}T00:00:00`)
  base.setDate(base.getDate() + CICLO_DIAS * p.cuotas_detalle.length)
  return base.toISOString().slice(0, 10)
}

/** Capital + interés del período vigente (completo, sin prorrateo). La mora
 *  entra o no según decida el operador. */
function totalCancelacion(p: Prestamo, incluirMora: boolean): number {
  const vigente = periodoVigente(p)
  return (
    capitalPendiente(p) +
    (vigente ? saldoCuota(vigente) : 0) +
    (incluirMora ? moraAcumulada(p) : 0)
  )
}

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

function getSemaforo(prestamo: Prestamo): Semaforo {
  if (prestamo.estado !== 'ACTIVO') return 'cancelado'
  if (esInteresFijo(prestamo)) {
    // Acá "sin cuotas pendientes" no significa terminado: el capital sigue
    // afuera. Lo que enciende el rojo es la mora, no el vencimiento de un cuadro.
    if (moraAcumulada(prestamo) > 0) return 'mora'
    const proxima = proximaFechaCobro(prestamo)
    if (proxima && daysUntil(proxima) <= 7) return 'proximo'
    return 'ok'
  }
  const pendientes = prestamo.cuotas_detalle.filter((c) => c.estado !== 'COBRADA')
  if (pendientes.length === 0) return 'cancelado'
  const enMora = pendientes.some((c) => daysUntil(c.fecha_vencimiento) < 0)
  if (enMora) return 'mora'
  const proxima = pendientes.sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))[0]
  if (proxima && daysUntil(proxima.fecha_vencimiento) <= 7) return 'proximo'
  return 'ok'
}

function proximaCuota(prestamo: Prestamo): Cuota | null {
  return (
    prestamo.cuotas_detalle
      .filter((c) => c.estado !== 'COBRADA')
      .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))[0] ?? null
  )
}

// Saldo pendiente del préstamo = suma del saldo (monto − monto_pagado) de las
// cuotas no cobradas, en la moneda del préstamo.
function saldoPrestamo(prestamo: Prestamo): number {
  return prestamo.cuotas_detalle
    .filter((c) => c.estado !== 'COBRADA')
    .reduce((acc, c) => acc + (parseFloat(c.monto) - parseFloat(c.monto_pagado || '0')), 0)
}

const semaforoConfig: Record<Semaforo, { accent: string; borderColor: string; badgeBg: string; label: string }> = {
  mora:     { accent: 'var(--danger)',  borderColor: 'color-mix(in srgb, var(--danger) 50%, transparent)',  badgeBg: 'color-mix(in srgb, var(--danger) 12%, transparent)',  label: 'En mora' },
  proximo:  { accent: 'var(--warning)', borderColor: 'color-mix(in srgb, var(--warning) 50%, transparent)', badgeBg: 'color-mix(in srgb, var(--warning) 12%, transparent)', label: 'Vence pronto' },
  ok:       { accent: 'var(--success)', borderColor: 'color-mix(in srgb, var(--success) 45%, transparent)', badgeBg: 'color-mix(in srgb, var(--success) 12%, transparent)', label: 'Al día' },
  cancelado:{ accent: 'var(--text-2)', borderColor: 'var(--bd-008)', badgeBg: 'var(--bd-006)', label: 'Cancelado' },
}

const FRECUENCIAS: { value: Frecuencia; label: string }[] = [
  { value: 'DIARIA',    label: 'Diaria' },
  { value: 'SEMANAL',   label: 'Semanal' },
  { value: 'QUINCENAL', label: 'Quincenal' },
  { value: 'MENSUAL',   label: 'Mensual' },
  { value: 'ANUAL',     label: 'Anual' },
]

// ── Piezas compartidas de los modales de interés fijo ─────────────────────

const OVERLAY: React.CSSProperties = { position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }

function ModalShell({ titulo, subtitulo, children }: { titulo: string; subtitulo: string; children: React.ReactNode }) {
  return (
    <div style={OVERLAY}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 1 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>{titulo}</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{subtitulo}</p>
        </div>
        {children}
      </div>
    </div>
  )
}

/** Fila etiqueta/valor del resumen que abre cada modal de interés fijo. */
function FilaResumen({ label, value, destacado }: { label: string; value: string; destacado?: 'total' | 'mora' }) {
  const color = destacado === 'mora' ? 'var(--danger)' : destacado === 'total' ? 'var(--primary)' : 'var(--text-1)'
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', ...(destacado === 'total' ? { paddingTop: '0.35rem', borderTop: '1px solid var(--bd-006)' } : {}) }}>
      <span style={{ color: destacado ? color : 'rgba(100,116,139,0.7)' }}>{label}</span>
      <span style={{ color, fontWeight: destacado ? 700 : 600 }}>{value}</span>
    </div>
  )
}

function CajaResumen({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
      {children}
    </div>
  )
}

/** Cotización de entrada al stock: obligatoria al cobrar en dólares, porque sin
 *  costo declarado esos dólares no se van a poder vender (§Stock de dólares). */
function CampoCotizacionStock({ moneda, valor, onChange }: { moneda: Moneda; valor: string; onChange: (v: string) => void }) {
  if (moneda !== 'USD') return null
  return (
    <div>
      <label style={LABEL_STYLE}>Cotización de entrada al stock ($/USD)</label>
      <input type="number" step="0.000001" min="0.000001" value={valor} onChange={(e) => onChange(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
      <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.7)', marginTop: '0.25rem', lineHeight: 1.4 }}>
        A cuánto entran al stock los dólares que estás cobrando. Sin costo declarado no se pueden vender.
      </p>
    </div>
  )
}

function BotonesModal({ onClose, loading, disabled, texto }: { onClose: () => void; loading: boolean; disabled?: boolean; texto: string }) {
  return (
    <div style={{ display: 'flex', gap: '0.75rem' }}>
      <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
      <button type="submit" disabled={loading || disabled} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || disabled) ? 0.5 : 1 }}>
        {loading ? 'Guardando…' : texto}
      </button>
    </div>
  )
}

/** Casilla para decidir qué pasa con la mora acumulada. Es una decisión del
 *  operador, no un default del sistema: puede cobrarla junto o dejarla aparte. */
function CasillaMora({ monto, moneda, marcada, onChange, cuantos, textoOff }: { monto: number; moneda: Moneda; marcada: boolean; onChange: (v: boolean) => void; cuantos: number; textoOff: string }) {
  if (monto <= 0) return null
  return (
    <div style={{ background: 'color-mix(in srgb, var(--danger) 8%, transparent)', border: '1px solid color-mix(in srgb, var(--danger) 25%, transparent)', borderRadius: 'var(--r-md)', padding: '0.65rem 0.8rem' }}>
      <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', cursor: 'pointer' }}>
        <input type="checkbox" checked={marcada} onChange={(e) => onChange(e.target.checked)} style={{ marginTop: '2px', cursor: 'pointer' }} />
        <span style={{ fontFamily: FM, fontSize: '0.75rem', color: 'var(--text-1)', lineHeight: 1.45 }}>
          Cobrar también la <strong>mora acumulada</strong>: {fmtMonto(monto, moneda)} de {cuantos} período{cuantos > 1 ? 's' : ''} impago{cuantos > 1 ? 's' : ''}.
          {!marcada && <span style={{ display: 'block', color: 'var(--danger)', marginTop: '0.2rem' }}>{textoOff}</span>}
        </span>
      </label>
    </div>
  )
}

// ── Modal: cobrar interés / cancelar el préstamo ──────────────────────────

/** Los dos cobros del interés fijo comparten formulario porque comparten
 *  decisiones: por qué caja entra, en qué fecha y qué se hace con la mora. Lo
 *  único que cambia es qué se cobra — el interés del ciclo, o todo. */
function ModalInteresFijoCobro({
  prestamo, clienteNombre, modo, onClose, onSuccess,
}: {
  prestamo: Prestamo
  clienteNombre: string
  modo: 'interes' | 'cancelar'
  onClose: () => void
  onSuccess: () => void
}) {
  const toast = useToast()
  const vigente = periodoVigente(prestamo)
  const mora = moraAcumulada(prestamo)
  const capital = capitalPendiente(prestamo)
  const interesVigente = vigente ? saldoCuota(vigente) : 0

  const [incluirMora, setIncluirMora] = useState(modo === 'cancelar')
  const [medioPago, setMedioPago] = useState<MedioPago>('EFECTIVO')
  const [fechaCobro, setFechaCobro] = useState('')
  const [cotizacionStock, setCotizacionStock] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const total = modo === 'cancelar'
    ? totalCancelacion(prestamo, incluirMora)
    : interesVigente + (incluirMora ? mora : 0)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    const comun = {
      medio_pago: medioPago,
      fecha_cobro: fechaCobro || null,
      cotizacion_stock: prestamo.moneda === 'USD' ? parseFloat(cotizacionStock) : null,
    }
    try {
      if (modo === 'cancelar') {
        await cancelarInteresFijo(prestamo.id, { ...comun, incluir_mora: incluirMora })
        toast('success', incluirMora || mora === 0
          ? 'Préstamo cancelado'
          : 'Capital e interés cobrados · queda la mora por cobrar')
      } else {
        await cobrarInteres(prestamo.id, { ...comun, incluir_mora: incluirMora })
        toast('success', 'Interés cobrado')
      }
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <ModalShell
      titulo={modo === 'cancelar' ? 'Cancelar préstamo' : 'Cobrar interés'}
      subtitulo={modo === 'cancelar'
        ? `${clienteNombre} · capital + interés del período en curso`
        : `${clienteNombre} · período de 30 días`}
    >
      <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

        {modo === 'cancelar' && (
          <div style={{ background: 'color-mix(in srgb, var(--warning) 8%, transparent)', border: '1px solid color-mix(in srgb, var(--warning) 25%, transparent)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.8rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--warning)', lineHeight: 1.45 }}>
              El interés del período en curso se cobra <strong>completo</strong>, aunque falten días para que se cumpla. Es la regla del negocio: no hay prorrateo.
            </p>
          </div>
        )}

        <CajaResumen>
          {modo === 'cancelar' && <FilaResumen label="Capital pendiente" value={fmtMonto(capital, prestamo.moneda)} />}
          <FilaResumen
            label={vigente ? `Interés del período #${vigente.numero_cuota}` : 'Interés del período'}
            value={fmtMonto(interesVigente, prestamo.moneda)}
          />
          {incluirMora && mora > 0 && <FilaResumen label="Mora acumulada" value={fmtMonto(mora, prestamo.moneda)} destacado="mora" />}
          <FilaResumen label="Total a cobrar" value={fmtMonto(total, prestamo.moneda)} destacado="total" />
        </CajaResumen>

        <CasillaMora
          monto={mora}
          moneda={prestamo.moneda}
          marcada={incluirMora}
          onChange={setIncluirMora}
          cuantos={periodosEnMora(prestamo).length}
          textoOff={modo === 'cancelar'
            ? 'Sin marcar, el préstamo queda abierto por esa deuda hasta que la cobres.'
            : 'Sin marcar, solo se cobra el período en curso.'}
        />

        <SelectorMedioPago valor={medioPago} onChange={setMedioPago} />

        <div>
          <label style={LABEL_STYLE}>Fecha de cobro <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
          <input type="date" value={fechaCobro} onChange={(e) => setFechaCobro(e.target.value)} style={INPUT_STYLE} />
        </div>

        <CampoCotizacionStock moneda={prestamo.moneda} valor={cotizacionStock} onChange={setCotizacionStock} />

        {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171', margin: 0 }}>{error}</p>}

        <BotonesModal
          onClose={onClose}
          loading={loading}
          disabled={total <= 0}
          texto={modo === 'cancelar' ? 'Confirmar cancelación' : 'Confirmar cobro'}
        />
      </form>
    </ModalShell>
  )
}

// ── Modal: abonar capital ─────────────────────────────────────────────────

function ModalAbonarCapital({ prestamo, clienteNombre, onClose, onSuccess }: { prestamo: Prestamo; clienteNombre: string; onClose: () => void; onSuccess: () => void }) {
  const toast = useToast()
  const capital = capitalPendiente(prestamo)

  const [monto, setMonto] = useState('')
  const [medioPago, setMedioPago] = useState<MedioPago>('EFECTIVO')
  const [fechaCobro, setFechaCobro] = useState('')
  const [cotizacionStock, setCotizacionStock] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const montoNum = parseFloat(monto) || 0
  const excede = montoNum > capital

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (excede) { setError('El abono supera el capital pendiente.'); return }
    setError(null)
    setLoading(true)
    try {
      await abonarCapital(prestamo.id, {
        monto: montoNum,
        medio_pago: medioPago,
        fecha_cobro: fechaCobro || null,
        cotizacion_stock: prestamo.moneda === 'USD' ? parseFloat(cotizacionStock) : null,
      })
      toast('success', montoNum >= capital ? 'Capital saldado' : 'Capital abonado')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <ModalShell titulo="Abonar capital" subtitulo={`${clienteNombre} · devolución parcial o total`}>
      <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

        <div style={{ background: 'var(--ov-002)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.8rem' }}>
          <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.85)', lineHeight: 1.45 }}>
            Esto <strong>no toca el interés</strong>: baja lo que el cliente tiene prestado. Si devuelve todo el capital, dejan de nacer períodos nuevos.
          </p>
        </div>

        <div>
          <label style={LABEL_STYLE}>Capital a devolver</label>
          <input type="number" step="0.01" min="0.01" max={capital} value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="0,00" autoFocus required style={INPUT_STYLE} />
          <button type="button" onClick={() => setMonto(String(capital))}
            style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--primary)', background: 'transparent', border: 'none', cursor: 'pointer', marginTop: '0.35rem', padding: 0 }}>
            Devolvió todo ({fmtMonto(capital, prestamo.moneda)})
          </button>
        </div>

        <CajaResumen>
          <FilaResumen label="Capital pendiente hoy" value={fmtMonto(capital, prestamo.moneda)} />
          <FilaResumen label="Queda prestado" value={fmtMonto(Math.max(capital - montoNum, 0), prestamo.moneda)} destacado="total" />
        </CajaResumen>

        <SelectorMedioPago valor={medioPago} onChange={setMedioPago} />

        <div>
          <label style={LABEL_STYLE}>Fecha <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
          <input type="date" value={fechaCobro} onChange={(e) => setFechaCobro(e.target.value)} style={INPUT_STYLE} />
        </div>

        <CampoCotizacionStock moneda={prestamo.moneda} valor={cotizacionStock} onChange={setCotizacionStock} />

        {excede && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171', margin: 0 }}>El abono supera el capital pendiente ({fmtMonto(capital, prestamo.moneda)}).</p>}
        {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171', margin: 0 }}>{error}</p>}

        <BotonesModal onClose={onClose} loading={loading} disabled={montoNum <= 0 || excede} texto="Confirmar" />
      </form>
    </ModalShell>
  )
}

// ── Modal: editar el interés pactado ──────────────────────────────────────

function ModalEditarInteres({ prestamo, clienteNombre, onClose, onSuccess }: { prestamo: Prestamo; clienteNombre: string; onClose: () => void; onSuccess: () => void }) {
  const toast = useToast()
  const vigente = periodoVigente(prestamo)
  const sinPeriodos = prestamo.cuotas_detalle.length === 0
  const vigenteIntacto = !!vigente && parseFloat(vigente.monto_pagado || '0') === 0

  const [interes, setInteres] = useState(prestamo.monto_interes_fijo ?? '')
  const [diaCobro, setDiaCobro] = useState(prestamo.dia_cobro ?? '')
  const [aplicarVigente, setAplicarVigente] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const interesNum = parseFloat(interes) || 0
  const anterior = parseFloat(prestamo.monto_interes_fijo || '0')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await editarInteresFijo(prestamo.id, {
        monto_interes_fijo: interesNum,
        // La fecha de cobro es el ancla de los ciclos: solo viaja mientras no
        // haya períodos, que es lo único que el backend permite mover.
        ...(sinPeriodos && diaCobro ? { dia_cobro: diaCobro } : {}),
        aplicar_a_periodo_vigente: aplicarVigente,
      })
      toast('success', aplicarVigente ? 'Interés actualizado · rige desde este período' : 'Interés actualizado · rige desde el próximo período')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <ModalShell titulo="Editar interés" subtitulo={`${clienteNombre} · interés de cada período de 30 días`}>
      <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

        <div style={{ background: 'var(--ov-002)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.8rem' }}>
          <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.85)', lineHeight: 1.45 }}>
            Lo ya devengado queda con el interés que estaba pactado ese día. El valor nuevo rige <strong>de los próximos períodos en adelante</strong>.
          </p>
        </div>

        <div>
          <label style={LABEL_STYLE}>Interés por período</label>
          <input type="number" step="0.01" min="0.01" value={interes} onChange={(e) => setInteres(e.target.value)} autoFocus required style={INPUT_STYLE} />
          <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.7)', marginTop: '0.25rem' }}>
            Antes: {fmtMonto(anterior, prestamo.moneda)} cada 30 días.
          </p>
        </div>

        {sinPeriodos && (
          <div>
            <label style={LABEL_STYLE}>Fecha del primer cobro</label>
            <input type="date" value={diaCobro} onChange={(e) => setDiaCobro(e.target.value)} style={INPUT_STYLE} />
            <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.7)', marginTop: '0.25rem', lineHeight: 1.4 }}>
              Ancla de los ciclos de 30 días. Solo se puede mover mientras no haya ningún período devengado.
            </p>
          </div>
        )}

        {vigente && (
          <div style={{ background: 'var(--ov-002)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.65rem 0.8rem' }}>
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', cursor: vigenteIntacto ? 'pointer' : 'default', opacity: vigenteIntacto ? 1 : 0.6 }}>
              <input type="checkbox" checked={aplicarVigente} disabled={!vigenteIntacto} onChange={(e) => setAplicarVigente(e.target.checked)} style={{ marginTop: '2px' }} />
              <span style={{ fontFamily: FM, fontSize: '0.75rem', color: 'var(--text-1)', lineHeight: 1.45 }}>
                Aplicarlo también al período <strong>#{vigente.numero_cuota}</strong> (el que está en curso).
                {!vigenteIntacto && (
                  <span style={{ display: 'block', color: 'rgba(100,116,139,0.75)', marginTop: '0.2rem' }}>
                    Ese período ya tiene un pago imputado: no se le puede cambiar el interés.
                  </span>
                )}
              </span>
            </label>
          </div>
        )}

        {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171', margin: 0 }}>{error}</p>}

        <BotonesModal onClose={onClose} loading={loading} disabled={interesNum <= 0} texto="Guardar" />
      </form>
    </ModalShell>
  )
}

// ── Modal cobrar cuota ────────────────────────────────────────────────

function ModalCobrarCuota({
  prestamo,
  clienteNombre,
  onClose,
  onSuccess,
}: {
  prestamo: Prestamo
  clienteNombre: string
  onClose: () => void
  onSuccess: () => void
}) {
  const queryClient = useQueryClient()
  const toast = useToast()

  const pendientes = prestamo.cuotas_detalle
    .filter((c) => c.estado !== 'COBRADA')
    .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))

  const [cuotaIds, setCuotaIds] = useState<Set<string>>(
    () => new Set(pendientes[0]?.id ? [pendientes[0].id] : [])
  )
  const [metodo, setMetodo] = useState<'efectivo' | 'transferencia' | 'cheque'>('efectivo')
  const [fechaCobro, setFechaCobro] = useState('')

  const [nroCheque, setNroCheque] = useState('')
  const [banco, setBanco] = useState('')
  const [montoCheque, setMontoCheque] = useState('')
  const [pctCompra, setPctCompra] = useState('')
  const [fechaEmision, setFechaEmision] = useState('')
  const [fechaPago, setFechaPago] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const cuotasSeleccionadas = pendientes.filter((c) => cuotaIds.has(c.id))
  const totalSeleccionado = cuotasSeleccionadas.reduce((sum, c) => sum + parseFloat(c.monto), 0)

  function toggleCuota(id: string) {
    setCuotaIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    const ids = [...cuotaIds]
    const n = ids.length
    try {
      if (metodo === 'efectivo' || metodo === 'transferencia') {
        await cobrarCuotasLote(prestamo.id, { cuota_ids: ids, fecha_cobro: fechaCobro || null })
        toast('success', `${n} cuota${n > 1 ? 's' : ''} cobrada${n > 1 ? 's' : ''} en ${metodo}`)
      } else {
        await cobrarCuotasConChequeLote(prestamo.id, {
          cuota_ids: ids,
          nro_cheque: nroCheque.trim(),
          banco: banco.trim() || null,
          monto: parseFloat(montoCheque),
          porcentaje_compra: parseFloat(pctCompra) || 0,
          fecha_emision: fechaEmision || null,
          fecha_pago: fechaPago || null,
          cliente_origen_id: prestamo.cliente_id,
          fecha_cobro: fechaCobro || null,
        })
        queryClient.invalidateQueries({ queryKey: ['cartera'] })
        toast('success', `${n} cuota${n > 1 ? 's' : ''} cobrada${n > 1 ? 's' : ''} · cheque ingresado a cartera`)
      }
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', flexShrink: 0, background: MODAL_BG }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Cobrar cuota</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{clienteNombre} · {pendientes.length} cuota(s) pendiente(s)</p>
        </div>

        <form onSubmit={handleSubmit} style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

          {/* Lista de cuotas — zona scrolleable */}
          <div style={{ overflowY: 'auto', flex: '1 1 auto', minHeight: 0, padding: '1.25rem 1.5rem 0.75rem' }}>
            <p style={LABEL_STYLE}>Seleccioná las cuotas a cobrar</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              {pendientes.map((c) => {
                const mora = daysUntil(c.fecha_vencimiento) < 0
                const selected = cuotaIds.has(c.id)
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => toggleCuota(c.id)}
                    style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '0.6rem 0.875rem',
                      borderRadius: 'var(--r-md)',
                      border: selected ? '1px solid var(--primary)' : '1px solid var(--bd-008)',
                      background: selected ? 'color-mix(in srgb, var(--primary) 10%, transparent)' : 'var(--ov-002)',
                      cursor: 'pointer', textAlign: 'left', transition: 'all 0.12s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
                      <div style={{
                        width: 15, height: 15, borderRadius: '3px', flexShrink: 0,
                        border: selected ? '2px solid var(--primary)' : '2px solid var(--bd-012)',
                        background: selected ? 'var(--primary)' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        transition: 'all 0.12s ease',
                      }}>
                        {selected && <span style={{ color: '#fff', fontSize: '0.55rem', fontWeight: 900, lineHeight: 1 }}>✓</span>}
                      </div>
                      <span style={{ fontFamily: FM, fontSize: '0.8rem', fontWeight: selected ? 700 : 500, color: selected ? 'var(--primary)' : 'var(--text-1)' }}>
                        Cuota {c.numero_cuota}
                      </span>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span style={{ display: 'block', fontFamily: FM, fontSize: '0.78rem', fontWeight: 700, color: selected ? 'var(--primary)' : 'var(--text-1)' }}>
                        {fmtMonto(c.monto, prestamo.moneda)}
                      </span>
                      <span style={{ display: 'block', fontFamily: FM, fontSize: '0.65rem', color: mora ? 'var(--danger)' : 'rgba(100,116,139,0.6)', marginTop: '1px' }}>
                        {fmtDate(c.fecha_vencimiento)}{mora ? ' · en mora' : ''}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Parte inferior fija */}
          <div style={{ flexShrink: 0, borderTop: '1px solid var(--bd-006)', padding: '0.75rem 1.5rem 1.25rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

            {cuotaIds.size > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: FM, fontSize: '0.72rem', color: 'var(--primary)', background: 'color-mix(in srgb, var(--primary) 6%, transparent)', borderRadius: 'var(--r-md)', padding: '0.4rem 0.75rem' }}>
                <span>{cuotaIds.size} cuota{cuotaIds.size > 1 ? 's' : ''} seleccionada{cuotaIds.size > 1 ? 's' : ''}</span>
                <span style={{ fontWeight: 700 }}>{fmtMonto(totalSeleccionado, prestamo.moneda)}</span>
              </div>
            )}

            {/* Método de pago */}
            {cuotaIds.size > 0 && (
              <div>
                <p style={LABEL_STYLE}>Método de cobro</p>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  {(['efectivo', 'transferencia', 'cheque'] as const).map((m) => (
                    <button key={m} type="button" onClick={() => setMetodo(m)}
                      style={{ ...(metodo === m ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.72rem' }}>
                      {m === 'efectivo' ? 'Efectivo' : m === 'transferencia' ? 'Transferencia' : 'Cheque'}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Fecha de cobro (efectivo / transferencia) */}
            {cuotaIds.size > 0 && (metodo === 'efectivo' || metodo === 'transferencia') && (
              <div>
                <label style={LABEL_STYLE}>Fecha de cobro <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
                <input type="date" value={fechaCobro} onChange={(e) => setFechaCobro(e.target.value)} style={INPUT_STYLE} />
              </div>
            )}

            {/* Campos cheque */}
            {cuotaIds.size > 0 && metodo === 'cheque' && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                  <div>
                    <label style={LABEL_STYLE}>Nº de cheque</label>
                    <input type="text" value={nroCheque} onChange={(e) => setNroCheque(e.target.value)} placeholder="Número" required style={INPUT_STYLE} />
                  </div>
                  <div>
                    <label style={LABEL_STYLE}>Banco <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
                    <input type="text" value={banco} onChange={(e) => setBanco(e.target.value)} placeholder="Banco" style={INPUT_STYLE} />
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                  <div>
                    <label style={LABEL_STYLE}>Monto nominal</label>
                    <input type="number" step="0.01" min="0.01" value={montoCheque} onChange={(e) => setMontoCheque(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                  </div>
                  <div>
                    <label style={LABEL_STYLE}>% de compra</label>
                    <input type="number" step="0.0001" min="0" max="100" value={pctCompra} onChange={(e) => setPctCompra(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                  <div>
                    <label style={LABEL_STYLE}>Fecha emisión</label>
                    <input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} style={INPUT_STYLE} />
                  </div>
                  <div>
                    <label style={LABEL_STYLE}>Fecha de pago</label>
                    <input type="date" value={fechaPago} onChange={(e) => setFechaPago(e.target.value)} style={INPUT_STYLE} />
                  </div>
                </div>
                <div>
                  <label style={LABEL_STYLE}>Fecha de cobro <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
                  <input type="date" value={fechaCobro} onChange={(e) => setFechaCobro(e.target.value)} style={INPUT_STYLE} />
                </div>
                {parseFloat(montoCheque) > 0 && parseFloat(pctCompra) >= 0 && (
                  <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.65rem 1rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                      <span style={{ color: 'rgba(100,116,139,0.7)' }}>Valor neto del cheque</span>
                      <span style={{ color: 'var(--text-1)', fontWeight: 700 }}>
                        {fmtMonto(parseFloat(montoCheque) * (100 - (parseFloat(pctCompra) || 0)) / 100, prestamo.moneda)}
                      </span>
                    </div>
                  </div>
                )}
              </>
            )}

            {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171', margin: 0 }}>{error}</p>}

            <div style={{ display: 'flex', gap: '0.75rem' }}>
              <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
              <button type="submit" disabled={loading || cuotaIds.size === 0}
                style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || cuotaIds.size === 0) ? 0.5 : 1 }}>
                {loading ? 'Guardando…' : cuotaIds.size > 1 ? `Cobrar ${cuotaIds.size} cuotas` : 'Confirmar cobro'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal nuevo préstamo ──────────────────────────────────────────────

function ModalNuevoPrestamo({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [tipo, setTipo] = useState<PrestamoTipo>('NORMAL')
  const [clienteId, setClienteId] = useState('')
  const [credito, setCredito] = useState('')
  const [moneda, setMoneda] = useState<Moneda>('ARS')
  const [cuotas, setCuotas] = useState('')
  const [frecuencia, setFrecuencia] = useState<Frecuencia>('MENSUAL')
  const [totalACobrar, setTotalACobrar] = useState('')
  const [fechaInicio, setFechaInicio] = useState('')
  // Solo interés fijo
  const [interesFijo, setInteresFijo] = useState('')
  const [diaCobro, setDiaCobro] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [mostrandoNuevoCliente, setMostrandoNuevoCliente] = useState(false)
  const [nuevoNombre, setNuevoNombre] = useState('')
  const [nuevoTelefono, setNuevoTelefono] = useState('')
  const [cargandoCliente, setCargandoCliente] = useState(false)
  const [errorCliente, setErrorCliente] = useState<string | null>(null)

  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const esFijo = tipo === 'INTERES_FIJO'
  const creditoNum = parseFloat(credito) || 0
  const totalNum = parseFloat(totalACobrar) || 0
  const cuotasNum = parseInt(cuotas) || 0
  const interesNum = parseFloat(interesFijo) || 0
  const ganancia = totalNum - creditoNum
  const montoCuota = cuotasNum > 0 ? totalNum / cuotasNum : 0
  const showPreview = esFijo
    ? creditoNum > 0 && interesNum > 0
    : creditoNum > 0 && totalNum >= creditoNum && cuotasNum > 0

  async function handleCrearCliente() {
    if (!nuevoNombre.trim()) return
    setCargandoCliente(true)
    setErrorCliente(null)
    try {
      const nuevo = await createCliente({ nombre: nuevoNombre.trim(), telefono: nuevoTelefono.trim() || null })
      queryClient.setQueryData<Cliente[]>(['clientes'], (prev) => [...(prev ?? []), nuevo])
      setClienteId(nuevo.id)
      setMostrandoNuevoCliente(false)
      setNuevoNombre('')
      setNuevoTelefono('')
    } catch (err) {
      setErrorCliente((err as Error).message)
    } finally {
      setCargandoCliente(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!esFijo && totalNum < creditoNum) { setError('El total a cobrar debe ser mayor o igual al capital.'); return }
    setError(null)
    setLoading(true)
    try {
      // Las dos modalidades no comparten campos: mandar los de la otra hace que
      // el backend rechace la carga, y con razón — sería una carga ambigua.
      await createPrestamo(esFijo
        ? {
            cliente_id: clienteId, tipo_prestamo: 'INTERES_FIJO', credito: creditoNum, moneda,
            monto_interes_fijo: interesNum, dia_cobro: diaCobro || null, fecha_inicio: fechaInicio || null,
          }
        : {
            cliente_id: clienteId, tipo_prestamo: 'NORMAL', credito: creditoNum, moneda,
            cuotas: cuotasNum, frecuencia, total_a_cobrar: totalNum, fecha_inicio: fechaInicio || null,
          })
      toast('success', esFijo ? 'Préstamo a interés fijo creado' : 'Préstamo creado correctamente')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '400px', maxHeight: '92dvh', overflowY: 'auto' }}>

        {/* Header */}
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 1 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Nuevo préstamo</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Completá los datos de la operación</p>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>

          {/* Modalidad — lo primero, porque cambia todo el resto del formulario */}
          <div>
            <label style={LABEL_STYLE}>Modalidad</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {([
                { valor: 'NORMAL' as PrestamoTipo, titulo: 'En cuotas', ayuda: 'Cuadro cerrado' },
                { valor: 'INTERES_FIJO' as PrestamoTipo, titulo: 'Interés fijo', ayuda: 'Cada 30 días' },
              ]).map((o) => (
                <button key={o.valor} type="button" onClick={() => setTipo(o.valor)}
                  style={{ ...(tipo === o.valor ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.5rem', fontSize: '0.78rem', display: 'flex', flexDirection: 'column', gap: '1px', lineHeight: 1.2 }}>
                  <span>{o.titulo}</span>
                  <span style={{ fontSize: '0.62rem', opacity: 0.75, fontWeight: 400 }}>{o.ayuda}</span>
                </button>
              ))}
            </div>
            <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.7)', marginTop: '0.35rem', lineHeight: 1.45 }}>
              {esFijo
                ? 'El capital queda prestado y no se amortiza: se cobra un interés fijo cada 30 días y el capital vuelve cuando el cliente lo devuelve.'
                : 'Capital y ganancia repartidos en un cuadro de cuotas que se genera entero al alta.'}
            </p>
          </div>

          {/* Cliente */}
          <div>
            <label style={LABEL_STYLE}>Cliente</label>
            {!mostrandoNuevoCliente ? (
              <>
                <select value={clienteId} onChange={(e) => setClienteId(e.target.value)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                  <option value="">Seleccionar cliente…</option>
                  {clientes?.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
                <button type="button" onClick={() => { setMostrandoNuevoCliente(true); setClienteId('') }}
                  style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--primary)', background: 'transparent', border: 'none', cursor: 'pointer', marginTop: '0.35rem', padding: 0 }}>
                  + Agregar cliente nuevo
                </button>
              </>
            ) : (
              <div style={{ border: '1px solid var(--bd-008)', borderRadius: 'var(--r-md)', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem', background: 'var(--ov-002)' }}>
                <p style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--primary)' }}>Nuevo cliente</p>
                <input type="text" value={nuevoNombre} onChange={(e) => setNuevoNombre(e.target.value)} placeholder="Nombre *" autoFocus style={INPUT_STYLE} />
                <input type="text" value={nuevoTelefono} onChange={(e) => setNuevoTelefono(e.target.value)} placeholder="Teléfono (opcional)" style={INPUT_STYLE} />
                {errorCliente && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#f87171' }}>{errorCliente}</p>}
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button type="button" onClick={() => { setMostrandoNuevoCliente(false); setErrorCliente(null) }} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.4rem', fontSize: '0.72rem' }}>Volver</button>
                  <button type="button" onClick={handleCrearCliente} disabled={cargandoCliente || !nuevoNombre.trim()} style={{ ...btnSolid('primary'), flex: 1, padding: '0.4rem', fontSize: '0.72rem', opacity: (cargandoCliente || !nuevoNombre.trim()) ? 0.5 : 1 }}>
                    {cargandoCliente ? 'Creando…' : 'Crear cliente'}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Moneda */}
          <div>
            <label style={LABEL_STYLE}>Moneda</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {(['ARS', 'USD'] as Moneda[]).map((m) => (
                <button key={m} type="button" onClick={() => setMoneda(m)}
                  style={{ ...(moneda === m ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.8rem' }}>
                  {m}
                </button>
              ))}
            </div>
          </div>

          {/* Capital y Total */}
          <div style={{ display: 'grid', gridTemplateColumns: esFijo ? '1fr' : '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={LABEL_STYLE}>Capital</label>
              <input type="number" step="0.01" min="0.01" value={credito} onChange={(e) => setCredito(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
            </div>
            {!esFijo && (
              <div>
                <label style={LABEL_STYLE}>Total a cobrar</label>
                <input type="number" step="0.01" min="0.01" value={totalACobrar} onChange={(e) => setTotalACobrar(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
              </div>
            )}
          </div>

          {/* Cuotas y Frecuencia — solo el préstamo con cuadro */}
          {!esFijo && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div>
                <label style={LABEL_STYLE}>Cuotas</label>
                <input type="number" step="1" min="1" value={cuotas} onChange={(e) => setCuotas(e.target.value)} placeholder="1" required style={INPUT_STYLE} />
              </div>
              <div>
                <label style={LABEL_STYLE}>Frecuencia</label>
                <select value={frecuencia} onChange={(e) => setFrecuencia(e.target.value as Frecuencia)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                  {FRECUENCIAS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                </select>
              </div>
            </div>
          )}

          {/* Interés y fecha de cobro — solo el préstamo a interés fijo */}
          {esFijo && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div>
                <label style={LABEL_STYLE}>Interés por período</label>
                <input type="number" step="0.01" min="0.01" value={interesFijo} onChange={(e) => setInteresFijo(e.target.value)} placeholder="0,00" required style={INPUT_STYLE} />
              </div>
              <div>
                <label style={LABEL_STYLE}>Primer cobro <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
                <input type="date" value={diaCobro} onChange={(e) => setDiaCobro(e.target.value)} style={INPUT_STYLE} />
              </div>
            </div>
          )}
          {esFijo && (
            <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.7)', marginTop: '-0.5rem', lineHeight: 1.45 }}>
              El interés va <strong>en plata, no en porcentaje</strong>. Si no ponés fecha de primer cobro, se toma a los 30 días de la entrega.
            </p>
          )}

          {/* Fecha inicio */}
          <div>
            <label style={LABEL_STYLE}>Fecha de {esFijo ? 'entrega' : 'inicio'} <span style={{ textTransform: 'none', fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label>
            <input type="date" value={fechaInicio} onChange={(e) => setFechaInicio(e.target.value)} style={INPUT_STYLE} />
          </div>

          {/* Preview */}
          {showPreview && esFijo && (
            <CajaResumen>
              <FilaResumen label="Capital prestado" value={fmtMonto(creditoNum, moneda)} />
              <FilaResumen label="Interés cada 30 días" value={fmtMonto(interesNum, moneda)} />
              <FilaResumen label="Al año (12 períodos)" value={fmtMonto(interesNum * 12, moneda)} destacado="total" />
              <p style={{ fontFamily: FM, fontSize: '0.68rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.15rem', lineHeight: 1.4 }}>
                El total real depende de cuántos períodos dure: el capital vuelve cuando el cliente lo devuelve.
              </p>
            </CajaResumen>
          )}
          {showPreview && !esFijo && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {[
                { label: 'Capital', value: fmtMonto(creditoNum, moneda), color: 'var(--text-1)' },
                { label: 'Total a cobrar', value: fmtMonto(totalNum, moneda), color: 'var(--text-1)' },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                  <span style={{ color: 'rgba(100,116,139,0.7)' }}>{label}</span>
                  <span style={{ color, fontWeight: 600 }}>{value}</span>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.35rem', borderTop: '1px solid var(--bd-006)' }}>
                <span style={{ color: 'var(--success)', fontWeight: 700 }}>Ganancia</span>
                <span style={{ color: 'var(--success)', fontWeight: 700 }}>{fmtMonto(ganancia, moneda)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.72rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.6)' }}>Cuota aprox.</span>
                <span style={{ color: 'rgba(100,116,139,0.6)' }}>{fmtMonto(montoCuota, moneda)}</span>
              </div>
            </div>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading || mostrandoNuevoCliente} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: (loading || mostrandoNuevoCliente) ? 0.5 : 1 }}>
              {loading ? 'Guardando…' : 'Confirmar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal editar préstamo ─────────────────────────────────────────────

function ModalEditarPrestamo({ prestamo, clienteNombre, onClose, onSuccess }: { prestamo: Prestamo; clienteNombre: string; onClose: () => void; onSuccess: () => void }) {
  const toast = useToast()
  const [credito, setCredito] = useState(prestamo.credito)
  const [moneda, setMoneda] = useState<Moneda>(prestamo.moneda)
  const [cuotas, setCuotas] = useState(String(prestamo.cuotas))
  const [frecuencia, setFrecuencia] = useState<Frecuencia>(prestamo.frecuencia)
  const [totalACobrar, setTotalACobrar] = useState(prestamo.total_a_cobrar)
  const [fechaInicio, setFechaInicio] = useState(prestamo.fecha_inicio)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const creditoNum = parseFloat(credito) || 0
  const totalNum = parseFloat(totalACobrar) || 0
  const cuotasNum = parseInt(cuotas) || 0
  const ganancia = totalNum - creditoNum
  const montoCuota = cuotasNum > 0 ? totalNum / cuotasNum : 0
  const showPreview = creditoNum > 0 && totalNum >= creditoNum && cuotasNum > 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (totalNum < creditoNum) { setError('El total a cobrar debe ser mayor o igual al capital.'); return }
    setError(null)
    setLoading(true)
    try {
      await editarPrestamo(prestamo.id, { credito: creditoNum, moneda, cuotas: cuotasNum, frecuencia, total_a_cobrar: totalNum, fecha_inicio: fechaInicio || null })
      toast('success', 'Préstamo actualizado · cuotas regeneradas')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '400px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 1 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Editar préstamo</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{clienteNombre} · regenera el cuadro de cuotas</p>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ background: 'color-mix(in srgb, var(--warning) 8%, transparent)', border: '1px solid color-mix(in srgb, var(--warning) 25%, transparent)', borderRadius: 'var(--r-md)', padding: '0.6rem 0.8rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--warning)', lineHeight: 1.4 }}>Cambiar capital, total, cantidad o frecuencia <strong>recalcula todas las cuotas</strong> (incluidas sus fechas).</p>
          </div>

          <div>
            <label style={LABEL_STYLE}>Moneda</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {(['ARS', 'USD'] as Moneda[]).map((m) => (
                <button key={m} type="button" onClick={() => setMoneda(m)}
                  style={{ ...(moneda === m ? btnSolid('primary') : btnBordered('neutral')), flex: 1, padding: '0.45rem', fontSize: '0.8rem' }}>
                  {m}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={LABEL_STYLE}>Capital</label>
              <input type="number" step="0.01" min="0.01" value={credito} onChange={(e) => setCredito(e.target.value)} required style={INPUT_STYLE} />
            </div>
            <div>
              <label style={LABEL_STYLE}>Total a cobrar</label>
              <input type="number" step="0.01" min="0.01" value={totalACobrar} onChange={(e) => setTotalACobrar(e.target.value)} required style={INPUT_STYLE} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={LABEL_STYLE}>Cuotas</label>
              <input type="number" step="1" min="1" value={cuotas} onChange={(e) => setCuotas(e.target.value)} required style={INPUT_STYLE} />
            </div>
            <div>
              <label style={LABEL_STYLE}>Frecuencia</label>
              <select value={frecuencia} onChange={(e) => setFrecuencia(e.target.value as Frecuencia)} required style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
                {FRECUENCIAS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label style={LABEL_STYLE}>Fecha de inicio</label>
            <input type="date" value={fechaInicio} onChange={(e) => setFechaInicio(e.target.value)} style={INPUT_STYLE} />
          </div>

          {showPreview && (
            <div style={{ background: 'var(--ov-003)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {[
                { label: 'Capital', value: fmtMonto(creditoNum, moneda) },
                { label: 'Total a cobrar', value: fmtMonto(totalNum, moneda) },
              ].map(({ label, value }) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                  <span style={{ color: 'rgba(100,116,139,0.7)' }}>{label}</span>
                  <span style={{ color: 'var(--text-1)', fontWeight: 600 }}>{value}</span>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.35rem', borderTop: '1px solid var(--bd-006)' }}>
                <span style={{ color: 'var(--success)', fontWeight: 700 }}>Ganancia</span>
                <span style={{ color: 'var(--success)', fontWeight: 700 }}>{fmtMonto(ganancia, moneda)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.72rem' }}>
                <span style={{ color: 'rgba(100,116,139,0.6)' }}>Cuota aprox.</span>
                <span style={{ color: 'rgba(100,116,139,0.6)' }}>{fmtMonto(montoCuota, moneda)}</span>
              </div>
            </div>
          )}

          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: loading ? 0.5 : 1 }}>
              {loading ? 'Guardando…' : 'Guardar cambios'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Cuerpo de la tarjeta de un préstamo a interés fijo ────────────────

/** Lo que el operador necesita ver de un vistazo es otra cosa que en el
 *  préstamo con cuotas: no "cuántas faltan", sino cuánto capital sigue afuera,
 *  cuánto interés se debe y cuándo entra el próximo. */
function PanelInteresFijo({ prestamo }: { prestamo: Prestamo }) {
  const vigente = periodoVigente(prestamo)
  const mora = moraAcumulada(prestamo)
  const capital = capitalPendiente(prestamo)
  const proxima = proximaFechaCobro(prestamo)
  const interesVigente = vigente && vigente.estado !== 'COBRADA' ? saldoCuota(vigente) : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', marginBottom: '0.25rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
        <span style={{ color: 'rgba(100,116,139,0.7)' }}>Capital pendiente</span>
        <span style={{ color: 'var(--text-1)', fontWeight: 700 }}>{fmtMonto(capital, prestamo.moneda)}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
        <span style={{ color: 'rgba(100,116,139,0.7)' }}>Interés cada 30 días</span>
        <span style={{ color: 'var(--text-1)', fontWeight: 600 }}>{fmtMonto(prestamo.monto_interes_fijo ?? '0', prestamo.moneda)}</span>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.25rem', borderTop: '1px solid var(--bd-006)' }}>
        <span style={{ color: 'rgba(100,116,139,0.7)' }}>
          {vigente ? `Período #${vigente.numero_cuota}` : 'Período en curso'}
        </span>
        <span style={{ color: interesVigente > 0 ? 'var(--warning)' : 'var(--success)', fontWeight: 700 }}>
          {vigente
            ? (interesVigente > 0 ? `${fmtMonto(interesVigente, prestamo.moneda)} impago` : 'al día')
            : 'sin devengar'}
        </span>
      </div>

      {mora > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
          <span style={{ color: 'var(--danger)' }}>
            Mora ({periodosEnMora(prestamo).length} período{periodosEnMora(prestamo).length > 1 ? 's' : ''})
          </span>
          <span style={{ color: 'var(--danger)', fontWeight: 700 }}>{fmtMonto(mora, prestamo.moneda)}</span>
        </div>
      )}

      {proxima && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.72rem' }}>
          <span style={{ color: 'rgba(100,116,139,0.6)' }}>Próximo cobro</span>
          <span style={{ color: 'rgba(100,116,139,0.6)' }}>{fmtDate(proxima)}</span>
        </div>
      )}
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function DeudoresPrestamos() {
  const [creandoPrestamo, setCreandoPrestamo] = useState(false)
  const [cobrandoCuota, setCobrandoCuota] = useState<Prestamo | null>(null)
  const [pagoLibre, setPagoLibre] = useState<DeudaItem | null>(null)
  const [editandoPrestamo, setEditandoPrestamo] = useState<Prestamo | null>(null)
  const [eliminandoPrestamo, setEliminandoPrestamo] = useState<Prestamo | null>(null)
  // Interés fijo: el cobro del interés y la cancelación comparten modal.
  const [cobroFijo, setCobroFijo] = useState<{ prestamo: Prestamo; modo: 'interes' | 'cancelar' } | null>(null)
  const [abonandoCapital, setAbonandoCapital] = useState<Prestamo | null>(null)
  const [editandoInteres, setEditandoInteres] = useState<Prestamo | null>(null)
  const queryClient = useQueryClient()

  const { data: prestamos, isLoading: loadingP, error: errP } = useQuery({
    queryKey: ['prestamos'],
    queryFn: () => getPrestamos(),
    refetchInterval: 30_000,
  })

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: getClientes,
    staleTime: 60_000,
  })

  const clienteMap = new Map(clientes?.map((c) => [c.id, c.nombre]) ?? [])

  const activos = (prestamos ?? [])
    .filter((p) => p.estado === 'ACTIVO')
    .sort((a, b) => {
      const sa = getSemaforo(a)
      const sb = getSemaforo(b)
      const order: Record<Semaforo, number> = { mora: 0, proximo: 1, ok: 2, cancelado: 3 }
      return order[sa] - order[sb]
    })

  const cancelados = (prestamos ?? []).filter((p) => p.estado !== 'ACTIVO')

  function handleNuevoPrestamo() {
    setCreandoPrestamo(false)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    queryClient.invalidateQueries({ queryKey: ['clientes'] })
  }

  function handleCobrarCuota() {
    setCobrandoCuota(null)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
  }

  function handlePagoLibre() {
    setPagoLibre(null)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
  }

  function handleEditarPrestamo() {
    setEditandoPrestamo(null)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
  }

  function handleEliminarPrestamo() {
    setEliminandoPrestamo(null)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    // La baja revierte el otorgamiento y los cobros de cuota asentados en caja.
    queryClient.invalidateQueries({ queryKey: ['reporte-caja'] })
    queryClient.invalidateQueries({ queryKey: ['reporte'] })
    queryClient.invalidateQueries({ queryKey: ['movimientos-unificados'] })
  }

  /** Toda operación de interés fijo mueve caja: hay que refrescar el reporte
   *  además de la lista, o el panel muestra un cierre viejo. */
  function handleOperacionInteresFijo() {
    setCobroFijo(null)
    setAbonandoCapital(null)
    setEditandoInteres(null)
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    queryClient.invalidateQueries({ queryKey: ['reporte-caja'] })
    queryClient.invalidateQueries({ queryKey: ['reporte'] })
    queryClient.invalidateQueries({ queryKey: ['movimientos-unificados'] })
  }

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>

      {/* Leyenda + botón Nuevo */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <div>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', color: 'rgba(100,116,139,0.7)' }}>Semáforo de cuotas activas</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginTop: '0.35rem' }}>
            {(['mora', 'proximo', 'ok'] as Semaforo[]).map((s) => (
              <span key={s} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: FM, fontSize: '0.7rem', color: 'rgba(148,163,184,0.6)' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: semaforoConfig[s].accent, display: 'inline-block' }} />
                {semaforoConfig[s].label}
              </span>
            ))}
          </div>
        </div>
        <button
          onClick={() => setCreandoPrestamo(true)}
          style={{ ...btnSolid('primary'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', padding: '0.45rem 0.875rem' }}
        >
          <IconPlus size={15} />Nuevo
        </button>
      </div>

      {loadingP && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" style={{ marginBottom: '2rem' }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} style={{ background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-card)', padding: '1.1rem 1.2rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><Skeleton w="50%" h={14} /><Skeleton w={64} h={16} /></div>
              <Skeleton w="40%" h={11} style={{ marginTop: '1rem' }} />
              <Skeleton w="65%" h={11} style={{ marginTop: '0.5rem' }} />
              <Skeleton w="100%" h={4} r={999} style={{ marginTop: '1.1rem' }} />
            </div>
          ))}
        </div>
      )}
      {errP && <div style={{ textAlign: 'center', color: '#f87171', padding: '3rem', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar préstamos.</div>}

      {activos.length === 0 && !loadingP && (
        <div style={{ textAlign: 'center', color: 'rgba(100,116,139,0.6)', padding: '3rem' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>🎉</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600 }}>No hay préstamos activos</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" style={{ marginBottom: '2rem' }}>
        {activos.map((p) => {
          const sem = getSemaforo(p)
          const cfg = semaforoConfig[sem]
          const proxima = proximaCuota(p)
          const cobradas = p.cuotas_detalle.filter((c) => c.estado === 'COBRADA').length
          const nombre = clienteMap.get(p.cliente_id) ?? '…'

          return (
            <div key={p.id} className="lift" style={{ background: 'var(--surface-grad)', border: `1px solid ${cfg.borderColor}`, borderRadius: 'var(--r-lg)', boxShadow: `var(--shadow-card), 0 0 0 1px ${cfg.borderColor}`, padding: '1.1rem 1.2rem' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem', marginBottom: '0.875rem' }}>
                <div style={{ minWidth: 0 }}>
                  <h3 style={{ fontFamily: FM, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word' }}>{nombre}</h3>
                  {esInteresFijo(p) && (
                    <span style={{ display: 'inline-block', fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--primary)', background: 'color-mix(in srgb, var(--primary) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--primary) 30%, transparent)', padding: '1px 6px', marginTop: '3px' }}>
                      Interés fijo
                    </span>
                  )}
                </div>
                <span style={{ fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, color: cfg.accent, background: cfg.badgeBg, border: `1px solid ${cfg.borderColor}`, padding: '2px 8px', letterSpacing: '0.05em', flexShrink: 0 }}>
                  {cfg.label}
                </span>
              </div>

              {esInteresFijo(p) ? (
                <PanelInteresFijo prestamo={p} />
              ) : (
                <>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', marginBottom: '0.875rem' }}>
                    {[
                      { label: 'Capital', value: fmtMonto(p.credito, p.moneda) },
                      { label: 'Total a cobrar', value: fmtMonto(p.total_a_cobrar, p.moneda) },
                    ].map(({ label, value }) => (
                      <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.78rem' }}>
                        <span style={{ color: 'rgba(100,116,139,0.7)' }}>{label}</span>
                        <span style={{ color: 'var(--text-1)', fontWeight: 600 }}>{value}</span>
                      </div>
                    ))}
                    {proxima && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', fontFamily: FM, fontSize: '0.78rem', paddingTop: '0.25rem', borderTop: '1px solid var(--bd-006)' }}>
                        <span style={{ color: 'rgba(100,116,139,0.7)', flexShrink: 0 }}>Próxima cuota</span>
                        <div style={{ textAlign: 'right', color: 'var(--text-1)', fontWeight: 600 }}>
                          <span style={{ display: 'block', fontSize: '0.72rem', color: 'rgba(148,163,184,0.65)' }}>{fmtDate(proxima.fecha_vencimiento)}</span>
                          <span style={{ display: 'block' }}>{fmtMonto(proxima.monto, p.moneda)}</span>
                        </div>
                      </div>
                    )}
                  </div>

                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: FM, fontSize: '0.62rem', color: 'rgba(100,116,139,0.6)', marginBottom: '0.3rem' }}>
                      <span>{cobradas} de {p.cuotas} cuotas</span>
                      <span style={{ textTransform: 'lowercase' }}>{p.frecuencia}</span>
                    </div>
                    <div style={{ display: 'flex', gap: '2px' }}>
                      {Array.from({ length: p.cuotas }).map((_, i) => (
                        <div key={i} style={{ flex: 1, height: '4px', borderRadius: '2px', background: i < cobradas ? cfg.accent : 'var(--bd-006)', transition: 'background 0.3s ease' }} />
                      ))}
                    </div>
                  </div>
                </>
              )}

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.75rem' }}>
                {esInteresFijo(p) ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setCobroFijo({ prestamo: p, modo: 'interes' })}
                      title="Cobrar el interés del período en curso (y la mora, si querés)"
                      style={{ ...btnSolid('primary'), flex: '1 1 8rem', padding: '0.45rem', fontSize: '0.75rem', textAlign: 'center' }}
                    >
                      Cobrar interés
                    </button>
                    <button
                      type="button"
                      onClick={() => setAbonandoCapital(p)}
                      title="Recibir capital de vuelta, total o parcial. No toca el interés."
                      style={{ ...btnBordered('primary'), flex: '1 1 8rem', padding: '0.45rem', fontSize: '0.75rem', textAlign: 'center' }}
                    >
                      Abonar capital
                    </button>
                    <button
                      type="button"
                      onClick={() => setCobroFijo({ prestamo: p, modo: 'cancelar' })}
                      title="Liquidar: capital pendiente + interés del período en curso"
                      style={{ ...btnBordered('primary'), flex: '1 1 8rem', padding: '0.45rem', fontSize: '0.75rem', textAlign: 'center' }}
                    >
                      Cancelar
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditandoInteres(p)}
                      title="Renegociar el interés de cada período"
                      style={{ ...btnBordered('neutral'), flex: '1 1 8rem', padding: '0.45rem 0.8rem', fontSize: '0.75rem', textAlign: 'center' }}
                    >
                      Editar interés
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => setCobrandoCuota(p)}
                      style={{ ...btnSolid('primary'), flex: '1 1 8rem', padding: '0.45rem', fontSize: '0.75rem', textAlign: 'center' }}
                    >
                      Cobrar cuota
                    </button>
                    <button
                      type="button"
                      onClick={() => setPagoLibre({
                        tipo: 'prestamo',
                        id: p.id,
                        clienteNombre: nombre,
                        label: `Préstamo · ${p.cuotas - cobradas}/${p.cuotas} cuota${p.cuotas > 1 ? 's' : ''} pend.`,
                        saldo: saldoPrestamo(p),
                        moneda: p.moneda,
                      })}
                      title="Pagar un importe libre (parcial o total), en cualquier moneda"
                      style={{ ...btnBordered('primary'), flex: '1 1 8rem', padding: '0.45rem', fontSize: '0.75rem', textAlign: 'center' }}
                    >
                      Pago libre
                    </button>
                    {cobradas === 0 && (
                      <button
                        type="button"
                        onClick={() => setEditandoPrestamo(p)}
                        title="Corregir la carga del préstamo"
                        style={{ ...btnBordered('neutral'), flex: '1 1 8rem', padding: '0.45rem 0.8rem', fontSize: '0.75rem', textAlign: 'center' }}
                      >
                        Editar
                      </button>
                    )}
                  </>
                )}
                <button
                  type="button"
                  onClick={() => setEliminandoPrestamo(p)}
                  title="Eliminar el préstamo y revertir sus movimientos de caja"
                  style={{ ...btnBordered('danger'), flex: '1 1 100%', padding: '0.45rem 0.8rem', fontSize: '0.75rem', textAlign: 'center' }}
                >
                  Eliminar
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {cancelados.length > 0 && (
        <details style={{ marginTop: '0.5rem' }}>
          <summary style={{ cursor: 'pointer', fontFamily: FM, fontSize: '0.75rem', color: 'rgba(100,116,139,0.55)', listStyle: 'none', display: 'flex', alignItems: 'center', gap: '0.5rem', userSelect: 'none' }}>
            <span>▶</span>
            Ver {cancelados.length} préstamo(s) cancelado(s)
          </summary>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" style={{ marginTop: '0.875rem' }}>
            {cancelados.map((p) => {
              const nombre = clienteMap.get(p.cliente_id) ?? '…'
              return (
                <div key={p.id} style={{ background: 'var(--ov-002)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.75rem 1rem', opacity: 0.55 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-1)' }}>{nombre}</span>
                    <span style={{ fontFamily: FM, fontSize: '0.62rem', fontWeight: 700, color: 'rgba(100,116,139,0.6)', background: 'var(--ov-004)', padding: '1px 7px' }}>{p.estado}</span>
                  </div>
                  <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>
                    {fmtMonto(p.credito, p.moneda)} · {esInteresFijo(p)
                      ? `interés fijo, ${p.cuotas_detalle.length} período${p.cuotas_detalle.length === 1 ? '' : 's'}`
                      : `${p.cuotas} cuotas`}
                  </p>
                </div>
              )
            })}
          </div>
        </details>
      )}

      {creandoPrestamo && (
        <ModalNuevoPrestamo
          onClose={() => setCreandoPrestamo(false)}
          onSuccess={handleNuevoPrestamo}
        />
      )}
      {cobrandoCuota && (
        <ModalCobrarCuota
          prestamo={cobrandoCuota}
          clienteNombre={clienteMap.get(cobrandoCuota.cliente_id) ?? '…'}
          onClose={() => setCobrandoCuota(null)}
          onSuccess={handleCobrarCuota}
        />
      )}
      {pagoLibre && (
        <ModalPagarDeuda
          deuda={pagoLibre}
          onClose={() => setPagoLibre(null)}
          onSuccess={handlePagoLibre}
        />
      )}
      {editandoPrestamo && (
        <ModalEditarPrestamo
          prestamo={editandoPrestamo}
          clienteNombre={clienteMap.get(editandoPrestamo.cliente_id) ?? '…'}
          onClose={() => setEditandoPrestamo(null)}
          onSuccess={handleEditarPrestamo}
        />
      )}
      {eliminandoPrestamo && (
        <ModalEliminar
          entidad="prestamo"
          id={eliminandoPrestamo.id}
          onClose={() => setEliminandoPrestamo(null)}
          onSuccess={handleEliminarPrestamo}
        />
      )}
      {cobroFijo && (
        <ModalInteresFijoCobro
          prestamo={cobroFijo.prestamo}
          clienteNombre={clienteMap.get(cobroFijo.prestamo.cliente_id) ?? '…'}
          modo={cobroFijo.modo}
          onClose={() => setCobroFijo(null)}
          onSuccess={handleOperacionInteresFijo}
        />
      )}
      {abonandoCapital && (
        <ModalAbonarCapital
          prestamo={abonandoCapital}
          clienteNombre={clienteMap.get(abonandoCapital.cliente_id) ?? '…'}
          onClose={() => setAbonandoCapital(null)}
          onSuccess={handleOperacionInteresFijo}
        />
      )}
      {editandoInteres && (
        <ModalEditarInteres
          prestamo={editandoInteres}
          clienteNombre={clienteMap.get(editandoInteres.cliente_id) ?? '…'}
          onClose={() => setEditandoInteres(null)}
          onSuccess={handleOperacionInteresFijo}
        />
      )}
    </div>
  )
}
