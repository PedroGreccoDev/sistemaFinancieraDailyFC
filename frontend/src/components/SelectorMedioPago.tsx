import type { MedioPago } from '../types'

const FM = "'Manrope', sans-serif"

const LABEL: React.CSSProperties = {
  display: 'block',
  fontFamily: FM,
  fontSize: '0.65rem',
  fontWeight: 700,
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: 'rgba(100,116,139,0.7)',
  marginBottom: '0.3rem',
}

const OPCIONES: { valor: MedioPago; icono: string; texto: string }[] = [
  { valor: 'EFECTIVO', icono: '💵', texto: 'Efectivo' },
  { valor: 'TRANSFERENCIA', icono: '🏦', texto: 'Transferencia' },
]

/**
 * Por cuál de las dos cajas pasa la plata de esta operación.
 *
 * Son dos botones y no un desplegable a propósito: es la decisión que más veces
 * por día toma el operador, y con las dos opciones a la vista se elige de un
 * toque. Un `select` obliga a abrir, leer y elegir cada vez.
 *
 * El efectivo viene elegido de entrada porque es el caso normal del negocio: el
 * que no mira este control carga bien igual.
 */
export default function SelectorMedioPago({
  valor,
  onChange,
  label = '¿Por dónde entra o sale la plata?',
  ayuda,
  disabled = false,
}: {
  valor: MedioPago
  onChange: (m: MedioPago) => void
  label?: string
  /** Aclaración extra cuando la operación tiene alguna vuelta (dos patas, etc.). */
  ayuda?: string
  disabled?: boolean
}) {
  return (
    <div>
      <label style={LABEL}>{label}</label>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        {OPCIONES.map((o) => {
          const activo = valor === o.valor
          return (
            <button
              key={o.valor}
              type="button"
              disabled={disabled}
              onClick={() => onChange(o.valor)}
              style={{
                flex: 1,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.4rem',
                fontFamily: FM,
                fontSize: '0.78rem',
                fontWeight: activo ? 700 : 500,
                padding: '0.5rem 0.75rem',
                cursor: disabled ? 'default' : 'pointer',
                color: activo ? 'var(--text-1)' : 'var(--text-2)',
                background: activo
                  ? 'color-mix(in srgb, var(--primary) 14%, transparent)'
                  : 'var(--bg)',
                border: `1px solid ${
                  activo
                    ? 'color-mix(in srgb, var(--primary) 45%, transparent)'
                    : 'var(--bd-012)'
                }`,
                borderRadius: 'var(--r-md)',
                opacity: disabled ? 0.5 : 1,
                transition: 'background 120ms, border-color 120ms',
              }}
            >
              <span aria-hidden>{o.icono}</span>
              {o.texto}
            </button>
          )
        })}
      </div>
      {ayuda && (
        <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.75)', lineHeight: 1.5, marginTop: '0.35rem' }}>
          {ayuda}
        </p>
      )}
    </div>
  )
}
