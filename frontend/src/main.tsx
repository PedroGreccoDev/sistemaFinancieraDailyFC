import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { instalarCapturaDeErrores } from './lib/errores'

// Antes de montar nada: si el panel revienta al arrancar, el enganche ya está
// puesto y el error llega al registro de bugs igual (§Registro de bugs).
instalarCapturaDeErrores()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
