import { NavLink, Outlet } from 'react-router-dom'

const FONT = "'Manrope', sans-serif"
const ACCENT = '#6366f1'

export default function Deudores() {
  return (
    <div>
      <div className="px-4 pt-5 sm:px-8" style={{ background: 'var(--surface-grad)', borderBottom: '1px solid var(--bd-006)' }}>
        <h1 style={{ fontFamily: "'Bebas Neue', sans-serif", fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.25rem' }}>
          Deudores
        </h1>
        <div style={{ display: 'flex', gap: 0, marginTop: '0.75rem' }}>
          {[
            { to: '/deudores', label: 'Préstamos', end: true },
            { to: '/deudores/cheques-fiados', label: 'Cheques fiados', end: false },
          ].map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              style={({ isActive }) => ({
                fontFamily: FONT,
                fontSize: '0.78rem',
                fontWeight: 600,
                letterSpacing: '0.03em',
                textDecoration: 'none',
                padding: '0.5rem 1rem',
                color: isActive ? 'var(--text-strong)' : 'var(--nav-inactive)',
                borderBottom: isActive ? `2px solid ${ACCENT}` : '2px solid transparent',
                transition: 'all 0.15s',
              })}
            >
              {label}
            </NavLink>
          ))}
        </div>
      </div>
      <Outlet />
    </div>
  )
}
