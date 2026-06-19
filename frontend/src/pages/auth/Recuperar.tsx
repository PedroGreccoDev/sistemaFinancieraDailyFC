// Recuperar contraseña (/recuperar). Flujo en 3 pasos: pedir usuario → ingresar
// código (OTP enviado por WhatsApp) → nueva contraseña. El código se valida
// recién en el backend al fijar la clave (endpoint reset-password toma código +
// clave nueva juntos); si falla, se vuelve al paso del código.

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../../lib/toast'
import { forgotPassword, resetPassword } from '../../api/auth'
import {
  AuthScreen, AuthFrame, AuthBottom, Field, OtpInput, PrimaryButton, ErrorBanner, BackLink,
  IconWhatsapp, FM,
} from './authUi'

type Paso = 1 | 2 | 3

const RESEND_SECS = 30

export default function Recuperar() {
  const navigate = useNavigate()
  const toast = useToast()
  const [paso, setPaso] = useState<Paso>(1)
  const [usuario, setUsuario] = useState('')
  const [codigo, setCodigo] = useState('')
  const [codeError, setCodeError] = useState(false)
  const [pass1, setPass1] = useState('')
  const [pass2, setPass2] = useState('')
  const [secs, setSecs] = useState(RESEND_SECS)
  const [loading, setLoading] = useState(false)

  // Cuenta regresiva del reenvío mientras estamos en el paso del código.
  useEffect(() => {
    if (paso !== 2) return
    setSecs(RESEND_SECS)
    const id = setInterval(() => setSecs((s) => (s <= 1 ? 0 : s - 1)), 1000)
    return () => clearInterval(id)
  }, [paso])

  const mm = Math.floor(secs / 60)
  const ss = String(secs % 60).padStart(2, '0')

  async function enviarCodigo() {
    if (!usuario.trim() || loading) return
    setLoading(true)
    try {
      // Respuesta genérica (no revela si el usuario existe). Igual avanzamos.
      await forgotPassword(usuario.trim())
    } catch {
      // No bloqueamos el flujo: el backend responde 200 genérico de todos modos.
    }
    setCodigo('')
    setCodeError(false)
    setLoading(false)
    setPaso(2)
  }

  function confirmarCodigo() {
    if (codigo.length < 6) {
      setCodeError(true)
      return
    }
    setCodeError(false)
    setPaso(3)
  }

  async function reenviar() {
    setSecs(RESEND_SECS)
    try {
      await forgotPassword(usuario.trim())
      toast('info', 'Te reenviamos el código por WhatsApp.')
    } catch {
      toast('info', 'Te reenviamos el código por WhatsApp.')
    }
  }

  async function actualizar() {
    if (pass1.length < 8 || pass1 !== pass2 || loading) return
    setLoading(true)
    try {
      await resetPassword(usuario.trim(), codigo, pass1)
      toast('success', 'Contraseña actualizada. Ya podés ingresar.')
      navigate('/login')
    } catch {
      // Código inválido/vencido → volver al paso del código con el error.
      setLoading(false)
      setCodeError(true)
      setCodigo('')
      setPaso(2)
    }
  }

  return (
    <AuthScreen>
      <AuthFrame>

          <div style={{ marginBottom: paso === 1 ? '2.4rem' : '2rem' }}>
            <BackLink onClick={() => (paso === 1 ? navigate('/login') : setPaso((p) => (p - 1) as Paso))}>
              {paso === 1 ? 'Volver al login' : 'Volver'}
            </BackLink>
          </div>

          {/* ── Paso 1 · pedir usuario ─────────────────────────────────────── */}
          {paso === 1 && (
            <>
              <p style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-strong)', margin: '0 0 0.6rem' }}>Recuperar contraseña</p>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 1.8rem' }}>
                Ingresá tu usuario y te enviamos un código por WhatsApp para crear una nueva contraseña.
              </p>
              <Field label="Usuario" value={usuario} onChange={setUsuario} placeholder="tu.usuario" autoComplete="username" disabled={loading} />
              <AuthBottom>
                <PrimaryButton onClick={enviarCodigo} disabled={!usuario.trim()} loading={loading}>Enviar código</PrimaryButton>
              </AuthBottom>
            </>
          )}

          {/* ── Paso 2 · ingresar código ───────────────────────────────────── */}
          {paso === 2 && (
            <>
              <div style={{
                width: 52, height: 52, borderRadius: 14, marginBottom: '1.2rem',
                background: 'color-mix(in srgb, var(--success) 12%, transparent)',
                border: '1px solid color-mix(in srgb, var(--success) 30%, transparent)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--success)',
              }}>
                <IconWhatsapp />
              </div>
              <p style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-strong)', margin: '0 0 0.6rem' }}>Revisá tu WhatsApp</p>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 1.3rem' }}>
                Si el usuario existe y tiene un teléfono cargado, te enviamos un código por WhatsApp. Ingresalo acá.
              </p>

              {codeError && (
                <div style={{ marginBottom: '1.1rem' }}>
                  <ErrorBanner>El código es inválido o ya venció. Pedí uno nuevo e intentá otra vez.</ErrorBanner>
                </div>
              )}

              <label style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--text-2)', marginBottom: '0.45rem', display: 'block' }}>Código</label>
              <OtpInput value={codigo} onChange={(v) => { setCodigo(v); setCodeError(false) }} error={codeError} />

              <AuthBottom>
                <PrimaryButton onClick={confirmarCodigo}>Confirmar código</PrimaryButton>
                <p style={{ textAlign: 'center', fontSize: '0.76rem', color: 'var(--text-2)', margin: '1.2rem 0 0' }}>
                  ¿No llegó?{' '}
                  {secs > 0 ? (
                    <span style={{ fontWeight: 600 }}>Reenviar en {mm}:{ss}</span>
                  ) : (
                    <button
                      type="button"
                      onClick={reenviar}
                      style={{ background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', fontFamily: FM, fontSize: '0.76rem', fontWeight: 700, color: '#6366f1' }}
                    >
                      Reenviar código
                    </button>
                  )}
                </p>
              </AuthBottom>
            </>
          )}

          {/* ── Paso 3 · nueva contraseña ──────────────────────────────────── */}
          {paso === 3 && (
            <>
              <p style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-strong)', margin: '0 0 0.6rem' }}>Nueva contraseña</p>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 1.8rem' }}>Elegí una contraseña nueva para tu cuenta.</p>
              <div style={{ marginBottom: '1rem' }}>
                <Field label="Nueva contraseña" type="password" value={pass1} onChange={setPass1} placeholder="Mínimo 8 caracteres" autoComplete="new-password" />
              </div>
              <Field label="Repetir contraseña" type="password" value={pass2} onChange={setPass2} placeholder="••••••••" autoComplete="new-password"
                error={pass2.length > 0 && pass1 !== pass2}
                hint={pass2.length > 0 && pass1 !== pass2
                  ? <span style={{ fontSize: '0.72rem', color: 'var(--danger)' }}>Las contraseñas no coinciden.</span>
                  : undefined}
              />
              <AuthBottom>
                <PrimaryButton onClick={actualizar} disabled={pass1.length < 8 || pass1 !== pass2} loading={loading}>Actualizar contraseña</PrimaryButton>
              </AuthBottom>
            </>
          )}

      </AuthFrame>
    </AuthScreen>
  )
}
