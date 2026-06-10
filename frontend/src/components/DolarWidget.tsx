import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getDolarBlue } from '../api/dolar'
import type { CSSProperties } from 'react'

const glass: CSSProperties = {
  backdropFilter: 'blur(48px) saturate(200%) brightness(1.06)',
  WebkitBackdropFilter: 'blur(48px) saturate(200%) brightness(1.06)',
  background: 'linear-gradient(145deg, rgba(255,255,255,0.26) 0%, rgba(255,255,255,0.11) 50%, rgba(255,255,255,0.04) 100%)',
  border: '1px solid rgba(255,255,255,0.34)',
  boxShadow: [
    '0 28px 72px rgba(0,0,0,0.14)',
    '0 6px 20px rgba(0,0,0,0.09)',
    'inset 0 1.5px 0 rgba(255,255,255,0.65)',
    'inset 0 -1px 0 rgba(0,0,0,0.05)',
    'inset 1px 0 0 rgba(255,255,255,0.18)',
  ].join(', '),
}

export default function DolarWidget() {
  const [collapsed, setCollapsed] = useState(false)

  const { data: dolar } = useQuery({
    queryKey: ['dolar-blue'],
    queryFn: getDolarBlue,
    refetchInterval: 5 * 60 * 1000,
    staleTime: 3 * 60 * 1000,
  })

  const hora = dolar?.fechaActualizacion
    ? new Date(dolar.fechaActualizacion).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })
    : null

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        style={{ ...glass, position: 'fixed', bottom: '1.5rem', right: '1rem', zIndex: 50, borderRadius: '100px' }}
        className="flex items-center gap-2.5 px-4 py-2.5 hover:-translate-y-0.5 active:translate-y-0 transition-transform duration-200"
      >
        <span
          style={{ background: 'linear-gradient(135deg,#34d399,#10b981)', boxShadow: '0 0 8px rgba(52,211,153,0.55)' }}
          className="w-1.5 h-1.5 rounded-full shrink-0"
        />
        <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest">USD</span>
        {dolar ? (
          <span className="font-mono font-bold text-sm text-slate-800 dark:text-slate-100">
            ${dolar.venta.toLocaleString('es-AR')}
          </span>
        ) : (
          <span className="text-slate-400 text-xs">…</span>
        )}
      </button>
    )
  }

  return (
    <div
      style={{ ...glass, position: 'fixed', bottom: '1.5rem', right: '1rem', zIndex: 50, borderRadius: '24px', minWidth: '198px' }}
      className="p-4 hover:-translate-y-0.5 transition-transform duration-200"
    >
      {/* Specular top sheen */}
      <div style={{
        position: 'absolute', top: 0, left: '18%', right: '18%', height: '1px',
        background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.85), transparent)',
        borderRadius: '100px',
      }} />

      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <div style={{
            background: 'linear-gradient(135deg,#38bdf8,#6366f1)',
            boxShadow: '0 0 10px rgba(56,189,248,0.48)',
            borderRadius: '8px',
          }} className="w-5 h-5 flex items-center justify-center shrink-0">
            <span className="text-white text-[9px] font-black leading-none select-none">$</span>
          </div>
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 tracking-wide">Dólar Blue</span>
        </div>
        <button
          onClick={() => setCollapsed(true)}
          style={{ background: 'rgba(148,163,184,0.18)', borderRadius: '100px' }}
          className="w-5 h-5 flex items-center justify-center hover:bg-slate-400/30 transition-colors"
          aria-label="Minimizar"
        >
          <svg className="w-2.5 h-2.5 text-slate-500 dark:text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M18 12H6" />
          </svg>
        </button>
      </div>

      {/* Divider */}
      <div style={{ background: 'linear-gradient(90deg,transparent,rgba(148,163,184,0.30),transparent)', height: '1px', marginBottom: '12px' }} />

      {dolar ? (
        <>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[9px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-1">Compra</p>
              <p className="font-mono font-bold text-lg leading-none text-rose-500 dark:text-rose-400">
                ${dolar.compra.toLocaleString('es-AR')}
              </p>
            </div>
            <div style={{ background: 'linear-gradient(180deg,transparent,rgba(148,163,184,0.28),transparent)', width: '1px', height: '32px', marginTop: '14px' }} />
            <div>
              <p className="text-[9px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-1">Venta</p>
              <p className="font-mono font-bold text-lg leading-none text-emerald-600 dark:text-emerald-400">
                ${dolar.venta.toLocaleString('es-AR')}
              </p>
            </div>
          </div>

          {hora && (
            <>
              <div style={{ background: 'linear-gradient(90deg,transparent,rgba(148,163,184,0.30),transparent)', height: '1px', margin: '12px 0 8px' }} />
              <p className="text-[9px] text-slate-400 dark:text-slate-500 text-center tracking-wide">
                Actualizado {hora}
              </p>
            </>
          )}
        </>
      ) : (
        <div className="flex items-center justify-center gap-1.5 py-2">
          {[0, 150, 300].map((delay) => (
            <div key={delay} className="w-1 h-1 rounded-full bg-slate-400 animate-pulse" style={{ animationDelay: `${delay}ms` }} />
          ))}
        </div>
      )}
    </div>
  )
}
