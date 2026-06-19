// Administración de usuarios (/usuarios, solo admin). Conectado al backend:
// invitar (enlace de un solo uso enviado por WhatsApp), revocar invitaciones,
// listar usuarios, resetear clave (genera una temporal), activar/desactivar y
// editar teléfono. Usa React Query + apiFetch + toast.

import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useToast } from '../lib/toast'
import { btnSolid, btnBordered } from '../lib/ui'
import { IconAlert, IconClose } from '../components/icons'
import { useCurrentUser, iniciales } from '../lib/auth'
import {
  getInvitaciones, crearInvitacion, revocarInvitacion,
  getUsuarios, actualizarUsuario, crearUsuario,
} from '../api/usuarios'
import type { AuthUser } from '../api/auth'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const ACCENT = '#6366f1'

const CARD: CSSProperties = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const SECTION: CSSProperties = { fontFamily: FN, fontSize: '1.05rem', letterSpacing: '0.06em', color: 'var(--text-strong)', margin: '0 0 0.85rem', lineHeight: 1 }
const MODAL_BG = 'var(--modal)'
const LABEL_STYLE: CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

const DAY = 86_400_000
const diasRestantes = (iso: string) => Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / DAY))
const absLink = (link: string) => (/^https?:\/\//.test(link) ? link : `${window.location.origin}${link}`)
const msgError = (e: unknown) => (e instanceof Error ? e.message : 'Ocurrió un error')

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

// ── Modal: editar teléfono ──────────────────────────────────────────────────
function ModalEditarTel({ user, onClose, onSaved }: { user: AuthUser; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  // El alta/invitación anteponen "54"; en el campo mostramos solo la parte local.
  const [tel, setTel] = useState(user.phone ? user.phone.replace(/^54/, '') : '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (loading) return
    setError(null)
    setLoading(true)
    try {
      const digits = tel.replace(/\D/g, '')
      await actualizarUsuario(user.id, { phone: digits ? `54${digits}` : null })
      toast('success', 'Teléfono actualizado')
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ocurrió un error')
    } finally {
      setLoading(false)
    }
  }

  const fieldBase: CSSProperties = { background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', borderRadius: 'var(--r-sm)', outline: 'none', boxSizing: 'border-box' }

  return (
    <div className="modal-overlay" onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '380px' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)' }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Editar teléfono</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>{user.username}</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div>
            <label style={LABEL_STYLE}>Teléfono</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <span style={{ ...fieldBase, display: 'flex', alignItems: 'center', padding: '0 0.7rem', fontWeight: 600, color: 'var(--text-2)' }}>+54</span>
              <input
                autoFocus
                type="tel"
                inputMode="tel"
                value={tel}
                onChange={(e) => setTel(e.target.value)}
                placeholder="9 11 5555 5555"
                style={{ ...fieldBase, flex: 1, minWidth: 0, padding: '0.5rem 0.75rem' }}
              />
            </div>
            <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.5)', marginTop: '0.3rem' }}>Dejalo vacío para quitar el teléfono.</p>
          </div>
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: loading ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Guardar'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal: confirmación de acciones irreversibles ────────────────────────────
type ConfirmConfig = {
  title: string
  intro?: string
  warning: ReactNode
  confirmLabel: string
  loadingLabel: string
  variant: 'danger' | 'warning'
  onConfirm: () => Promise<void>
}

function ConfirmModal({ config, onClose }: { config: ConfirmConfig; onClose: () => void }) {
  const [loading, setLoading] = useState(false)
  const color = config.variant === 'danger' ? 'var(--danger)' : 'var(--warning)'

  async function go() {
    if (loading) return
    setLoading(true)
    try {
      await config.onConfirm()
      onClose()
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '400px' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.75rem' }}>
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', minWidth: 0 }}>
            <IconAlert size={20} style={{ color, flexShrink: 0 }} />
            <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>{config.title}</h2>
          </div>
          <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-2)', padding: 4, lineHeight: 0 }}><IconClose size={18} /></button>
        </div>
        <div style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          {config.intro && <p style={{ fontFamily: FM, fontSize: '0.8rem', color: 'var(--text-2)', margin: 0 }}>{config.intro}</p>}
          <div style={{ background: `color-mix(in srgb, ${color} 10%, transparent)`, border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`, borderRadius: 'var(--r-md)', padding: '0.9rem 1rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.8rem', color, margin: 0, lineHeight: 1.6 }}>{config.warning}</p>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} disabled={loading} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="button" onClick={go} disabled={loading} style={{ ...btnSolid(config.variant), flex: 1, padding: '0.55rem', opacity: loading ? 0.6 : 1 }}>{loading ? config.loadingLabel : config.confirmLabel}</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Página ────────────────────────────────────────────────────────────────────
export default function Usuarios() {
  const toast = useToast()
  const me = useCurrentUser()
  const qc = useQueryClient()

  const [telefono, setTelefono] = useState('')
  const [esAdmin, setEsAdmin] = useState(false)
  // Resultado de la última invitación: el enlace + si se envió por WhatsApp.
  const [result, setResult] = useState<{ link: string; enviada: boolean } | null>(null)
  const [enviando, setEnviando] = useState(false)
  // Clave temporal revelada tras un reseteo por admin (para comunicarla al usuario).
  const [tempPass, setTempPass] = useState<{ username: string; password: string } | null>(null)
  // Usuario cuyo teléfono se está editando (abre el modal).
  const [editandoTel, setEditandoTel] = useState<AuthUser | null>(null)
  // Configuración del modal de confirmación de acciones irreversibles.
  const [confirmCfg, setConfirmCfg] = useState<ConfirmConfig | null>(null)

  // Alta directa de usuario (sin enlace de invitación).
  const [nuevoUser, setNuevoUser] = useState('')
  const [nuevoPass, setNuevoPass] = useState('')
  const [nuevoTel, setNuevoTel] = useState('')
  const [nuevoEsAdmin, setNuevoEsAdmin] = useState(false)
  const [creando, setCreando] = useState(false)

  const invitacionesQ = useQuery({ queryKey: ['invitaciones'], queryFn: getInvitaciones })
  const usuariosQ = useQuery({ queryKey: ['usuarios'], queryFn: getUsuarios })
  const pendientes = invitacionesQ.data ?? []
  const usuarios = usuariosQ.data ?? []

  async function enviarInvitacion() {
    const digits = telefono.replace(/\D/g, '')
    if (enviando) return
    setEnviando(true)
    try {
      // El UI muestra el prefijo +54; mandamos el teléfono completo (o null si vacío).
      const phone = digits ? `54${digits}` : null
      const res = await crearInvitacion(phone, esAdmin)
      setResult({ link: absLink(res.link), enviada: res.enviada_por_whatsapp })
      setTelefono('')
      setEsAdmin(false)
      qc.invalidateQueries({ queryKey: ['invitaciones'] })
      toast(
        res.enviada_por_whatsapp ? 'success' : 'info',
        res.enviada_por_whatsapp ? 'Invitación enviada por WhatsApp' : 'No se pudo enviar por WhatsApp — pasale el enlace',
      )
    } catch (e) {
      toast('error', msgError(e))
    } finally {
      setEnviando(false)
    }
  }

  async function crearUsuarioDirecto() {
    if (creando) return
    const username = nuevoUser.trim()
    if (!username) {
      toast('error', 'Ingresá un nombre de usuario')
      return
    }
    const password = nuevoPass.trim()
    if (password && password.length < 8) {
      toast('error', 'La contraseña debe tener al menos 8 caracteres')
      return
    }
    const digits = nuevoTel.replace(/\D/g, '')
    setCreando(true)
    try {
      const res = await crearUsuario({
        username,
        // Si se deja vacío, el backend genera una clave temporal y la devuelve.
        password: password || null,
        phone: digits ? `54${digits}` : null,
        is_admin: nuevoEsAdmin,
      })
      qc.invalidateQueries({ queryKey: ['usuarios'] })
      if (res.temp_password) {
        setTempPass({ username: res.usuario.username, password: res.temp_password })
      }
      setNuevoUser('')
      setNuevoPass('')
      setNuevoTel('')
      setNuevoEsAdmin(false)
      toast('success', `Usuario ${res.usuario.username} creado`)
    } catch (e) {
      toast('error', msgError(e))
    } finally {
      setCreando(false)
    }
  }

  async function copiar(texto: string) {
    try {
      await navigator.clipboard.writeText(texto)
      toast('success', 'Enlace copiado')
    } catch {
      toast('error', 'No se pudo copiar el enlace')
    }
  }

  async function revocar(id: string) {
    try {
      await revocarInvitacion(id)
      qc.invalidateQueries({ queryKey: ['invitaciones'] })
      toast('info', 'Invitación revocada')
    } catch (e) {
      toast('error', msgError(e))
    }
  }

  async function toggleActivo(u: AuthUser) {
    try {
      await actualizarUsuario(u.id, { activo: !u.activo })
      qc.invalidateQueries({ queryKey: ['usuarios'] })
      toast('success', u.activo ? `Usuario ${u.username} desactivado` : `Usuario ${u.username} activado`)
    } catch (e) {
      toast('error', msgError(e))
    }
  }

  async function resetClave(u: AuthUser) {
    try {
      const res = await actualizarUsuario(u.id, { reset_password: true })
      if (res.temp_password) setTempPass({ username: u.username, password: res.temp_password })
      qc.invalidateQueries({ queryKey: ['usuarios'] })
      toast('success', `Se generó una clave temporal para ${u.username}`)
    } catch (e) {
      toast('error', msgError(e))
    }
  }

  // ── Bloques reutilizables ───────────────────────────────────────────────────
  const cardCrear = (
    <div style={{ ...CARD, padding: '1.1rem 1.2rem', display: 'flex', flexDirection: 'column' }}>
      <p style={{ fontSize: '0.72rem', color: 'var(--text-2)', margin: '0 0 0.95rem' }}>
        Alta directa, sin enlace. Si dejás la clave vacía, se genera una temporal para comunicar.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <label style={{ fontSize: '0.58rem', fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-2)' }}>Usuario</label>
          <input
            className="fld-auth"
            type="text"
            autoCapitalize="none"
            autoCorrect="off"
            value={nuevoUser}
            onChange={(e) => setNuevoUser(e.target.value)}
            placeholder="nombredeusuario"
            style={{ background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.7rem 0.8rem', fontFamily: FM, fontSize: '0.85rem', color: 'var(--text-strong)', outline: 'none' }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <label style={{ fontSize: '0.58rem', fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-2)' }}>Contraseña (opcional)</label>
          <input
            className="fld-auth"
            type="text"
            autoCapitalize="none"
            autoCorrect="off"
            value={nuevoPass}
            onChange={(e) => setNuevoPass(e.target.value)}
            placeholder="Dejar vacío para generar una temporal"
            style={{ background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.7rem 0.8rem', fontFamily: FM, fontSize: '0.85rem', color: 'var(--text-strong)', outline: 'none' }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <label style={{ fontSize: '0.58rem', fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-2)' }}>Teléfono (opcional)</label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <span style={{ display: 'flex', alignItems: 'center', background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0 0.7rem', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-2)' }}>+54</span>
            <input
              className="fld-auth"
              type="tel"
              inputMode="tel"
              value={nuevoTel}
              onChange={(e) => setNuevoTel(e.target.value)}
              placeholder="9 11 5555 5555"
              style={{ flex: 1, minWidth: 0, background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.7rem 0.8rem', fontFamily: FM, fontSize: '0.85rem', color: 'var(--text-strong)', outline: 'none' }}
            />
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.85rem 0 0.95rem', marginTop: 'auto' }}>
        <span style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--text-1)' }}>¿Es administrador?</span>
        <Toggle on={nuevoEsAdmin} onClick={() => setNuevoEsAdmin((v) => !v)} />
      </div>

      <button type="button" onClick={crearUsuarioDirecto} disabled={creando} style={{ width: '100%', background: ACCENT, color: '#fff', border: 'none', borderRadius: 'var(--r-md)', padding: '0.8rem', fontFamily: FM, fontSize: '0.85rem', fontWeight: 700, cursor: creando ? 'default' : 'pointer', opacity: creando ? 0.7 : 1 }}>
        {creando ? 'Creando…' : 'Crear usuario'}
      </button>
    </div>
  )

  const cardInvitar = (
    <div style={{ ...CARD, padding: '1.1rem 1.2rem', display: 'flex', flexDirection: 'column' }}>
      <p style={{ fontSize: '0.72rem', color: 'var(--text-2)', margin: '0 0 0.95rem' }}>
        Enviá un enlace de un solo uso por WhatsApp. La persona elige su propia clave (vence en 24 h).
      </p>

      {result ? (
        <div style={{
          background: `color-mix(in srgb, ${result.enviada ? 'var(--success)' : '#f59e0b'} 8%, transparent)`,
          border: `1px solid color-mix(in srgb, ${result.enviada ? 'var(--success)' : '#f59e0b'} 28%, transparent)`,
          borderRadius: 'var(--r-md)', padding: '0.85rem',
        }}>
          <p style={{ fontSize: '0.74rem', fontWeight: 600, color: result.enviada ? 'var(--success)' : '#f59e0b', margin: '0 0 0.7rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            {result.enviada ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><polyline points="20 6 9 17 4 12" /></svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /></svg>
            )}
            {result.enviada ? 'Invitación enviada por WhatsApp' : 'No se pudo enviar por WhatsApp — pasale este enlace'}
          </p>
          <p style={{ fontSize: '0.64rem', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-2)', margin: '0 0 0.4rem' }}>
            {result.enviada ? 'Enlace de respaldo' : 'Enlace de invitación'}
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <span style={{ flex: 1, minWidth: 0, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.7rem', color: 'var(--text-2)', background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.55rem 0.7rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{result.link}</span>
            <button type="button" onClick={() => copiar(result.link)} style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '0.35rem', background: ACCENT, color: '#fff', border: 'none', borderRadius: 'var(--r-sm)', padding: '0.55rem 0.7rem', fontFamily: FM, fontSize: '0.72rem', fontWeight: 700, cursor: 'pointer' }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
              Copiar
            </button>
          </div>
          <button type="button" onClick={() => setResult(null)} style={{ marginTop: '0.85rem', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', fontFamily: FM, fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-2)' }}>
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
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.55rem 0 0.95rem', marginTop: 'auto' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--text-1)' }}>¿Es administrador?</span>
            <Toggle on={esAdmin} onClick={() => setEsAdmin((v) => !v)} />
          </div>
          <button type="button" onClick={enviarInvitacion} disabled={enviando} style={{ width: '100%', background: ACCENT, color: '#fff', border: 'none', borderRadius: 'var(--r-md)', padding: '0.8rem', fontFamily: FM, fontSize: '0.85rem', fontWeight: 700, cursor: enviando ? 'default' : 'pointer', opacity: enviando ? 0.7 : 1 }}>
            {enviando ? 'Enviando…' : 'Enviar invitación'}
          </button>
        </>
      )}
    </div>
  )

  const cardPendientes = (
    <div style={{ ...CARD, padding: '1.1rem 1.2rem' }}>
      {pendientes.length === 0 ? (
        <p style={{ fontSize: '0.78rem', color: 'var(--text-2)', margin: 0 }}>No hay invitaciones pendientes.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          {pendientes.map((inv) => (
            <div key={inv.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.6rem', background: 'var(--input-bg)', border: '1px solid var(--bd-006)', borderRadius: 'var(--r-md)', padding: '0.7rem 0.85rem' }}>
              <div style={{ minWidth: 0 }}>
                <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.82rem', color: 'var(--text-strong)', margin: '0 0 2px' }}>{inv.phone ? `+${inv.phone}` : 'Sin teléfono'}</p>
                <p style={{ fontSize: '0.66rem', color: 'var(--text-2)', margin: 0 }}>
                  Vence en {diasRestantes(inv.expires_at)} días · {inv.is_admin ? <span style={{ color: '#818cf8', fontWeight: 600 }}>Admin</span> : 'Usuario'}
                </p>
              </div>
              <Ghost danger onClick={() => setConfirmCfg({
                title: 'Revocar invitación',
                intro: inv.phone ? `Invitación para +${inv.phone}.` : 'Invitación sin teléfono.',
                warning: <>El enlace dejará de funcionar y <strong>no se puede recuperar</strong>. Si la necesitás, vas a tener que generar una invitación nueva.</>,
                confirmLabel: 'Sí, revocar',
                loadingLabel: 'Revocando…',
                variant: 'danger',
                onConfirm: () => revocar(inv.id),
              })}>Revocar</Ghost>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  const cardUsuarios = (
    <div style={{ ...CARD, padding: '1.1rem 1.2rem' }}>
      <div className="grid grid-cols-1 sm:grid-cols-2" style={{ gap: '0.7rem', alignItems: 'start' }}>
        {usuarios.map((u) => {
          const esVos = u.username.toLowerCase() === me.username.toLowerCase()
          return (
          <div key={u.id} style={{
            background: 'var(--input-bg)', borderRadius: 'var(--r-md)', padding: '0.85rem',
            border: `1px solid ${esVos ? 'rgba(99,102,241,0.25)' : 'var(--bd-006)'}`,
            opacity: u.activo ? 1 : 0.72,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.7rem' }}>
              <Avatar initials={iniciales(u.username)} tone={esVos ? 'accent' : 'muted'} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <p style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--text-strong)', margin: 0 }}>
                  {u.username}
                  {esVos && <span style={{ fontSize: '0.62rem', fontWeight: 600, color: '#818cf8', background: 'rgba(99,102,241,0.16)', borderRadius: 999, padding: '1px 7px', marginLeft: 5 }}>Vos</span>}
                </p>
                <p style={{ fontSize: '0.68rem', color: 'var(--text-2)', margin: 0 }}>
                  {u.is_admin ? 'Admin' : 'Usuario'} · {u.activo ? 'Activo' : 'Inactivo'}{u.phone ? ` · +${u.phone}` : ''}
                </p>
              </div>
              {!esVos && (
                <span style={{ width: 9, height: 9, borderRadius: '50%', flexShrink: 0, background: u.activo ? 'var(--success)' : 'var(--bd-012)' }} />
              )}
            </div>

            {esVos ? (
              <p style={{ fontSize: '0.68rem', color: 'var(--text-2)', display: 'flex', alignItems: 'center', gap: '0.35rem', margin: 0 }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg>
                No podés desactivarte ni quitarte el rol a vos mismo.
              </p>
            ) : (
              <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
                <Ghost onClick={() => setConfirmCfg({
                  title: 'Resetear clave',
                  intro: `Vas a resetear la clave de ${u.username}.`,
                  warning: <>Se generará una <strong>clave temporal nueva</strong> y se cerrarán todas sus sesiones activas. La clave actual dejará de funcionar. <strong>No se puede deshacer.</strong></>,
                  confirmLabel: 'Sí, resetear',
                  loadingLabel: 'Reseteando…',
                  variant: 'warning',
                  onConfirm: () => resetClave(u),
                })}>Resetear clave</Ghost>
                {u.activo
                  ? <Ghost danger onClick={() => setConfirmCfg({
                      title: 'Desactivar usuario',
                      intro: `Vas a desactivar a ${u.username}.`,
                      warning: <>No va a poder ingresar al panel y se <strong>cerrarán sus sesiones activas</strong>. Podés volver a activarlo cuando quieras.</>,
                      confirmLabel: 'Sí, desactivar',
                      loadingLabel: 'Desactivando…',
                      variant: 'danger',
                      onConfirm: () => toggleActivo(u),
                    })}>Desactivar</Ghost>
                  : <Solid color="var(--success)" onClick={() => toggleActivo(u)}>Activar</Solid>}
                <Ghost onClick={() => setEditandoTel(u)} style={{ color: 'var(--text-2)' }}>Editar tel.</Ghost>
              </div>
            )}
          </div>
          )
        })}
      </div>
    </div>
  )

  // ── Banner de clave temporal (tras reset por admin) ─────────────────────────
  const cardTempPass = tempPass && (
    <div style={{
      background: 'color-mix(in srgb, var(--success) 8%, transparent)',
      border: '1px solid color-mix(in srgb, var(--success) 28%, transparent)',
      borderRadius: 'var(--r-lg)', padding: '1rem 1.2rem',
    }}>
      <p style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--success)', margin: '0 0 0.6rem' }}>
        Clave temporal de {tempPass.username}
      </p>
      <p style={{ fontSize: '0.72rem', color: 'var(--text-2)', margin: '0 0 0.7rem' }}>
        Pasásela por un canal seguro. El usuario debería cambiarla al ingresar. Esta clave no se vuelve a mostrar.
      </p>
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
        <span style={{ flex: 1, minWidth: 0, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.9rem', color: 'var(--text-strong)', background: 'var(--input-bg)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.6rem 0.75rem', letterSpacing: '0.04em' }}>{tempPass.password}</span>
        <button type="button" onClick={() => copiar(tempPass.password)} style={{ flexShrink: 0, background: ACCENT, color: '#fff', border: 'none', borderRadius: 'var(--r-sm)', padding: '0.6rem 0.8rem', fontFamily: FM, fontSize: '0.72rem', fontWeight: 700, cursor: 'pointer' }}>Copiar</button>
        <button type="button" onClick={() => setTempPass(null)} style={{ flexShrink: 0, background: 'transparent', color: 'var(--text-2)', border: '1px solid var(--bd-008)', borderRadius: 'var(--r-sm)', padding: '0.6rem 0.8rem', fontFamily: FM, fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer' }}>Ocultar</button>
      </div>
    </div>
  )

  return (
    <div className="px-4 py-5 sm:px-8 sm:py-6" style={{ fontFamily: FM }}>
      <Link
        to="/configuracion"
        style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-2)', textDecoration: 'none', marginBottom: '0.6rem' }}
      >
        ← Configuración
      </Link>
      <p style={{ fontFamily: FN, fontSize: '1.9rem', letterSpacing: '0.05em', color: 'var(--text-strong)', margin: '0 0 1.4rem', lineHeight: 1 }}>Usuarios</p>

      {cardTempPass && <div style={{ marginBottom: '1.4rem' }}>{cardTempPass}</div>}

      {/* Dashboard: barra lateral con las acciones (alta + invitaciones pendientes)
          y la lista de cuentas ocupando el resto del ancho. En móvil/tablet apila. */}
      <div className="grid grid-cols-1 lg:grid-cols-2" style={{ gap: '1.8rem', alignItems: 'start' }}>
        <div>
          <section>
            <p style={SECTION}>Crear usuario</p>
            {cardCrear}
          </section>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.8rem' }}>
          <section>
            <p style={SECTION}>Invitar por enlace</p>
            {cardInvitar}
          </section>

          <section>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '0 0 0.85rem' }}>
              <p style={{ ...SECTION, margin: 0 }}>Cuentas</p>
              <span style={{ fontSize: '0.6rem', fontWeight: 700, color: '#818cf8', background: 'rgba(99,102,241,0.14)', borderRadius: 999, padding: '1px 8px' }}>{usuarios.length}</span>
            </div>
            {cardUsuarios}
          </section>

          <section>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: '0 0 0.85rem' }}>
              <p style={{ ...SECTION, margin: 0 }}>Invitaciones pendientes</p>
              <span style={{ fontSize: '0.6rem', fontWeight: 700, color: '#818cf8', background: 'rgba(99,102,241,0.14)', borderRadius: 999, padding: '1px 8px' }}>{pendientes.length}</span>
            </div>
            {cardPendientes}
          </section>
        </div>
      </div>

      {editandoTel && (
        <ModalEditarTel
          user={editandoTel}
          onClose={() => setEditandoTel(null)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['usuarios'] })
            setEditandoTel(null)
          }}
        />
      )}

      {confirmCfg && <ConfirmModal config={confirmCfg} onClose={() => setConfirmCfg(null)} />}
    </div>
  )
}
