import { useQuery } from '@tanstack/react-query'
import { getDolarBlue } from '../api/dolar'

function useDolar() {
  return useQuery({
    queryKey: ['dolar-blue'],
    queryFn: getDolarBlue,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 3 * 60 * 1000,
  })
}

/** Pill compacto para la cabecera mobile */
export function DolarPill() {
  const { data: dolar } = useDolar()

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '5px',
      padding: '4px 10px',
      borderRadius: '100px',
      background: 'var(--ov-004)',
      border: '1px solid var(--bd-006)',
      flexShrink: 0,
    }}>
      <span style={{
        width: '6px',
        height: '6px',
        borderRadius: '50%',
        background: 'linear-gradient(135deg, #34d399, #10b981)',
        boxShadow: '0 0 6px rgba(52,211,153,0.45)',
        flexShrink: 0,
        display: 'inline-block',
      }} />
      <span style={{
        fontSize: '9px',
        fontWeight: 700,
        color: 'var(--text-2)',
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        fontFamily: "'Manrope', sans-serif",
      }}>USD</span>
      {dolar ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '3px' }}>
            <span style={{ fontSize: '7px', fontWeight: 700, color: 'var(--danger)', textTransform: 'uppercase', letterSpacing: '0.1em', lineHeight: 1, opacity: 0.85 }}>C</span>
            <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '12px', color: 'var(--danger)', lineHeight: 1 }}>
              ${dolar.compra.toLocaleString('es-AR')}
            </span>
          </div>
          <span style={{ color: 'var(--text-2)', fontSize: '10px', lineHeight: 1, opacity: 0.5 }}>·</span>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '3px' }}>
            <span style={{ fontSize: '7px', fontWeight: 700, color: 'var(--success)', textTransform: 'uppercase', letterSpacing: '0.1em', lineHeight: 1, opacity: 0.85 }}>V</span>
            <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '12px', color: 'var(--success)', lineHeight: 1 }}>
              ${dolar.venta.toLocaleString('es-AR')}
            </span>
          </div>
        </div>
      ) : (
        <span style={{ color: 'var(--text-2)', fontSize: '12px' }}>…</span>
      )}
    </div>
  )
}

/** Bloque para el pie del sidebar desktop */
export function DolarBlock() {
  const { data: dolar } = useDolar()

  const hora = dolar?.fechaActualizacion
    ? new Date(dolar.fechaActualizacion).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div style={{ padding: '1rem 1.5rem', borderTop: '1px solid var(--bd-006)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '10px' }}>
        <div style={{
          background: 'linear-gradient(135deg, #38bdf8, #6366f1)',
          boxShadow: '0 0 8px rgba(56,189,248,0.30)',
          borderRadius: '6px',
          width: '18px',
          height: '18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          <span style={{ color: 'white', fontSize: '9px', fontWeight: 900, lineHeight: 1, userSelect: 'none' }}>$</span>
        </div>
        <span style={{
          fontFamily: "'Manrope', sans-serif",
          fontSize: '11px',
          fontWeight: 600,
          color: 'var(--text-2)',
          letterSpacing: '0.06em',
        }}>Dólar Blue</span>
      </div>

      {dolar ? (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <p style={{ fontSize: '8px', fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: '3px', opacity: 0.7 }}>Compra</p>
              <p style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '15px', color: 'var(--danger)', lineHeight: 1 }}>
                ${dolar.compra.toLocaleString('es-AR')}
              </p>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p style={{ fontSize: '8px', fontWeight: 700, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: '3px', opacity: 0.7 }}>Venta</p>
              <p style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '15px', color: 'var(--success)', lineHeight: 1 }}>
                ${dolar.venta.toLocaleString('es-AR')}
              </p>
            </div>
          </div>
          {hora && (
            <p style={{ fontSize: '9px', color: 'var(--text-2)', textAlign: 'center', marginTop: '8px', letterSpacing: '0.03em', opacity: 0.65 }}>
              Act. {hora}
            </p>
          )}
        </>
      ) : (
        <div className="skeleton" style={{ height: '36px', borderRadius: '6px' }} />
      )}
    </div>
  )
}
