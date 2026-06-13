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
