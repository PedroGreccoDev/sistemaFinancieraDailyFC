// Sello de la agencia que desarrolla el sistema ("Desarrollado por grevex").
// Va en las pantallas de autenticación y debajo de "Daily FC" en el menú. El logotipo
// se arma con la tipografía Unbounded (cargada en index.html) en el índigo de
// la marca; si algún día hay un SVG oficial, se reemplaza solo acá.

export default function GrevexSeal({ size = 'md', onDark = false, align = 'center', label = 'Desarrollado por' }: {
  size?: 'sm' | 'md'
  onDark?: boolean
  align?: 'center' | 'start'
  label?: string
}) {
  const sm = size === 'sm'
  return (
    <div
      aria-label={`${label} grevex`}
      style={{
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: align === 'start' ? 'flex-start' : 'center',
        gap: sm ? '0.4rem' : '0.5rem',
        fontFamily: "'Manrope', sans-serif",
      }}
    >
      <span style={{
        fontSize: sm ? '0.55rem' : '0.6rem',
        fontWeight: 600,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: onDark ? 'rgba(224,231,255,0.7)' : 'var(--text-2)',
      }}>
        {label}
      </span>
      <span style={{
        fontFamily: "'Unbounded', 'Manrope', sans-serif",
        fontWeight: 700,
        fontSize: sm ? '0.8rem' : '0.95rem',
        letterSpacing: '-0.01em',
        color: onDark ? '#fff' : 'var(--grevex)',
        lineHeight: 1,
      }}>
        grevex
      </span>
    </div>
  )
}
