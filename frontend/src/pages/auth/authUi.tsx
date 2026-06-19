// Primitivas visuales compartidas por las pantallas de autenticación.
// Estilos inline + tokens de tema (mismo patrón que el resto del panel), para
// que login / recuperar / registro se vean idénticos al diseño en claro y
// oscuro, mobile-first y con su versión de escritorio.

import { useRef, useState } from 'react'
import type { CSSProperties, FormEvent, ReactNode } from 'react'
import { IconAlert } from '../../components/icons'

export const FM = "'Manrope', sans-serif"
export const FB = "'Bebas Neue', sans-serif"
export const ACCENT = '#6366f1'

// ── Iconos locales (solo se usan acá) ────────────────────────────────────────
export function IconEye({ off = false, size = 17 }: { off?: boolean; size?: number }) {
  return off ? (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-10-7-10-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19" />
      <path d="M1 1l22 22M9.5 9.5a3 3 0 0 0 4.2 4.2" />
    </svg>
  ) : (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" />
    </svg>
  )
}

export function IconWhatsapp({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  )
}

export function IconBack({ size = 15 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  )
}

export function Spinner({ size = 16, color = '#fff', style }: { size?: number; color?: string; style?: CSSProperties }) {
  return (
    <svg className="spin" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" style={style}>
      <path d="M21 12a9 9 0 1 1-6.2-8.5" opacity="0.85" />
    </svg>
  )
}

// ── Layout full-viewport centrado ────────────────────────────────────────────
export function AuthScreen({ children, maxWidth = 380 }: { children: ReactNode; maxWidth?: number }) {
  return (
    <div
      className="min-h-dvh"
      style={{
        background: 'var(--bg)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1.5rem',
        fontFamily: FM,
      }}
    >
      <div style={{ width: '100%', maxWidth }}>{children}</div>
    </div>
  )
}

/** Tarjeta contenedora (oculta el desbordado, sombra suave). */
export function AuthCard({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        background: 'var(--surface-grad)',
        border: '1px solid var(--bd-008)',
        borderRadius: 'var(--r-lg)',
        boxShadow: 'var(--shadow-card)',
        overflow: 'hidden',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// Alto y padding compartidos por todas las pantallas de auth con botón primario,
// para que las tarjetas (y por ende los botones anclados abajo) queden iguales.
export const AUTH_MIN_H = 560
export const AUTH_PAD = '1.6rem 1.6rem 2rem'

/** Frame estándar: tarjeta de alto fijo + columna flex con padding consistente. */
export function AuthFrame({ children, as = 'div', onSubmit }: { children: ReactNode; as?: 'div' | 'form'; onSubmit?: (e: FormEvent) => void }) {
  const Inner: any = as
  return (
    <AuthCard style={{ minHeight: AUTH_MIN_H }}>
      <Inner
        onSubmit={onSubmit}
        style={{ display: 'flex', flexDirection: 'column', minHeight: AUTH_MIN_H, padding: AUTH_PAD, fontFamily: FM }}
      >
        {children}
      </Inner>
    </AuthCard>
  )
}

/** Bloque inferior anclado al fondo de la tarjeta (botón primario + texto auxiliar). */
export function AuthBottom({ children }: { children: ReactNode }) {
  return <div style={{ marginTop: 'auto', paddingTop: '1.6rem' }}>{children}</div>
}

// ── Marca ─────────────────────────────────────────────────────────────────────
export function BrandMark({ size = 2.6, sub = true, color = 'var(--text-strong)' }: { size?: number; sub?: boolean; color?: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <p style={{ fontFamily: FB, fontSize: `${size}rem`, letterSpacing: '0.1em', color, lineHeight: 0.9, margin: 0 }}>Daily FC</p>
      {sub && (
        <p style={{ fontSize: '0.6rem', fontWeight: 600, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'var(--text-2)', margin: '0.45rem 0 0' }}>
          Sistema Financiero
        </p>
      )}
    </div>
  )
}

// ── Caption / label uppercase ────────────────────────────────────────────────
const labelStyle: CSSProperties = {
  fontSize: '0.6rem',
  fontWeight: 700,
  letterSpacing: '0.14em',
  textTransform: 'uppercase',
  color: 'var(--text-2)',
}

// ── Campo de texto / password ────────────────────────────────────────────────
interface FieldProps {
  label: string
  type?: 'text' | 'password' | 'tel'
  value: string
  onChange: (v: string) => void
  placeholder?: string
  autoComplete?: string
  error?: boolean
  disabled?: boolean
  hint?: ReactNode
  inputMode?: 'numeric' | 'tel' | 'text'
}

export function Field({ label, type = 'text', value, onChange, placeholder, autoComplete, error, disabled, hint, inputMode }: FieldProps) {
  const [show, setShow] = useState(false)
  const isPw = type === 'password'
  const effectiveType = isPw && show ? 'text' : type
  const border = error ? 'color-mix(in srgb, var(--danger) 45%, transparent)' : 'var(--bd-008)'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
      <label style={labelStyle}>{label}</label>
      <div style={{ position: 'relative' }}>
        <input
          className="fld-auth"
          type={effectiveType}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          autoComplete={autoComplete}
          inputMode={inputMode}
          onChange={(e) => onChange(e.target.value)}
          style={{
            width: '100%',
            background: 'var(--input-bg)',
            border: `1px solid ${border}`,
            borderRadius: 'var(--r-md)',
            padding: isPw ? '0.85rem 2.6rem 0.85rem 0.9rem' : '0.85rem 0.9rem',
            fontFamily: FM,
            fontSize: '0.9rem',
            color: 'var(--text-strong)',
            outline: 'none',
          }}
        />
        {isPw && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? 'Ocultar contraseña' : 'Mostrar contraseña'}
            style={{
              position: 'absolute', right: '0.6rem', top: '50%', transform: 'translateY(-50%)',
              background: 'transparent', border: 'none', color: 'var(--text-2)', cursor: 'pointer',
              display: 'flex', alignItems: 'center', padding: '0.25rem',
            }}
          >
            <IconEye off={show} />
          </button>
        )}
      </div>
      {hint}
    </div>
  )
}

