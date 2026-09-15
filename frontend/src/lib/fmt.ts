export function fmtARS(value: string | number): string {
  const n = typeof value === 'string' ? parseFloat(value) : value
  return n.toLocaleString('es-AR', { style: 'currency', currency: 'ARS', minimumFractionDigits: 2 })
}

export function fmtUSD(value: string | number): string {
  const n = typeof value === 'string' ? parseFloat(value) : value
  return `U$D ${n.toLocaleString('es-AR', { minimumFractionDigits: 2 })}`
}

export function fmtMonto(value: string | number, moneda: string): string {
  return moneda === 'USD' ? fmtUSD(value) : fmtARS(value)
}

export function fmtDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const [year, month, day] = dateStr.split('-')
  return `${day}/${month}/${year?.slice(2)}`
}

/**
 * Hora de una operación, en hora de Argentina y formato 24h (ej: "21:17").
 *
 * Recibe un timestamp ISO del backend (`momento`, `created_at`). La zona se fija
 * a mano en `America/Argentina/Buenos_Aires` en vez de dejar que el navegador
 * use la suya: una máquina con el reloj en otra zona mostraría la hora corrida
 * y el operador leería una hora que nunca pasó. Es el mismo cuidado que ya
 * tiene `todayISO()` con `toISOString()`.
 *
 * Si el string viene sin zona se asume UTC, que es como los guarda la base: sin
 * eso, el navegador lo leería como hora local y en Argentina adelantaría 3 horas.
 */
export function fmtHora(iso: string | null | undefined): string {
  if (!iso) return '—'
  const conZona = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`
  const d = new Date(conZona)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('es-AR', {
    hour:     '2-digit',
    minute:   '2-digit',
    hour12:   false,
    timeZone: 'America/Argentina/Buenos_Aires',
  })
}

/**
 * Día y hora de registro, en hora de Argentina (ej: "14/09/26 21:17").
 *
 * Para el tooltip de la hora: cuando una operación se carga atrasada, su día de
 * carga no es el día operativo bajo el que aparece, y verlo entero evita leer
 * la hora como si la operación hubiera pasado a esa hora de ese día.
 */
export function fmtFechaHora(iso: string | null | undefined): string {
  if (!iso) return '—'
  const conZona = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`
  const d = new Date(conZona)
  if (isNaN(d.getTime())) return '—'
  const dia = d.toLocaleDateString('es-AR', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    timeZone: 'America/Argentina/Buenos_Aires',
  })
  return `${dia} ${fmtHora(iso)}`
}

/**
 * Día local ART (YYYY-MM-DD) de un timestamp del backend.
 *
 * Los timestamps se guardan en UTC, así que recortarlos a mano con
 * `.slice(0, 10)` devuelve el día UTC: una operación de las 21:17 de Argentina
 * cae en el día siguiente y se traspapela un día entero de filtros. Es la misma
 * cuenta que el backend hace con `fecha_local()`.
 */
export function diaLocalISO(iso: string | null | undefined): string | null {
  if (!iso) return null
  const conZona = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`
  const d = new Date(conZona)
  if (isNaN(d.getTime())) return null
  // 'en-CA' es el locale que formatea la fecha como YYYY-MM-DD, que es lo que
  // comparan los filtros de rango.
  return d.toLocaleDateString('en-CA', { timeZone: 'America/Argentina/Buenos_Aires' })
}

/**
 * Fecha operativa con la hora de carga al lado (ej: "14/09/26 21:17").
 *
 * `dia` es la fecha con la que se cargó la operación —la que el operador eligió
 * y con la que cierra la caja— e `iso` el timestamp de cuándo se registró.
 *
 * La hora **solo se muestra si la operación se cargó ese mismo día**. Un gasto
 * de ayer cargado hoy a las 10:00 no pasó ayer a las 10:00: pegarle la hora a la
 * fecha operativa arma un momento que nunca existió. En ese caso va la fecha sola.
 */
export function fmtFechaConHora(
  dia: string | null | undefined,
  iso: string | null | undefined,
): string {
  if (!dia) return '—'
  const fecha = fmtDate(dia)
  const hora = horaDeCarga(dia, iso)
  return hora ? `${fecha} ${hora}` : fecha
}

/**
 * La hora de carga sola, o null si no corresponde mostrarla.
 *
 * Misma regla que `fmtFechaConHora`, para las pantallas que ya muestran el día
 * aparte —agrupadas por fecha— y solo necesitan la hora.
 */
export function horaDeCarga(
  dia: string | null | undefined,
  iso: string | null | undefined,
): string | null {
  if (!dia || !iso) return null
  return diaLocalISO(iso) === dia ? fmtHora(iso) : null
}

export function daysUntil(dateStr: string): number {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(dateStr + 'T00:00:00')
  return Math.round((target.getTime() - today.getTime()) / 86_400_000)
}

// Fecha local en formato ISO (YYYY-MM-DD). NO usar toISOString(): devuelve UTC
// y en Argentina (UTC−3) de noche adelanta un día, corriendo todos los filtros.
function localISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function todayISO(): string {
  return localISO(new Date())
}

export function weekStartISO(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() - d.getDay() + (d.getDay() === 0 ? -6 : 1))
  return localISO(d)
}

export function monthStartISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

export function yearStartISO(): string {
  return `${new Date().getFullYear()}-01-01`
}

/**
 * Cómo se muestra el número de un cheque, que puede faltar.
 *
 * Un e-cheq cargado desde un comprobante de emisión no trae número: el
 * comprobante simplemente no lo tiene. Se muestra "Sin número" en vez de un
 * hueco, para que se lea como un dato que falta y no como un error de la tabla.
 */
export function fmtNroCheque(nro: string | null): string {
  return nro || 'Sin número'
}
