import type { CSSProperties } from 'react'

/* Placeholder con shimmer (clase .skeleton definida en index.css). */
export function Skeleton({
  w = '100%', h = 14, r, style,
}: { w?: number | string; h?: number | string; r?: number | string; style?: CSSProperties }) {
  return <div className="skeleton" style={{ width: w, height: h, borderRadius: r ?? 'var(--r-sm)', ...style }} />
}

const CARD = {
  background: 'var(--surface-grad)',
  border: '1px solid var(--bd-006)',
  boxShadow: 'var(--shadow-card)',
  borderRadius: 'var(--r-lg)',
  padding: '1rem 1.2rem',
}

/** Grilla de tarjetas KPI en carga. */
export function SkeletonKpis({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" style={{ marginBottom: '1.75rem' }}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} style={{ ...CARD, borderLeft: '2px solid var(--bd-010)' }}>
          <Skeleton w="55%" h={10} />
          <Skeleton w="70%" h={34} style={{ marginTop: '0.7rem' }} />
          <Skeleton w="45%" h={9} style={{ marginTop: '0.7rem' }} />
        </div>
      ))}
    </div>
  )
}

/** Filas de lista/tabla en carga. Se renderiza dentro de la card existente. */
export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem',
          padding: '0.9rem 1.1rem',
          borderBottom: i === rows - 1 ? 'none' : '1px solid var(--ov-004)',
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Skeleton w={`${45 + ((i * 17) % 35)}%`} h={13} />
            <Skeleton w={`${25 + ((i * 11) % 25)}%`} h={9} style={{ marginTop: '0.5rem' }} />
          </div>
          <Skeleton w={80} h={16} />
        </div>
      ))}
    </div>
  )
}
