import type { CSSProperties } from 'react'

/*
  Sistema de variantes inspirado en HeroUI, construido sobre los tokens
  semánticos de index.css (theme-aware). Cada variante deriva sus fondos /
  bordes del color con color-mix, así un solo token sirve para solid/flat/
  bordered/ghost y se adapta automáticamente a claro/oscuro.
*/

export const FM = "'Manrope', sans-serif"

export type Variant = 'primary' | 'secondary' | 'success' | 'warning' | 'danger' | 'neutral'

const TOK: Record<Variant, string> = {
  primary:   'var(--primary)',
  secondary: 'var(--secondary)',
  success:   'var(--success)',
  warning:   'var(--warning)',
  danger:    'var(--danger)',
  neutral:   'var(--text-2)',
}

/** color del variante mezclado con transparente al `pct`% (fondos/bordes suaves) */
const mix = (v: Variant, pct: number) => `color-mix(in srgb, ${TOK[v]} ${pct}%, transparent)`

const baseBtn: CSSProperties = {
  fontFamily: FM,
  fontSize: '0.78rem',
  fontWeight: 700,
  padding: '0.5rem 0.9rem',
  borderRadius: 'var(--r-md)',
  cursor: 'pointer',
  lineHeight: 1.2,
  transition: 'transform .08s ease, background .15s ease, border-color .15s ease, opacity .15s ease',
}

/** Botón sólido (acción primaria). */
export const btnSolid = (v: Variant = 'primary'): CSSProperties => ({
  ...baseBtn,
  background: TOK[v],
  color: 'var(--on-accent)',
  border: '1px solid transparent',
})

/** Botón "flat": fondo del color al 12% + texto del color. */
export const btnFlat = (v: Variant = 'primary'): CSSProperties => ({
  ...baseBtn,
  background: mix(v, 12),
  color: TOK[v],
  border: '1px solid transparent',
})

/** Botón con borde, fondo transparente. */
export const btnBordered = (v: Variant = 'neutral'): CSSProperties => ({
  ...baseBtn,
  background: 'transparent',
  color: TOK[v],
  border: `1px solid ${mix(v, 45)}`,
})

/** Botón fantasma: solo texto, sin fondo ni borde. */
export const btnGhost = (v: Variant = 'neutral'): CSSProperties => ({
  ...baseBtn,
  background: 'transparent',
  color: TOK[v],
  border: '1px solid transparent',
})

/** Chip / badge (pill suave): fondo 14% + texto. */
export const chip = (v: Variant): CSSProperties => ({
  fontFamily: FM,
  fontSize: '0.65rem',
  fontWeight: 700,
  color: TOK[v],
  background: mix(v, 14),
  padding: '2px 8px',
  borderRadius: 'var(--r-sm)',
  whiteSpace: 'nowrap',
})
