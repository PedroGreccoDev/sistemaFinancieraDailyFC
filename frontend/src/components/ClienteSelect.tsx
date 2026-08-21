import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { createCliente } from '../api/clientes'
import { btnBordered, btnSolid } from '../lib/ui'
import type { Cliente } from '../types'

// Selector de cliente con alta inline: el operador carga una operación y se
// encuentra con que el cliente todavía no existe. Mandarlo a otra pantalla a
// crearlo le hace perder lo que venía tipeando.
//
// Vive acá y no en una página porque lo usan las dos compras —el alta de cheque
// (Cartera) y la de divisas (Movimientos)— y en ambas, cuando la compra queda a
// deber, elegir el vendedor deja de ser opcional: es a quien se le debe.

const FM = "'Manrope', sans-serif"
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }

export default function ClienteSelect({
  label,
  value,
  onChange,
  clientes,
  placeholder = '— Sin asignar —',
}: {
  label: string
  value: string
  onChange: (id: string) => void
  clientes: Cliente[]
  placeholder?: string
}) {
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [nombre, setNombre] = useState('')
  const [tel, setTel] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function crear() {
    if (!nombre.trim()) return
    setBusy(true); setErr(null)
    try {
      const nuevo = await createCliente({ nombre: nombre.trim(), telefono: tel.trim() || null })
      qc.setQueryData<Cliente[]>(['clientes'], (prev) => [...(prev ?? []), nuevo])
      onChange(nuevo.id); setCreating(false); setNombre(''); setTel('')
    } catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <div>
      <label style={LABEL_STYLE}>{label}</label>
      {!creating ? (
        <>
          <select value={value} onChange={(e) => onChange(e.target.value)} style={{ ...INPUT_STYLE, cursor: 'pointer' }}>
            <option value="">{placeholder}</option>
            {clientes.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
          <button type="button" onClick={() => setCreating(true)} style={{ fontFamily: FM, fontSize: '0.7rem', color: 'var(--primary)', background: 'transparent', border: 'none', cursor: 'pointer', marginTop: '0.35rem', padding: 0 }}>+ Agregar cliente nuevo</button>
        </>
      ) : (
        <div style={{ border: '1px solid var(--bd-008)', borderRadius: 'var(--r-md)', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem', background: 'var(--ov-002)' }}>
          <input type="text" value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Nombre *" autoFocus style={INPUT_STYLE} />
          <input type="text" value={tel} onChange={(e) => setTel(e.target.value)} placeholder="Teléfono (opcional)" style={INPUT_STYLE} />
          {err && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: '#f87171' }}>{err}</p>}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button type="button" onClick={() => { setCreating(false); setErr(null) }} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.4rem', fontSize: '0.72rem' }}>Volver</button>
            <button type="button" onClick={crear} disabled={busy || !nombre.trim()} style={{ ...btnSolid('primary'), flex: 1, padding: '0.4rem', fontSize: '0.72rem', opacity: (busy || !nombre.trim()) ? 0.5 : 1 }}>{busy ? 'Creando…' : 'Crear'}</button>
          </div>
        </div>
      )}
    </div>
  )
}
