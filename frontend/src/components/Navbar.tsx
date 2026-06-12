import { NavLink } from 'react-router-dom'

const NAV_LINKS = [
  { to: '/',            label: 'Inicio',      end: true  },
  { to: '/cartera',     label: 'Cartera',     end: false },
  { to: '/deudores',    label: 'Deudores',    end: false },
  { to: '/pasivos',     label: 'Deudas',      end: false },
  { to: '/reportes',    label: 'Reportes',    end: false },
  { to: '/movimientos', label: 'Movimientos', end: false },
]

const ACCENT = "#6366f1"
const BG     = "#0a0a0e"
const BORDER = "1px solid rgba(255,255,255,0.06)"

export default function Navbar() {
  return (
    <>
      {/* ── Mobile: top bar ─────────────────────────────── */}
      <nav className="md:hidden flex items-stretch" style={{
        background: BG,
        borderBottom: BORDER,
        height: "56px",
        paddingLeft: "1rem",
        paddingRight: "1rem",
        gap: "0.75rem",
        position: "sticky",
        top: 0,
        zIndex: 50,
      }}>
        <div style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
          <span style={{
            fontFamily: "'Bebas Neue', sans-serif",
            fontSize: "1.5rem",
            letterSpacing: "0.1em",
            color: "#f8fafc",
          }}>
            Daily FC
          </span>
        </div>
        <div style={{ width: "1px", margin: "12px 0", background: "rgba(255,255,255,0.1)" }} />
        <div style={{ display: "flex", alignItems: "stretch", overflowX: "auto", gap: 0, flex: 1 }}>
          {NAV_LINKS.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              style={({ isActive }) => ({
                display: "flex",
                alignItems: "center",
                padding: "0 0.75rem",
                fontFamily: "'Manrope', sans-serif",
                fontSize: "0.68rem",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                textDecoration: "none",
                whiteSpace: "nowrap",
                color: isActive ? "#f8fafc" : "rgba(148,163,184,0.6)",
                borderBottom: isActive ? `2px solid ${ACCENT}` : "2px solid transparent",
              })}
            >
              {label}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* ── Desktop: left sidebar ────────────────────────── */}
      <nav className="hidden md:flex flex-col" style={{
        background: BG,
        borderRight: BORDER,
        width: "200px",
        minHeight: "100dvh",
        flexShrink: 0,
        position: "sticky",
        top: 0,
        alignSelf: "flex-start",
      }}>
        {/* Brand */}
        <div style={{
          padding: "1.75rem 1.5rem 1.25rem",
          borderBottom: BORDER,
        }}>
          <span style={{
            fontFamily: "'Bebas Neue', sans-serif",
            fontSize: "1.9rem",
            letterSpacing: "0.1em",
            color: "#f8fafc",
            lineHeight: 1,
            display: "block",
          }}>
            Daily FC
          </span>
          <span style={{
            fontFamily: "'Manrope', sans-serif",
            fontSize: "0.6rem",
            fontWeight: 600,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            color: "rgba(100,116,139,0.7)",
            marginTop: "4px",
            display: "block",
          }}>
            Sistema Financiero
          </span>
        </div>

        {/* Links */}
        <div style={{ padding: "0.75rem 0", flex: 1 }}>
          {NAV_LINKS.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              style={({ isActive }) => ({
                display: "flex",
                alignItems: "center",
                padding: "0.65rem 1.5rem",
                fontFamily: "'Manrope', sans-serif",
                fontSize: "0.78rem",
                fontWeight: isActive ? 700 : 500,
                letterSpacing: "0.04em",
                textDecoration: "none",
                color: isActive ? "#f8fafc" : "rgba(148,163,184,0.6)",
                borderLeft: isActive ? `2px solid ${ACCENT}` : "2px solid transparent",
                background: isActive ? "rgba(99,102,241,0.08)" : "transparent",
                transition: "all 0.15s",
              })}
              onMouseEnter={(e) => {
                const el = e.currentTarget as HTMLAnchorElement
                if (!el.style.borderLeftColor.includes("rgb(99")) {
                  el.style.color = "rgba(226,232,240,0.85)"
                  el.style.background = "rgba(255,255,255,0.03)"
                }
              }}
              onMouseLeave={(e) => {
                const el = e.currentTarget as HTMLAnchorElement
                if (!el.style.borderLeftColor.includes("rgb(99")) {
                  el.style.color = "rgba(148,163,184,0.6)"
                  el.style.background = "transparent"
                }
              }}
            >
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </>
  )
}
