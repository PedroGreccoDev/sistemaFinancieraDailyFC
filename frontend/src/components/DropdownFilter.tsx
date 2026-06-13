import { useState, useRef, useEffect } from 'react'

const FONT = "'Manrope', sans-serif"

export default function DropdownFilter<T extends string>({
  label, value, options, onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const current = options.find((o) => o.value === value)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }} ref={ref}>
      <label style={{ fontFamily: FONT, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase' as const, color: 'rgba(100,116,139,0.7)' }}>
        {label}
      </label>
      <div style={{ position: 'relative' }}>
        <button
          onClick={() => setOpen((v) => !v)}
          style={{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: FONT, fontSize: '0.78rem', fontWeight: 600, background: 'var(--surface-grad)', border: '1px solid var(--bd-008)', color: 'var(--text-1)', padding: '0.45rem 0.85rem', minWidth: '150px', justifyContent: 'space-between', cursor: 'pointer', borderRadius: 'var(--r-md)' }}
        >
          <span>{current?.label}</span>
          <svg style={{ width: '12px', height: '12px', color: 'rgba(148,163,184,0.5)', transition: 'transform 0.15s', transform: open ? 'rotate(180deg)' : 'none', flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        {open && (
          <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 30, minWidth: '100%', background: 'var(--modal)', border: '1px solid var(--bd-010)', boxShadow: 'var(--shadow-card-hover)', overflow: 'hidden', borderRadius: 'var(--r-md)' }}>
            {options.map((opt) => (
              <button
                key={opt.value}
                onClick={() => { onChange(opt.value); setOpen(false) }}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '0.5rem 0.85rem', fontFamily: FONT, fontSize: '0.78rem', fontWeight: opt.value === value ? 700 : 500, color: opt.value === value ? 'var(--text-strong)' : 'var(--text-2)', background: opt.value === value ? 'color-mix(in srgb, var(--primary) 14%, transparent)' : 'transparent', borderLeft: opt.value === value ? '2px solid var(--primary)' : '2px solid transparent', cursor: 'pointer', borderRadius: 0 }}
                onMouseEnter={(e) => { if (opt.value !== value) (e.currentTarget as HTMLButtonElement).style.background = 'var(--ov-004)' }}
                onMouseLeave={(e) => { if (opt.value !== value) (e.currentTarget as HTMLButtonElement).style.background = opt.value === value ? 'color-mix(in srgb, var(--primary) 14%, transparent)' : 'transparent' }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
