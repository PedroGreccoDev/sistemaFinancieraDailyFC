import { createContext, useCallback, useContext, useState } from 'react'
import type { ReactNode } from 'react'
import { IconCheck, IconAlert } from '../components/icons'

type ToastType = 'success' | 'error' | 'info'
interface Toast { id: number; type: ToastType; msg: string }

type Push = (type: ToastType, msg: string) => void

const ToastCtx = createContext<Push>(() => {})

export function useToast(): Push {
  return useContext(ToastCtx)
}

const FM = "'Manrope', sans-serif"
const COLOR: Record<ToastType, string> = {
  success: 'var(--success)',
  error: 'var(--danger)',
  info: 'var(--primary)',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback<Push>((type, msg) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, type, msg }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3800)
  }, [])

  const remove = (id: number) => setToasts((t) => t.filter((x) => x.id !== id))

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div style={{
        position: 'fixed', top: 'calc(0.9rem + env(safe-area-inset-top))', left: '50%', transform: 'translateX(-50%)',
        zIndex: 100, display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'center',
        width: 'max-content', maxWidth: '92vw', pointerEvents: 'none',
      }}>
        {toasts.map((t) => (
          <button
            key={t.id}
            onClick={() => remove(t.id)}
            className="toast-item"
            style={{
              pointerEvents: 'auto', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.6rem',
              fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, textAlign: 'left',
              color: 'var(--text-1)', background: 'var(--modal)',
              border: `1px solid color-mix(in srgb, ${COLOR[t.type]} 35%, var(--bd-008))`,
              borderLeft: `3px solid ${COLOR[t.type]}`,
              borderRadius: 'var(--r-md)', padding: '0.6rem 0.9rem',
              boxShadow: 'var(--shadow-card-hover)',
            }}
          >
            <span style={{ color: COLOR[t.type], display: 'flex', flexShrink: 0 }}>
              {t.type === 'error' ? <IconAlert size={17} /> : <IconCheck size={17} />}
            </span>
            <span>{t.msg}</span>
          </button>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
