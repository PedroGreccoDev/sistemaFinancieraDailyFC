import { useRef, useEffect } from 'react'
import { DayPicker } from 'react-day-picker'
import type { DateRange } from 'react-day-picker'
import { es } from 'react-day-picker/locale'
import 'react-day-picker/style.css'

interface Props {
  from: string | null
  to: string | null
  onChange: (from: string | null, to: string | null) => void
  onClose: () => void
}

function isoToDate(iso: string | null): Date | undefined {
  if (!iso) return undefined
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function dateToISO(d: Date | undefined): string | null {
  if (!d) return null
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('-')
}

export default function DateRangePicker({ from, to, onChange, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const range: DateRange = { from: isoToDate(from), to: isoToDate(to) }

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [onClose])

  return (
    <div
      ref={ref}
      className="absolute top-full right-0 mt-2 z-50 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5 text-slate-800 dark:text-slate-200"
      style={{
        '--rdp-accent-color': '#3b82f6',
        '--rdp-accent-background-color': 'rgba(59,130,246,0.15)',
        '--rdp-range_middle-background-color': 'rgba(59,130,246,0.12)',
        '--rdp-range_middle-color': '#3b82f6',
        '--rdp-range_start-color': '#ffffff',
        '--rdp-range_end-color': '#ffffff',
        '--rdp-today-color': '#3b82f6',
        '--rdp-day-height': '30px',
        '--rdp-day-width': '30px',
        '--rdp-day_button-height': '28px',
        '--rdp-day_button-width': '28px',
        '--rdp-nav-height': '2rem',
      } as React.CSSProperties}
    >
      <DayPicker
        mode="range"
        selected={range}
        onSelect={(r: DateRange | undefined) =>
          onChange(dateToISO(r?.from), dateToISO(r?.to))
        }
        locale={es}
        showOutsideDays
      />
      <div className="flex justify-end gap-2 mt-3 pt-3 border-t border-slate-100 dark:border-slate-700">
        <button
          onClick={() => { onChange(null, null); onClose() }}
          className="px-3 py-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 transition-colors"
        >
          Limpiar
        </button>
        <button
          onClick={onClose}
          className="px-4 py-1.5 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Aplicar
        </button>
      </div>
    </div>
  )
}
