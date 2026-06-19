// Administración de usuarios (/usuarios, solo admin). Solo UI: todos los datos
// son mock en estado local y las acciones (invitar, revocar, activar, etc.)
// solo muestran feedback, no impactan en ningún backend.
// TODO: cablear backend (CRUD de usuarios, invitaciones, reset de contraseña).

import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useToast } from '../lib/toast'
import { useCurrentUser } from '../lib/auth'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const ACCENT = '#6366f1'

const CARD: CSSProperties = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const CAP: CSSProperties = { fontSize: '0.62rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--text-2)' }

type Rol = 'Usuario' | 'Admin'
interface Invitacion { id: number; telefono: string; rol: Rol; dias: number }
interface Usuario { id: number; username: string; initials: string; rol: Rol; activo: boolean; telefono: string; esVos?: boolean }

// ── Datos mock iniciales ──────────────────────────────────────────────────────
const PENDIENTES_INI: Invitacion[] = [
  { id: 1, telefono: '+54 9 11 4821', rol: 'Usuario', dias: 6 },
  { id: 2, telefono: '+54 9 351 7733', rol: 'Admin', dias: 2 },
]

// ── Subcomponentes ────────────────────────────────────────────────────────────
function Avatar({ initials, tone = 'muted', size = 34 }: { initials: string; tone?: 'accent' | 'muted'; size?: number }) {
  const accent = tone === 'accent'
  return (
    <span style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontWeight: 700, fontSize: `${size * 0.023}rem`,
      background: accent ? 'rgba(99,102,241,0.2)' : 'var(--ov-005)',
      color: accent ? '#818cf8' : 'var(--text-2)',
    }}>{initials}</span>
  )
}

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onClick}
      style={{
        width: 42, height: 24, borderRadius: 999, position: 'relative', flexShrink: 0, cursor: 'pointer', padding: 0,
        background: on ? ACCENT : 'var(--input-bg)', border: on ? 'none' : '1px solid var(--bd-008)', transition: 'background 0.15s',
      }}
    >
      <span style={{
        position: 'absolute', top: 2, left: on ? 20 : 2, width: 18, height: 18, borderRadius: '50%',
        background: on ? '#fff' : 'var(--text-2)', transition: 'left 0.15s',
      }} />
    </button>
  )
}

function Ghost({ children, onClick, danger, style }: { children: ReactNode; onClick?: () => void; danger?: boolean; style?: CSSProperties }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        fontFamily: FM, fontSize: '0.7rem', fontWeight: 600, cursor: 'pointer',
        color: danger ? 'var(--danger)' : 'var(--text-1)', background: 'transparent',
        border: `1px solid ${danger ? 'color-mix(in srgb, var(--danger) 30%, transparent)' : 'var(--bd-008)'}`,
        borderRadius: 'var(--r-sm)', padding: '0.4rem 0.6rem', ...style,
      }}
    >{children}</button>
  )
}

function Solid({ children, onClick, color = ACCENT }: { children: ReactNode; onClick?: () => void; color?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{ fontFamily: FM, fontSize: '0.7rem', fontWeight: 700, cursor: 'pointer', color: '#fff', background: color, border: 'none', borderRadius: 'var(--r-sm)', padding: '0.4rem 0.65rem' }}
    >{children}</button>
  )
}

