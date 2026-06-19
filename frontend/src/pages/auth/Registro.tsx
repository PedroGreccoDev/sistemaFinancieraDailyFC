// Registro por invitación (/registro?token=…). Valida el token contra el backend
// y crea la cuenta (auto-login al éxito).
// Estados: validando el enlace → formulario de alta → enlace inválido/vencido.

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useToast } from '../../lib/toast'
import { registrarReq, validarInvitacion } from '../../api/auth'
import { setToken } from '../../api/client'
import {
  AuthScreen, AuthCard, AuthFrame, AuthBottom, BrandMark, Field, PrimaryButton, Spinner, TextLink, FM,
} from './authUi'

type Estado = 'validando' | 'form' | 'invalido'

export default function Registro() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const toast = useToast()
  const token = params.get('token') ?? ''

  const [estado, setEstado] = useState<Estado>('validando')
  const [usuario, setUsuario] = useState('')
  const [pass1, setPass1] = useState('')
  const [pass2, setPass2] = useState('')
  const [usuarioEnUso, setUsuarioEnUso] = useState(false)
  const [loading, setLoading] = useState(false)

  // Validación real del enlace de invitación contra el backend.
  useEffect(() => {
    if (!token) { setEstado('invalido'); return }
    let vivo = true
    validarInvitacion(token)
      .then(() => { if (vivo) setEstado('form') })
      .catch(() => { if (vivo) setEstado('invalido') })
    return () => { vivo = false }
  }, [token])

  const puedeCrear = usuario.trim().length > 0 && !usuarioEnUso && pass1.length >= 8 && pass1 === pass2

  async function crear() {
    if (!puedeCrear || loading) return
    setLoading(true)
    try {
      const { token: sessionToken } = await registrarReq(token, usuario.trim(), pass1)
      setToken(sessionToken)
      // Recargamos para que el AuthProvider hidrate la sesión y entre al panel.
      window.location.assign('/')
    } catch (e) {
      setLoading(false)
      const msg = e instanceof Error ? e.message : ''
      if (/existe/i.test(msg)) {
        setUsuarioEnUso(true)
      } else if (/enlace|inv[aá]lid|venci|v[aá]lid/i.test(msg)) {
        setEstado('invalido')
      } else {
        toast('error', msg || 'No se pudo crear la cuenta. Intentá de nuevo.')
      }
    }
  }

  return (
    <AuthScreen>

        {/* ── Validando enlace ─────────────────────────────────────────────── */}
        {estado === 'validando' && (
          <AuthCard style={{ minHeight: 480 }}>
            <div style={{ padding: '2rem 1.6rem', minHeight: 480, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontFamily: FM }}>
              <Spinner size={34} color="#818cf8" style={{ marginBottom: '1.4rem' }} />
              <p style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-strong)', margin: '0 0 0.4rem' }}>Validando tu invitación…</p>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-2)', margin: 0 }}>Un momento, estamos verificando el enlace.</p>
            </div>
          </AuthCard>
        )}

        {/* ── Enlace inválido / vencido ────────────────────────────────────── */}
        {estado === 'invalido' && (
          <AuthCard style={{ minHeight: 480 }}>
            <div style={{ padding: '2.5rem 1.6rem', minHeight: 480, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontFamily: FM }}>
              <div style={{
                width: 60, height: 60, borderRadius: 16, marginBottom: '1.4rem',
                background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
                border: '1px solid color-mix(in srgb, var(--danger) 30%, transparent)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--danger)',
              }}>
                <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </div>
              <p style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-strong)', margin: '0 0 0.6rem' }}>Este enlace ya no es válido</p>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 1.8rem', maxWidth: 240 }}>
                La invitación venció o ya fue usada. Pedile al administrador una nueva invitación.
              </p>
              <TextLink onClick={() => navigate('/login')} style={{ fontSize: '0.8rem' }}>Ir al login</TextLink>
            </div>
          </AuthCard>
        )}

        {/* ── Formulario de alta ───────────────────────────────────────────── */}
        {estado === 'form' && (
          <AuthFrame as="form" onSubmit={(e) => { e.preventDefault(); crear() }}>
            <div style={{ marginBottom: '1.6rem' }}>
              <BrandMark size={2} sub={false} />
            </div>
            <p style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-strong)', margin: '0 0 0.4rem' }}>Creá tu cuenta</p>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 1.5rem' }}>
              Te invitaron al sistema. Elegí tu usuario y contraseña para entrar.
            </p>

            <div style={{ marginBottom: '0.9rem' }}>
              <Field
                label="Elegí un usuario" value={usuario} onChange={(v) => { setUsuario(v); setUsuarioEnUso(false) }} placeholder="Nicolas Perez" autoComplete="username"
                error={usuarioEnUso}
                hint={usuarioEnUso
                  ? <span style={{ fontSize: '0.72rem', color: 'var(--danger)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
                      Ese usuario ya existe. Probá con otro.
                    </span>
                  : undefined}
              />
            </div>
            <div style={{ marginBottom: '0.9rem' }}>
              <Field label="Contraseña" type="password" value={pass1} onChange={setPass1} placeholder="Mínimo 8 caracteres" autoComplete="new-password" />
            </div>
            <Field label="Repetir contraseña" type="password" value={pass2} onChange={setPass2} placeholder="••••••••" autoComplete="new-password"
              error={pass2.length > 0 && pass1 !== pass2}
              hint={pass2.length > 0 && pass1 !== pass2
                ? <span style={{ fontSize: '0.72rem', color: 'var(--danger)' }}>Las contraseñas no coinciden.</span>
                : undefined}
            />

            <AuthBottom>
              <PrimaryButton type="submit" disabled={!puedeCrear} loading={loading}>Crear cuenta</PrimaryButton>
            </AuthBottom>
          </AuthFrame>
        )}

    </AuthScreen>
  )
}
