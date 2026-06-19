import React, { useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import type { ComponentType } from 'react'
import { IconHome, IconWallet, IconUsers, IconReceipt, IconChart, IconExchange, IconSettings, IconLogout } from './icons'
import { DolarPill, DolarBlock } from './DolarInline'
import { useDarkMode } from '../hooks/useDarkMode'
import { useCurrentUser } from '../lib/auth'
import { useAuth } from '../auth/AuthContext'

function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

type NavItem = { to: string; label: string; end: boolean; Icon: ComponentType<{ size?: number }>; adminOnly?: boolean; badge?: string }

const NAV_LINKS: NavItem[] = [
  { to: '/',               label: 'Inicio',        end: true,  Icon: IconHome },
  { to: '/cartera',        label: 'Cartera',        end: false, Icon: IconWallet },
  { to: '/deudores',       label: 'Deudores',       end: false, Icon: IconUsers },
  { to: '/pasivos',        label: 'Deudas',         end: false, Icon: IconReceipt },
  { to: '/reportes',       label: 'Reportes',       end: false, Icon: IconChart },
  { to: '/movimientos',    label: 'Movimientos',    end: false, Icon: IconExchange },
]

const ACCENT = "#6366f1"
const BG     = "var(--nav-bg)"
const BORDER = "1px solid var(--bd-006)"

function Brand({ compact = false, action }: { compact?: boolean; action?: React.ReactNode }) {
  return (
    <div style={{
      padding: compact ? 0 : "1.75rem 1.5rem 1.25rem",
      borderBottom: compact ? "none" : BORDER,
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
    }}>
      <div>
        <span style={{
          fontFamily: "'Bebas Neue', sans-serif",
          fontSize: compact ? "1.5rem" : "1.9rem",
          letterSpacing: "0.1em",
          color: "var(--text-strong)",
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
      {action}
    </div>
  )
}

function NavItems({ onNavigate, isAdmin }: { onNavigate?: () => void; isAdmin: boolean }) {
  return (
    <div style={{ padding: "0.75rem 0", flex: 1 }}>
      {NAV_LINKS.filter((l) => !l.adminOnly || isAdmin).map(({ to, label, end, Icon, badge }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          style={({ isActive }) => ({
            display: "flex",
            alignItems: "center",
            gap: "0.7rem",
            padding: "0.7rem 1.5rem",
            fontFamily: "'Manrope', sans-serif",
            fontSize: "0.82rem",
            fontWeight: isActive ? 700 : 500,
            letterSpacing: "0.04em",
            textDecoration: "none",
            color: isActive ? "var(--text-strong)" : "var(--nav-inactive)",
            borderLeft: isActive ? `2px solid ${ACCENT}` : "2px solid transparent",
            background: isActive ? "rgba(99,102,241,0.08)" : "transparent",
            transition: "all 0.15s",
          })}
          onMouseEnter={(e) => {
            const el = e.currentTarget as HTMLAnchorElement
            if (!el.style.borderLeftColor.includes("rgb(99")) {
              el.style.color = "var(--text-1)"
              el.style.background = "var(--ov-003)"
            }
          }}
          onMouseLeave={(e) => {
            const el = e.currentTarget as HTMLAnchorElement
            if (!el.style.borderLeftColor.includes("rgb(99")) {
              el.style.color = "var(--nav-inactive)"
              el.style.background = "transparent"
            }
          }}
        >
          <Icon size={17} />
          <span>{label}</span>
          {badge && (
            <span style={{
              fontSize: "0.5rem", fontWeight: 700, letterSpacing: "0.06em",
              color: "#818cf8", background: "rgba(99,102,241,0.2)",
              borderRadius: "4px", padding: "1px 4px",
            }}>{badge}</span>
          )}
        </NavLink>
      ))}
    </div>
  )
}

// Pie con el usuario actual, su rol y el botón de cerrar sesión. El logout borra
// el token de la sesión (localStorage) y vuelve al login.
function UserBlock({ position = 'bottom' }: { position?: 'top' | 'bottom' }) {
  const { logout } = useAuth()
  const me = useCurrentUser()
  // Arriba (debajo del logo): separador inferior y padding reducido para que quede
  // pegado al logo y a las secciones. Abajo (pie): separador superior clásico.
  const sep = position === 'top'
    ? { borderBottom: BORDER, padding: "0.625rem 1.5rem" }
    : { borderTop: BORDER, padding: "0.875rem 1.5rem" }
  return (
    <div style={{ ...sep, display: "flex", alignItems: "center", gap: "0.6rem" }}>
      <span style={{
        width: 34, height: 34, borderRadius: "50%", flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'Manrope', sans-serif", fontWeight: 700, fontSize: "0.72rem",
        background: "rgba(99,102,241,0.18)", border: "1px solid rgba(99,102,241,0.35)", color: "#818cf8",
      }}>{me.initials}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ fontFamily: "'Manrope', sans-serif", fontSize: "0.78rem", fontWeight: 700, color: "var(--text-strong)", margin: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{me.username}</p>
        <p style={{ fontFamily: "'Manrope', sans-serif", fontSize: "0.62rem", color: "var(--text-2)", margin: 0 }}>{me.rol === 'admin' ? 'Administrador' : 'Usuario'}</p>
      </div>
      <button
        onClick={logout}
        aria-label="Cerrar sesión"
        title="Cerrar sesión"
        style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: "0.4rem", flexShrink: 0,
          fontFamily: "'Manrope', sans-serif", fontSize: "0.74rem", fontWeight: 600, cursor: "pointer",
          color: "var(--danger)", background: "transparent",
          border: "1px solid color-mix(in srgb, var(--danger) 30%, transparent)",
          borderRadius: "var(--r-sm)", padding: "0.45rem 0.6rem",
        }}
      >
        <IconLogout size={14} />
      </button>
    </div>
  )
}

// Ruedita de Configuración (solo admin) que vive en la fila inferior, donde antes
// estaba el texto "Modo claro/oscuro". El toggle de tema queda a su derecha.
function ConfigGear({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <NavLink
      to="/configuracion"
      onClick={onNavigate}
      aria-label="Configuración"
      title="Configuración"
      style={({ isActive }) => ({
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '32px',
        height: '32px',
        background: isActive ? 'rgba(99,102,241,0.12)' : 'var(--ov-004)',
        border: isActive ? `1px solid ${ACCENT}` : '1px solid var(--bd-006)',
        borderRadius: '8px',
        color: isActive ? '#818cf8' : 'var(--text-2)',
        cursor: 'pointer',
      })}
    >
      <IconSettings size={16} />
    </NavLink>
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
  const [dark, toggleDark] = useDarkMode()
  const me = useCurrentUser()
  const isAdmin = me.rol === 'admin'

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
      // Confirmado swipe horizontal de drawer: cancelamos el gesto nativo de
      // "atrás" del navegador (solo posible con el listener no-pasivo).
      if (e.cancelable) e.preventDefault()
      if (!open && dx > THRESHOLD) { setOpen(true); tracking = false }
      else if (open && dx < -THRESHOLD) { setOpen(false); tracking = false }
    }
    function onEnd() { tracking = false; swiping = false }

    window.addEventListener('touchstart', onStart, { passive: true })
    window.addEventListener('touchmove', onMove, { passive: false })
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
            color: "var(--text-1)",
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
          color: "var(--text-strong)",
        }}>
          Daily FC
        </span>
        <div style={{ flex: 1 }} />
        <DolarPill />
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
        <UserBlock position="top" />
        <NavItems onNavigate={() => setOpen(false)} isAdmin={isAdmin} />
        <div style={{
          padding: '0.875rem 1.5rem',
          borderTop: BORDER,
          display: 'flex',
          alignItems: 'center',
          gap: '0.6rem',
        }}>
          {isAdmin && <ConfigGear onNavigate={() => setOpen(false)} />}
          <button
            onClick={toggleDark}
            aria-label={dark ? 'Activar modo claro' : 'Activar modo oscuro'}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '32px',
              height: '32px',
              marginLeft: 'auto',
              background: 'var(--ov-004)',
              border: '1px solid var(--bd-006)',
              borderRadius: '8px',
              color: 'var(--text-2)',
              cursor: 'pointer',
            }}
          >
            {dark ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </nav>

      {/* ── Desktop: left sidebar ────────────────────────────────────────── */}
      <nav className="hidden md:flex flex-col" style={{
        background: BG,
        borderRight: BORDER,
        width: "200px",
        height: "100dvh",
        flexShrink: 0,
        position: "sticky",
        top: 0,
        alignSelf: "flex-start",
      }}>
        <Brand />
        <UserBlock position="top" />
        <NavItems isAdmin={isAdmin} />
        <DolarBlock />
        <div style={{
          marginTop: 'auto',
          padding: '0.875rem 1.5rem',
          borderTop: BORDER,
          display: 'flex',
          alignItems: 'center',
          gap: '0.6rem',
        }}>
          {isAdmin && <ConfigGear />}
          <button
            onClick={toggleDark}
            aria-label={dark ? 'Activar modo claro' : 'Activar modo oscuro'}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '32px',
              height: '32px',
              marginLeft: 'auto',
              background: 'var(--ov-004)',
              border: '1px solid var(--bd-006)',
              borderRadius: '8px',
              color: 'var(--text-2)',
              cursor: 'pointer',
            }}
          >
            {dark ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </nav>
    </>
  )
}