// ── Página ────────────────────────────────────────────────────────────────────
export default function Usuarios() {
  const toast = useToast()
  const me = useCurrentUser()

  const [telefono, setTelefono] = useState('')
  const [esAdmin, setEsAdmin] = useState(false)
  const [link, setLink] = useState<string | null>(null)
  const [pendientes, setPendientes] = useState<Invitacion[]>(PENDIENTES_INI)
  const [usuarios, setUsuarios] = useState<Usuario[]>([
    { id: 0, username: me.username, initials: me.initials, rol: 'Admin', activo: true, telefono: '', esVos: true },
    { id: 1, username: 'j.perez', initials: 'JP', rol: 'Usuario', activo: true, telefono: '+54 9 11 4821' },
    { id: 2, username: 'l.rodriguez', initials: 'LR', rol: 'Usuario', activo: false, telefono: '+54 9 351 7733' },
  ])

  function enviarInvitacion() {
    if (!telefono.trim()) return
    const token = Math.random().toString(36).slice(2, 6)
    setLink(`dailyfc.app/registro?token=${token}…`)
    setPendientes((p) => [
      { id: Date.now(), telefono: `+54 ${telefono.trim()}`, rol: esAdmin ? 'Admin' : 'Usuario', dias: 7 },
      ...p,
    ])
    setTelefono('')
    setEsAdmin(false)
    toast('success', 'Invitación enviada por WhatsApp')
  }

  async function copiar(texto: string) {
    try {
      await navigator.clipboard.writeText(texto)
      toast('success', 'Enlace copiado')
    } catch {
      toast('error', 'No se pudo copiar el enlace')
    }
  }

  function revocar(id: number) {
    setPendientes((p) => p.filter((x) => x.id !== id))
    toast('info', 'Invitación revocada')
  }

  function toggleActivo(u: Usuario) {
    setUsuarios((list) => list.map((x) => (x.id === u.id ? { ...x, activo: !x.activo } : x)))
    toast('success', u.activo ? `Usuario ${u.username} desactivado` : `Usuario ${u.username} activado`)
  }

  // ── Bloques reutilizables ───────────────────────────────────────────────────
  const cardInvitar = (
    <div style={{ ...CARD, padding: '1.1rem 1.2rem' }}>
      <p style={{ ...CAP, margin: '0 0 0.9rem' }}>Invitar persona</p>

      {link ? (
        <div style={{
          background: 'color-mix(in srgb, var(--success) 8%, transparent)',
          border: '1px solid color-mix(in srgb, var(--success) 28%, transparent)',
          borderRadius: 'var(--r-md)', padding: '0.85rem',
        }}>
          <p style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--success)', margin: '0 0 0.7rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><polyline points="20 6 9 17 4 12" /></svg>
            Enlace de invitación generado
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <span style={{ flex: 1, minWidth: 0, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.7rem', color: 'var(--text-2)', background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.55rem 0.7rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{link}</span>
            <button type="button" onClick={() => copiar(link)} style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '0.35rem', background: ACCENT, color: '#fff', border: 'none', borderRadius: 'var(--r-sm)', padding: '0.55rem 0.7rem', fontFamily: FM, fontSize: '0.72rem', fontWeight: 700, cursor: 'pointer' }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
              Copiar
            </button>
          </div>
          <button type="button" onClick={() => setLink(null)} style={{ marginTop: '0.85rem', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', fontFamily: FM, fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-2)' }}>
            Invitar a otra persona
          </button>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginBottom: '0.85rem' }}>
            <label style={{ fontSize: '0.58rem', fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-2)' }}>Teléfono</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <span style={{ display: 'flex', alignItems: 'center', background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0 0.7rem', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-2)' }}>+54</span>
              <input
                className="fld-auth"
                type="tel"
                inputMode="tel"
                value={telefono}
                onChange={(e) => setTelefono(e.target.value)}
                placeholder="9 11 5555 5555"
                style={{ flex: 1, minWidth: 0, background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.7rem 0.8rem', fontFamily: FM, fontSize: '0.85rem', color: 'var(--text-strong)', outline: 'none' }}
              />
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.55rem 0 0.95rem' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--text-1)' }}>¿Es administrador?</span>
            <Toggle on={esAdmin} onClick={() => setEsAdmin((v) => !v)} />
          </div>
          <button type="button" onClick={enviarInvitacion} disabled={!telefono.trim()} style={{ width: '100%', background: ACCENT, color: '#fff', border: 'none', borderRadius: 'var(--r-md)', padding: '0.8rem', fontFamily: FM, fontSize: '0.85rem', fontWeight: 700, cursor: telefono.trim() ? 'pointer' : 'default', opacity: telefono.trim() ? 1 : 0.6 }}>
            Enviar invitación
          </button>
        </>
      )}
    </div>
  )

  const cardPendientes = (
    <div style={{ ...CARD, padding: '1.1rem 1.2rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.9rem' }}>
        <p style={{ ...CAP, margin: 0 }}>Invitaciones pendientes</p>
        <span style={{ fontSize: '0.6rem', fontWeight: 700, color: '#818cf8', background: 'rgba(99,102,241,0.14)', borderRadius: 999, padding: '1px 8px' }}>{pendientes.length}</span>
      </div>
      {pendientes.length === 0 ? (
        <p style={{ fontSize: '0.78rem', color: 'var(--text-2)', margin: 0 }}>No hay invitaciones pendientes.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          {pendientes.map((inv) => (
            <div key={inv.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.6rem', background: 'var(--input-bg)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.7rem 0.85rem' }}>
              <div style={{ minWidth: 0 }}>
                <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem', color: 'var(--text-strong)', margin: '0 0 2px' }}>{inv.telefono}</p>
                <p style={{ fontSize: '0.66rem', color: 'var(--text-2)', margin: 0 }}>
                  Vence en {inv.dias} días · {inv.rol === 'Admin' ? <span style={{ color: '#818cf8', fontWeight: 600 }}>Admin</span> : 'Usuario'}
                </p>
              </div>
              <Ghost danger onClick={() => revocar(inv.id)}>Revocar</Ghost>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  const cardUsuarios = (
    <div style={{ ...CARD, padding: '1.1rem 1.2rem' }}>
      <p style={{ ...CAP, margin: '0 0 0.9rem' }}>Usuarios existentes</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
        {usuarios.map((u) => (
          <div key={u.id} style={{
            background: 'var(--input-bg)', borderRadius: 'var(--r-md)', padding: '0.85rem',
            border: `1px solid ${u.esVos ? 'rgba(99,102,241,0.25)' : 'var(--bd-006)'}`,
            opacity: u.activo ? 1 : 0.72,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.7rem' }}>
              <Avatar initials={u.initials} tone={u.esVos ? 'accent' : 'muted'} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <p style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--text-strong)', margin: 0 }}>
                  {u.username}
                  {u.esVos && <span style={{ fontSize: '0.62rem', fontWeight: 600, color: '#818cf8', background: 'rgba(99,102,241,0.16)', borderRadius: 999, padding: '1px 7px', marginLeft: 5 }}>Vos</span>}
                </p>
                <p style={{ fontSize: '0.68rem', color: 'var(--text-2)', margin: 0 }}>
                  {u.rol} · {u.activo ? 'Activo' : 'Inactivo'}{u.telefono ? ` · ${u.telefono}` : ''}
                </p>
              </div>
              {!u.esVos && (
                <span style={{ width: 9, height: 9, borderRadius: '50%', flexShrink: 0, background: u.activo ? 'var(--success)' : 'var(--bd-012)' }} />
              )}
            </div>

            {u.esVos ? (
              <p style={{ fontSize: '0.68rem', color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: '0.35rem', margin: 0 }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg>
                No podés desactivarte ni quitarte el rol a vos mismo.
              </p>
            ) : (
              <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
                <Ghost onClick={() => toast('info', `Se reenvió un código de reseteo a ${u.username}`)}>Resetear clave</Ghost>
                {u.activo
                  ? <Ghost danger onClick={() => toggleActivo(u)}>Desactivar</Ghost>
                  : <Solid color="var(--success)" onClick={() => toggleActivo(u)}>Activar</Solid>}
                <Ghost onClick={() => toast('info', 'Edición de teléfono — pendiente de backend')} style={{ color: 'var(--text-2)' }}>Editar tel.</Ghost>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>
      <p style={{ fontFamily: FN, fontSize: '1.9rem', letterSpacing: '0.05em', color: 'var(--text-strong)', margin: '0 0 1.2rem', lineHeight: 1 }}>Usuarios</p>

      {/* Móvil: apilado · Escritorio: grid 2 columnas (usuarios ocupa toda la fila) */}
      <div className="grid grid-cols-1 md:grid-cols-2" style={{ gap: '1.1rem', alignItems: 'start', maxWidth: 920 }}>
        {cardInvitar}
        {cardPendientes}
        <div className="md:col-span-2">{cardUsuarios}</div>
      </div>
    </div>
  )
}
