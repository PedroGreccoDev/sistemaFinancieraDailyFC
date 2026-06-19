// Pantalla de login (/login). Mobile-first; en escritorio (md+) muestra el
// layout partido del diseño (panel índigo de marca a la izquierda + formulario
// a la derecha). Autentica contra el backend vía AuthContext.

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { AuthScreen, AuthFrame, AuthBottom, BrandMark, Field, PrimaryButton, ErrorBanner, TextLink, FM, FB } from './authUi'

export default function Login() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [usuario, setUsuario] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  async function submit() {
    if (!usuario.trim() || !password) {
      setError(true)
      return
    }
    setError(false)
    setLoading(true)
    try {
      await login(usuario.trim(), password)
      navigate('/', { replace: true })
    } catch {
      // 401 (credenciales/usuario inactivo) u otro error → banner de error.
      setError(true)
      setLoading(false)
    }
  }

  // Región de campos, compartida entre móvil y escritorio (mismos inputs).
  const campos = (
    <>
      <div style={{ minHeight: 58, display: 'flex', flexDirection: 'column', justifyContent: 'center', marginBottom: '1.2rem' }}>
        {error ? (
          <ErrorBanner>Usuario o contraseña incorrectos. Revisá los datos e intentá de nuevo.</ErrorBanner>
        ) : (
          <p style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-strong)', margin: 0 }}>Ingresá a tu cuenta</p>
        )}
      </div>

      <div style={{ marginBottom: '1rem' }}>
        <Field label="Usuario" value={usuario} onChange={setUsuario} placeholder="Usuario" autoComplete="username" error={error} disabled={loading} />
      </div>
      <div style={{ marginBottom: '0.7rem' }}>
        <Field label="Contraseña" type="password" value={password} onChange={setPassword} placeholder="••••••••" autoComplete="current-password" error={error} disabled={loading} />
      </div>

      <div style={{ alignSelf: 'flex-end', visibility: loading ? 'hidden' : 'visible' }}>
        <TextLink onClick={() => navigate('/recuperar')}>Olvidé mi contraseña</TextLink>
      </div>
    </>
  )

  const botonIngresar = <PrimaryButton type="submit" loading={loading}>{loading ? 'Ingresando…' : 'Ingresar'}</PrimaryButton>
  const ayuda = (
    <p style={{ marginTop: '1.4rem', textAlign: 'center', fontSize: '0.68rem', color: 'var(--text-2)' }}>
      ¿No tenés cuenta? Pedile una invitación al administrador.
    </p>
  )

  return (
    <>
      {/* ── Móvil: misma tarjeta/estructura que recuperar y registro ──────── */}
      <div className="md:hidden">
        <AuthScreen maxWidth={380}>
          <AuthFrame as="form" onSubmit={(e) => { e.preventDefault(); submit() }}>
            <div style={{ marginBottom: '2.2rem' }}>
              <BrandMark />
            </div>
            {campos}
            <AuthBottom>
              {botonIngresar}
              {ayuda}
            </AuthBottom>
          </AuthFrame>
        </AuthScreen>
      </div>

      {/* ── Escritorio: layout partido a pantalla completa ───────────────── */}
      <form
        onSubmit={(e) => { e.preventDefault(); submit() }}
        className="hidden md:flex"
        style={{ minHeight: '100dvh', width: '100%', background: 'var(--bg)', fontFamily: FM }}
      >
        <div style={{ width: '42%', background: 'linear-gradient(150deg,#3730a3,#6366f1)', padding: '4rem 3.4rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <p style={{ fontFamily: FB, fontSize: '4rem', letterSpacing: '0.1em', color: '#fff', lineHeight: 0.9, margin: 0 }}>Daily FC</p>
            <p style={{ fontSize: '0.74rem', fontWeight: 600, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(199,210,254,0.9)', margin: '0.7rem 0 0' }}>Sistema Financiero</p>
          </div>
          <p style={{ fontSize: '1.2rem', fontWeight: 500, color: 'rgba(224,231,255,0.92)', lineHeight: 1.5, margin: 0, maxWidth: 460 }}>
            Cheques, préstamos, divisas y caja — todo tu negocio financiero en un solo lugar.
          </p>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3rem' }}>
          <div style={{ width: '100%', maxWidth: 420 }}>
            {campos}
            <div style={{ marginTop: '1.6rem' }}>{botonIngresar}</div>
          </div>
        </div>
      </form>
    </>
  )
}
