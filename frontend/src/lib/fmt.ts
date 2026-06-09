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

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

export function weekStartISO(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() - d.getDay() + (d.getDay() === 0 ? -6 : 1))
  return d.toISOString().slice(0, 10)
}

export function monthStartISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

export function yearStartISO(): string {
  return `${new Date().getFullYear()}-01-01`
}
