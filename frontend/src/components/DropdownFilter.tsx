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
          style={{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: FONT, fontSize: '0.78rem', fontWeight: 600, background: 'linear-gradient(145deg, #0c0c10, #13131a)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0', padding: '0.45rem 0.85rem', minWidth: '150px', justifyContent: 'space-between', cursor: 'pointer' }}
        >
          <span>{current?.label}</span>
          <svg style={{ width: '12px', height: '12px', color: 'rgba(148,163,184,0.5)', transition: 'transform 0.15s', transform: open ? 'rotate(180deg)' : 'none', flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        {open && (
          <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 30, minWidth: '100%', background: '#0f0f16', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 8px 32px rgba(0,0,0,0.6)', overflow: 'hidden' }}>
            {options.map((opt) => (
              <button
                key={opt.value}
                onClick={() => { onChange(opt.value); setOpen(false) }}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '0.5rem 0.85rem', fontFamily: FONT, fontSize: '0.78rem', fontWeight: opt.value === value ? 700 : 500, color: opt.value === value ? '#f8fafc' : 'rgba(148,163,184,0.75)', background: opt.value === value ? 'rgba(99,102,241,0.12)' : 'transparent', borderLeft: opt.value === value ? '2px solid #6366f1' : '2px solid transparent', cursor: 'pointer' }}
                onMouseEnter={(e) => { if (opt.value !== value) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.04)' }}
                onMouseLeave={(e) => { if (opt.value !== value) (e.currentTarget as HTMLButtonElement).style.background = opt.value === value ? 'rgba(99,102,241,0.12)' : 'transparent' }}
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