// ── Inputs de código OTP (6 casillas) ────────────────────────────────────────
export function OtpInput({ value, onChange, error, length = 6 }: { value: string; onChange: (v: string) => void; error?: boolean; length?: number }) {
  const refs = useRef<(HTMLInputElement | null)[]>([])
  const chars = Array.from({ length }, (_, i) => value[i] ?? '')
  const border = error ? 'color-mix(in srgb, var(--danger) 45%, transparent)' : 'var(--bd-008)'

  const setChar = (i: number, c: string) => {
    const digit = c.replace(/\D/g, '').slice(-1)
    const next = chars.slice()
    next[i] = digit
    onChange(next.join('').slice(0, length))
    if (digit && i < length - 1) refs.current[i + 1]?.focus()
  }

  return (
    <div style={{ display: 'flex', gap: '0.45rem' }}>
      {chars.map((c, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el }}
          className="fld-auth"
          value={c}
          inputMode="numeric"
          maxLength={1}
          onChange={(e) => setChar(i, e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Backspace' && !chars[i] && i > 0) refs.current[i - 1]?.focus()
          }}
          onPaste={(e) => {
            e.preventDefault()
            const digits = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, length)
            if (digits) {
              onChange(digits)
              refs.current[Math.min(digits.length, length - 1)]?.focus()
            }
          }}
          style={{
            flex: 1, minWidth: 0, textAlign: 'center',
            fontFamily: "'JetBrains Mono', monospace", fontVariantNumeric: 'tabular-nums',
            background: 'var(--input-bg)', border: `1px solid ${border}`, borderRadius: 'var(--r-sm)',
            padding: '0.85rem 0', fontSize: '1.35rem', color: 'var(--text-strong)', outline: 'none',
          }}
        />
      ))}
    </div>
  )
}

// ── Botón primario full-width (con loading) ──────────────────────────────────
export function PrimaryButton({ children, onClick, loading, disabled, type = 'button' }: {
  children: ReactNode
  onClick?: () => void
  loading?: boolean
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      style={{
        width: '100%', background: ACCENT, color: '#fff', border: 'none', borderRadius: 'var(--r-md)',
        padding: '0.95rem', fontFamily: FM, fontSize: '0.92rem', fontWeight: 700, letterSpacing: '0.03em',
        cursor: disabled || loading ? 'default' : 'pointer', opacity: disabled || loading ? 0.9 : 1,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.6rem',
      }}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}

// ── Banner de error ──────────────────────────────────────────────────────────
export function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'flex-start', gap: '0.55rem',
        background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
        border: '1px solid color-mix(in srgb, var(--danger) 32%, transparent)',
        borderRadius: 'var(--r-md)', padding: '0.7rem 0.85rem',
      }}
    >
      <span style={{ color: 'var(--danger)', flexShrink: 0, marginTop: 1, display: 'flex' }}>
        <IconAlert size={16} />
      </span>
      <span style={{ fontSize: '0.76rem', fontWeight: 500, color: 'var(--danger)', lineHeight: 1.35 }}>{children}</span>
    </div>
  )
}

// ── Link "volver" ────────────────────────────────────────────────────────────
export function BackLink({ onClick, children = 'Volver' }: { onClick: () => void; children?: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: '0.35rem', alignSelf: 'flex-start',
        background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
        fontFamily: FM, fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-2)',
      }}
    >
      <IconBack />
      {children}
    </button>
  )
}

/** Link de texto índigo (ej. "Olvidé mi contraseña"). */
export function TextLink({ onClick, children, style }: { onClick?: () => void; children: ReactNode; style?: CSSProperties }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
        fontFamily: FM, fontSize: '0.76rem', fontWeight: 600, color: ACCENT, ...style,
      }}
    >
      {children}
    </button>
  )
}

export { labelStyle }
