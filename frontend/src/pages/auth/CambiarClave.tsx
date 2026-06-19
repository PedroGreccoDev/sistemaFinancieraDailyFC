// Cambio obligatorio de contraseña (/cambiar-clave). El usuario llega acá tras
// ingresar con una clave temporal (reset del admin o alta con clave generada):
// ProtectedRoute lo retiene en esta pantalla hasta que defina su propia clave.
// No pide la temporal de nuevo (el login ya probó que la conoce): solo la nueva y
// su repetición. Al confirmar, el backend invalida las demás sesiones y devuelve
// un token nuevo (lo guarda el AuthContext) y entramos al panel.

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../../lib/toast'
import { useAuth } from '../../auth/AuthContext'
import {
  AuthScreen, AuthFrame, AuthBottom, BrandMark, Field, PrimaryButton, ErrorBanner, TextLink,
} from './authUi'

export default function CambiarClave() {
  const navigate = useNavigate()
  const toast = useToast()
  const { definirPassword, logout } = useAuth()
  const [pass1, setPass1] = useState('')
  const [pass2, setPass2] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const noCoincide = pass2.length > 0 && pass1 !== pass2
  const puedeEnviar = pass1.length >= 8 && pass1 === pass2

  async function submit() {
    if (!puedeEnviar || loading) return
    setError('')
    setLoading(true)
    try {
      await definirPassword(pass1)
      toast('success', 'Contraseña actualizada. ¡Listo!')
      navigate('/', { replace: true })
    } catch (e) {
      // El backend devuelve un detail útil (clave actual incorrecta / igual a la nueva).
      setError(e instanceof Error ? e.message : 'No se pudo cambiar la contraseña.')
      setLoading(false)
    }
  }

  return (
    <AuthScreen maxWidth={380}>
      <AuthFrame as="form" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <div style={{ marginBottom: '1.8rem' }}>
          <BrandMark />
        </div>

        <p style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-strong)', margin: '0 0 0.6rem' }}>
          Creá tu contraseña
        </p>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 1.6rem' }}>
          Estás usando una contraseña temporal. Definí una propia para seguir.
        </p>

        {error && (
          <div style={{ marginBottom: '1.1rem' }}>
            <ErrorBanner>{error}</ErrorBanner>
          </div>
        )}

        <div style={{ marginBottom: '1rem' }}>
          <Field label="Nueva contraseña" type="password" value={pass1} onChange={setPass1}
            placeholder="Mínimo 8 caracteres" autoComplete="new-password" disabled={loading} />
        </div>
        <Field label="Repetir contraseña" type="password" value={pass2} onChange={setPass2}
          placeholder="••••••••" autoComplete="new-password" disabled={loading}
          error={noCoincide}
          hint={noCoincide
            ? <span style={{ fontSize: '0.72rem', color: 'var(--danger)' }}>Las contraseñas no coinciden.</span>
            : undefined}
        />

        <AuthBottom>
          <PrimaryButton type="submit" disabled={!puedeEnviar} loading={loading}>
            Guardar contraseña
          </PrimaryButton>
          <p style={{ textAlign: 'center', margin: '1.2rem 0 0' }}>
            <TextLink onClick={logout}>Cerrar sesión</TextLink>
          </p>
        </AuthBottom>
      </AuthFrame>
    </AuthScreen>
  )
}
