import { useEffect, useState } from 'react'
import { chequeFotoUrl } from '../api/cheques'
import { btnBordered, btnFlat } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconClose, IconDownload, IconShare } from './icons'
import type { Cheque } from '../types'

const FN = "'Bebas Neue', sans-serif"
const FM = "'Manrope', sans-serif"
const MODAL_BG = 'var(--modal)'

function extFromMime(mime: string): string {
  if (mime.includes('png')) return 'png'
  if (mime.includes('webp')) return 'webp'
  if (mime.includes('gif')) return 'gif'
  return 'jpg'
}

export default function ChequeFotoModal({ cheque, onClose }: { cheque: Cheque; onClose: () => void }) {
  const push = useToast()
  const [blob, setBlob] = useState<Blob | null>(null)
  const [objUrl, setObjUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)

  // Cierre con tecla Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Descarga la foto una sola vez; el blob se reutiliza para <img>, descargar y compartir.
  useEffect(() => {
    let revoked: string | null = null
    let cancelled = false
    fetch(chequeFotoUrl(cheque.id))
      .then((r) => { if (!r.ok) throw new Error('fetch'); return r.blob() })
      .then((b) => {
        if (cancelled) return
        const url = URL.createObjectURL(b)
        revoked = url
        setBlob(b)
        setObjUrl(url)
      })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true; if (revoked) URL.revokeObjectURL(revoked) }
  }, [cheque.id])

  const filename = `cheque-${cheque.nro_cheque}.${blob ? extFromMime(blob.type) : 'jpg'}`

  function descargar() {
    if (!objUrl) return
    const a = document.createElement('a')
    a.href = objUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  async function compartir() {
    if (!blob) return
    const file = new File([blob], filename, { type: blob.type })
    try {
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: `Cheque ${cheque.nro_cheque}` })
      } else {
        descargar()
        push('info', 'Compartir no está disponible acá; se descargó la foto.')
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') push('error', 'No se pudo compartir la foto.')
    }
  }

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '860px', maxHeight: '94dvh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
      >
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--bd-006)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
          <div style={{ minWidth: 0 }}>
            <h2 style={{ fontFamily: FN, fontSize: '1.4rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Foto del cheque</h2>
            <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '0.74rem', color: 'rgba(100,116,139,0.7)', marginTop: '0.25rem', wordBreak: 'break-word' }}>Nº {cheque.nro_cheque}</p>
          </div>
          <button onClick={onClose} aria-label="Cerrar" style={{ ...btnBordered('neutral'), padding: '0.35rem', display: 'flex', flexShrink: 0 }}>
            <IconClose size={16} />
          </button>
        </div>

        <div style={{ flex: 1, minHeight: '260px', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem', background: 'var(--ov-0025)', overflow: 'auto' }}>
          {error ? (
            <p style={{ fontFamily: FM, fontSize: '0.82rem', color: '#f87171' }}>No se pudo cargar la foto.</p>
          ) : !objUrl ? (
            <p style={{ fontFamily: FM, fontSize: '0.82rem', color: 'rgba(100,116,139,0.6)' }}>Cargando foto…</p>
          ) : (
            <img src={objUrl} alt={`Cheque ${cheque.nro_cheque}`} style={{ maxWidth: '100%', maxHeight: '78dvh', objectFit: 'contain', borderRadius: 'var(--r-md)' }} />
          )}
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', padding: '1rem 1.25rem', borderTop: '1px solid var(--bd-006)' }}>
          <button onClick={descargar} disabled={!objUrl} style={{ ...btnBordered('neutral'), flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.45rem', padding: '0.6rem', opacity: objUrl ? 1 : 0.5 }}>
            <IconDownload size={16} />Descargar
          </button>
          <button onClick={compartir} disabled={!blob} style={{ ...btnFlat('primary'), flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.45rem', padding: '0.6rem', opacity: blob ? 1 : 0.5 }}>
            <IconShare size={16} />Compartir
          </button>
        </div>
      </div>
    </div>
  )
}
