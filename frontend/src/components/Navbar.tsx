import { useState, useEffect } from 'react'
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

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div style={{ padding: compact ? 0 : "1.75rem 1.5rem 1.25rem", borderBottom: compact ? "none" : BORDER }}>
      <span style={{
        fontFamily: "'Bebas Neue', sans-serif",
        fontSize: compact ? "1.5rem" : "1.9rem",
        letterSpacing: "0.1em",
        color: "#f8fafc",
        lineHeight: 1,
        display: "block",
      }}>
        Daily FC
      </span>
      {!compact && (
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
      )}
    </div>
  )
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div style={{ padding: "0.75rem 0", flex: 1 }}>
      {NAV_LINKS.map(({ to, label, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          style={({ isActive }) => ({
            display: "flex",
            alignItems: "center",
            padding: "0.7rem 1.5rem",
            fontFamily: "'Manrope', sans-serif",
            fontSize: "0.82rem",
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
  )
}

function MenuIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="18" y1="6" x2="6" y2="18" />
    </svg>
  )
}

export default function Navbar() {
  const [open, setOpen] = useState(false)

  // Gestos táctiles: deslizar desde el borde izquierdo abre el drawer,
  // deslizar hacia la izquierda lo cierra. Solo en mobile.
  useEffect(() => {
    const EDGE = 28      // px desde el borde para iniciar el gesto de apertura
    const THRESHOLD = 55 // px de desplazamiento para disparar
    let startX = 0, startY = 0, tracking = false, swiping = false

    function onStart(e: TouchEvent) {
      if (window.innerWidth >= 768) return // md+: hay sidebar fijo
      const t = e.touches[0]
      startX = t.clientX
      startY = t.clientY
      tracking = open || startX <= EDGE
      swiping = false
    }
    function onMove(e: TouchEvent) {
      if (!tracking) return
      const t = e.touches[0]
      const dx = t.clientX - startX
      const dy = t.clientY - startY
      if (!swiping) {
        if (Math.abs(dy) > Math.abs(dx)) { tracking = false; return } // scroll vertical
        if (Math.abs(dx) < 10) return
        swiping = true
      }
      if (!open && dx > THRESHOLD) { setOpen(true); tracking = false }
      else if (open && dx < -THRESHOLD) { setOpen(false); tracking = false }
    }
    function onEnd() { tracking = false; swiping = false }

    window.addEventListener('touchstart', onStart, { passive: true })
    window.addEventListener('touchmove', onMove, { passive: true })
    window.addEventListener('touchend', onEnd)
    return () => {
      window.removeEventListener('touchstart', onStart)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onEnd)
    }
  }, [open])

  return (
    <>
      {/* ── Mobile: top bar with hamburger on the left ───────────────────── */}
      <nav className="md:hidden flex items-center" style={{
        background: BG,
        borderBottom: BORDER,
        height: "56px",
        paddingLeft: "0.75rem",
        paddingRight: "1rem",
        gap: "0.75rem",
        position: "sticky",
        top: 0,
        zIndex: 50,
      }}>
        <button
          onClick={() => setOpen(true)}
          aria-label="Abrir menú"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: "40px",
            height: "40px",
            background: "transparent",
            border: "none",
            color: "rgba(226,232,240,0.85)",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          <MenuIcon />
        </button>
        <span style={{
          fontFamily: "'Bebas Neue', sans-serif",
          fontSize: "1.5rem",
          letterSpacing: "0.1em",
          color: "#f8fafc",
        }}>
          Daily FC
        </span>
      </nav>

      {/* ── Mobile: backdrop ─────────────────────────────────────────────── */}
      <div
        className="md:hidden"
        onClick={() => setOpen(false)}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.6)",
          zIndex: 60,
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
          transition: "opacity 0.2s ease",
        }}
      />

      {/* ── Mobile: left drawer ──────────────────────────────────────────── */}
      <nav
        className="md:hidden flex flex-col"
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          height: "100dvh",
          width: "240px",
          maxWidth: "80vw",
          background: BG,
          borderRight: BORDER,
          zIndex: 70,
          transform: open ? "translateX(0)" : "translateX(-100%)",
          transition: "transform 0.25s ease",
          boxShadow: open ? "8px 0 32px rgba(0,0,0,0.5)" : "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "1rem 1rem 1rem 1.5rem", borderBottom: BORDER }}>
          <Brand compact />
          <button
            onClick={() => setOpen(false)}
            aria-label="Cerrar menú"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "36px",
              height: "36px",
              background: "transparent",
              border: "none",
              color: "rgba(148,163,184,0.7)",
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <CloseIcon />
          </button>
        </div>
        <NavItems onNavigate={() => setOpen(false)} />
      </nav>

      {/* ── Desktop: left sidebar ────────────────────────────────────────── */}
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
        <Brand />
        <NavItems />
      </nav>
    </>
  )
}
