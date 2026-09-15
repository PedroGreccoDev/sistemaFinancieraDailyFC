import { IconSearch, IconClose } from './icons'

// Buscador por nombre para los listados. Va al lado de los <DropdownFilter> de
// cada sección y comparte su altura y su etiqueta, así la fila de filtros se lee
// como una sola cosa.
//
// Filtra en el front sobre lo que la página ya tiene cargado: no pega a la API
// ni espera nada, la lista se achica mientras el operador tipea. Alcanza porque
// ninguna sección trae miles de filas, y evita que el listado parpadee entre
// tecla y tecla, que en el mostrador se lee como que el sistema se colgó.

const FM = "'Manrope', sans-serif"

export default function BuscadorCliente({
  value,
  onChange,
  label = 'Buscar',
  placeholder = 'Nombre del cliente…',
  ancho = 210,
}: {
  value: string
  onChange: (v: string) => void
  label?: string
  placeholder?: string
  /** Ancho en px. La fila de filtros lo deja encoger si no entra. */
  ancho?: number
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      <label style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)' }}>
        {label}
      </label>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <span style={{ position: 'absolute', left: '0.6rem', display: 'inline-flex', color: 'rgba(148,163,184,0.6)', pointerEvents: 'none' }}>
          <IconSearch size={14} />
        </span>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-label={label}
          style={{
            fontFamily: FM, fontSize: '0.78rem', fontWeight: 500,
            background: 'var(--surface-grad)', border: '1px solid var(--bd-008)',
            color: 'var(--text-1)', borderRadius: 'var(--r-md)',
            padding: '0.45rem 1.9rem 0.45rem 1.9rem',
            width: ancho, maxWidth: '100%', minWidth: 0, outline: 'none',
          }}
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            title="Borrar la búsqueda"
            aria-label="Borrar la búsqueda"
            style={{ position: 'absolute', right: '0.45rem', display: 'inline-flex', alignItems: 'center', background: 'transparent', border: 'none', padding: '2px', cursor: 'pointer', color: 'rgba(148,163,184,0.75)' }}
          >
            <IconClose size={13} />
          </button>
        )}
      </div>
    </div>
  )
}
