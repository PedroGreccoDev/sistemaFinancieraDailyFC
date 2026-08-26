// Atrapa el error que revienta durante un render de React.
//
// Es el único que los capturadores globales de `window` NO ven: React desmonta
// el árbol y deja **la pantalla en blanco**, sin excepción que llegue a ningún
// lado. Para el operador es lo peor que puede pasar —no hay error, no hay
// cartel, no hay nada— y hasta ahora del lado técnico tampoco quedaba rastro.
//
// Hace dos cosas: lo anota en el registro de bugs (§Registro de bugs) y le
// muestra al operador una pantalla que explica qué pasó y cómo seguir. Un panel
// en blanco lo deja adivinando si perdió lo que estaba cargando.

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportarError } from '../lib/errores'

type Props = { children: ReactNode }
type State = { rompio: boolean }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { rompio: false }

  static getDerivedStateFromError(): State {
    return { rompio: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // De la pila de componentes sale el nombre del que rompió, que es mejor
    // ubicación que el `archivo.js:línea` del bundle compilado: `Cartera` dice
    // dónde mirar, `index-4f2a.js:1` no dice nada.
    const componente = info.componentStack
      ?.split('\n')
      .find((l) => l.trim().startsWith('at '))
      ?.trim()
      .replace(/^at\s+/, '')
      .split(' ')[0]

    reportarError(error, 'render', componente ? `<${componente}>` : '')
  }

  render(): ReactNode {
    if (!this.state.rompio) return this.props.children

    return (
      <div
        style={{
          minHeight: '100dvh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg)',
          padding: '1.5rem',
        }}
      >
        <div style={{ maxWidth: '30rem', textAlign: 'center' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '0.75rem' }}>⚠️</div>
          <h1 style={{ fontSize: '1.15rem', marginBottom: '0.6rem', color: 'var(--text, #e2e8f0)' }}>
            Se rompió la pantalla
          </h1>
          <p style={{ fontSize: '0.9rem', lineHeight: 1.55, color: 'rgba(148,163,184,0.9)' }}>
            El error ya quedó registrado y avisado, no hace falta que lo reportes.
            <br />
            <strong>Lo que ya habías guardado está guardado</strong>; si estabas
            cargando algo sin confirmar, eso sí hay que hacerlo de nuevo.
          </p>
          <button
            onClick={() => window.location.assign('/')}
            style={{
              marginTop: '1.25rem',
              padding: '0.6rem 1.4rem',
              borderRadius: '0.5rem',
              border: '1px solid rgba(129,140,248,0.4)',
              background: 'rgba(129,140,248,0.15)',
              color: '#c7d2fe',
              fontSize: '0.9rem',
              cursor: 'pointer',
            }}
          >
            Volver al inicio
          </button>
        </div>
      </div>
    )
  }
}
