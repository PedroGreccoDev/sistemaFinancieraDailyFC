import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getDeudasSimples, editarDeudaSimple } from '../api/deudas_simples'
import { getClientes } from '../api/clientes'
import { fmtARS, fmtUSD, fmtDate } from '../lib/fmt'
import { chip, btnSolid, btnBordered, btnFlat } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconPlus, IconRefresh } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import DropdownFilter from '../components/DropdownFilter'
import ModalNuevaDeudaSimple from '../components/ModalNuevaDeudaSimple'
import ModalPagarDeuda, { type DeudaItem } from '../components/ModalPagarDeuda'
import ModalEliminar from '../components/ModalEliminar'
import type { DeudaSimple, DeudaSimpleEstado, Moneda } from '../types'

type Filtro = 'todos' | DeudaSimpleEstado

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }
const MODAL_BG = 'var(--modal)'
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }
const TH: React.CSSProperties = { fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.8)', padding: '0.625rem 1rem', textAlign: 'left', background: 'var(--ov-0025)', borderBottom: '1px solid var(--bd-006)', whiteSpace: 'nowrap' }
const TD: React.CSSProperties = { fontFamily: FM, fontSize: '0.82rem', padding: '0.65rem 1rem', borderBottom: '1px solid var(--ov-004)', color: 'var(--text-1)' }

function fmtMoneda(monto: string | number, moneda: Moneda): string {
  return moneda === 'USD' ? fmtUSD(monto) : fmtARS(monto)
}

function EstadoBadge({ estado }: { estado: DeudaSimpleEstado }) {
  const abierta = estado === 'ABIERTA'
  return <span style={chip(abierta ? 'warning' : 'success')}>{abierta ? 'Abierta' : 'Cancelada'}</span>
}

// ── Modal editar ──────────────────────────────────────────────────────

function ModalEditarDeudaSimple({ deuda, onClose, onSuccess }: { deuda: DeudaSimple; onClose: () => void; onSuccess: () => void }) {
  const [concepto, setConcepto] = useState(deuda.concepto)
  const [monto, setMonto] = useState(deuda.monto)
  const [moneda, setMoneda] = useState<Moneda>(deuda.moneda)
  const [fecha, setFecha] = useState(deuda.fecha)
  const [observaciones, setObservaciones] = useState(deuda.observaciones ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  // Monto/moneda se bloquean si está cancelada o ya tuvo cobros parciales
  // (saldo distinto del monto original). Coincide con el backend.
  const tieneCobros = parseFloat(deuda.saldo_pendiente) !== parseFloat(deuda.monto)
  const dineroBloqueado = deuda.estado === 'CANCELADA' || tieneCobros

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await editarDeudaSimple(deuda.id, {
        concepto: concepto.trim(),
        fecha: fecha || null,
        observaciones: observaciones.trim() || null,
        ...(dineroBloqueado ? {} : { monto: parseFloat(monto), moneda }),
      })
      toast('success', 'Deuda actualizada')
      onSuccess()
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }

  return (
    <div className="modal-overlay" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.55)', padding: '1rem', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}>
      <div style={{ background: MODAL_BG, border: '1px solid var(--bd-008)', borderRadius: 'var(--r-lg)', width: '100%', maxWidth: '420px', maxHeight: '92dvh', overflowY: 'auto' }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--bd-006)', position: 'sticky', top: 0, background: MODAL_BG, zIndex: 10 }}>
          <h2 style={{ fontFamily: FN, fontSize: '1.5rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1 }}>Editar deuda</h2>
          <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.6)', marginTop: '0.2rem' }}>Corregir la carga de la deuda</p>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: '1.25rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div><label style={LABEL_STYLE}>Razón / concepto</label><input type="text" value={concepto} onChange={(e) => setConcepto(e.target.value)} required style={INPUT_STYLE} /></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div><label style={LABEL_STYLE}>Monto</label><input type="number" step="0.01" min="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} required disabled={dineroBloqueado} style={{ ...INPUT_STYLE, opacity: dineroBloqueado ? 0.5 : 1, cursor: dineroBloqueado ? 'not-allowed' : 'auto' }} /></div>
            <div><label style={LABEL_STYLE}>Moneda</label><select value={moneda} onChange={(e) => setMoneda(e.target.value as Moneda)} disabled={dineroBloqueado} style={{ ...INPUT_STYLE, cursor: dineroBloqueado ? 'not-allowed' : 'pointer', opacity: dineroBloqueado ? 0.5 : 1 }}><option value="ARS">ARS</option><option value="USD">USD</option></select></div>
          </div>
          {dineroBloqueado && <p style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(251,191,36,0.85)', marginTop: '-0.4rem' }}>Monto y moneda no se pueden cambiar: la deuda está cancelada o ya tiene cobros.</p>}
          <div><label style={LABEL_STYLE}>Fecha de la deuda</label><input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} style={INPUT_STYLE} /></div>
          <div><label style={LABEL_STYLE}>Observaciones <span style={{ fontWeight: 400, color: 'rgba(100,116,139,0.5)' }}>(opcional)</span></label><textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} style={{ ...INPUT_STYLE, resize: 'none' }} /></div>
          {error && <p style={{ fontFamily: FM, fontSize: '0.75rem', color: '#f87171' }}>{error}</p>}
          <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '0.25rem' }}>
            <button type="button" onClick={onClose} style={{ ...btnBordered('neutral'), flex: 1, padding: '0.55rem' }}>Cancelar</button>
            <button type="submit" disabled={loading} style={{ ...btnSolid('primary'), flex: 1, padding: '0.55rem', opacity: loading ? 0.6 : 1 }}>{loading ? 'Guardando…' : 'Guardar cambios'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function DeudoresOtras() {
  const [filtro, setFiltro] = useState<Filtro>('ABIERTA')
  const [creando, setCreando] = useState(false)
  const [cobrando, setCobrando] = useState<DeudaItem | null>(null)
  const [editando, setEditando] = useState<DeudaSimple | null>(null)
  const [eliminando, setEliminando] = useState<DeudaSimple | null>(null)
  const queryClient = useQueryClient()

  const estado = filtro === 'todos' ? undefined : (filtro as DeudaSimpleEstado)
  const { data: deudas, isLoading, error, refetch } = useQuery({
    queryKey: ['deudas-simples', filtro],
    queryFn: () => getDeudasSimples(estado),
    refetchInterval: 30_000,
  })
  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })
  const nombreDe = new Map(clientes?.map((c) => [c.id, c.nombre]) ?? [])

  const abiertas = deudas?.filter((d) => d.estado === 'ABIERTA') ?? []
  const totalARS = abiertas.filter((d) => d.moneda === 'ARS').reduce((acc, d) => acc + parseFloat(d.saldo_pendiente), 0)
  const totalUSD = abiertas.filter((d) => d.moneda === 'USD').reduce((acc, d) => acc + parseFloat(d.saldo_pendiente), 0)

  function invalidar() {
    queryClient.invalidateQueries({ queryKey: ['deudas-simples'] })
    // General consolida préstamos + fiados + estas deudas.
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
  }

  function handleSuccess() {
    setCreando(false); setCobrando(null); setEditando(null); setEliminando(null)
    invalidar()
    queryClient.invalidateQueries({ queryKey: ['clientes'] })
    // Una baja revierte líneas de caja: reporte y feed quedan desactualizados.
    queryClient.invalidateQueries({ queryKey: ['reporte-caja'] })
    queryClient.invalidateQueries({ queryKey: ['reporte'] })
    queryClient.invalidateQueries({ queryKey: ['movimientos-unificados'] })
  }

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Deudas libres de clientes (sin cuotas ni cheque), con su razón</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button onClick={() => setCreando(true)} style={{ ...btnSolid('primary'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', padding: '0.45rem 0.875rem' }}><IconPlus size={15} />Nueva</button>
          <button onClick={() => refetch()} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}><IconRefresh size={14} />Actualizar</button>
        </div>
      </div>

      {/* KPIs */}
      {filtro !== 'CANCELADA' && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
          {[
            { label: 'Saldo a cobrar ARS', value: fmtARS(totalARS), sub: `${abiertas.filter((d) => d.moneda === 'ARS').length} deuda(s)` },
            { label: 'Saldo a cobrar USD', value: fmtUSD(totalUSD), sub: `${abiertas.filter((d) => d.moneda === 'USD').length} deuda(s)` },
          ].map(({ label, value, sub }) => (
            <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
              <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
              <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color: '#fbbf24', letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
              <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{sub}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filtro */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '0.75rem', marginBottom: '1rem' }}>
        <DropdownFilter
          label="Estado"
          value={filtro}
          options={[
            { value: 'todos' as Filtro, label: 'Todas' },
            { value: 'ABIERTA' as Filtro, label: 'Abiertas' },
            { value: 'CANCELADA' as Filtro, label: 'Canceladas' },
          ]}
          onChange={(v) => setFiltro(v as Filtro)}
        />
      </div>

      {/* Lista */}
      <div style={{ ...CARD, overflow: 'hidden' }}>
        {isLoading && <SkeletonRows rows={6} />}
        {error && <div style={{ padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar las deudas.</div>}
        {deudas && deudas.length === 0 && (
          <div style={{ padding: '3rem', textAlign: 'center' }}>
            <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>✅</p>
            <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>Sin deudas registradas</p>
          </div>
        )}
        {deudas && deudas.length > 0 && (
          <>
            {/* Mobile: tarjetas */}
            <div className="sm:hidden">
              {deudas.map((d) => (
                <div key={`m-${d.id}`} style={{ padding: '0.85rem 1rem', borderBottom: '1px solid var(--ov-004)' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.4rem' }}>
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontFamily: FM, fontSize: '0.86rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word' }}>{nombreDe.get(d.cliente_id) ?? '—'}</p>
                      <p style={{ fontFamily: FM, fontSize: '0.72rem', color: 'rgba(148,163,184,0.7)', wordBreak: 'break-word', marginTop: '1px' }}>{d.concepto}</p>
                    </div>
                    <EstadoBadge estado={d.estado} />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '0.75rem' }}>
                    <span style={{ fontFamily: FM, fontSize: '0.7rem', color: 'rgba(100,116,139,0.6)' }}>
                      Original {fmtMoneda(d.monto, d.moneda)} · {fmtDate(d.fecha)}
                    </span>
                    <span style={{ fontFamily: FM, fontSize: '0.9rem', fontWeight: 700, color: '#fbbf24', whiteSpace: 'nowrap' }}>{fmtMoneda(d.saldo_pendiente, d.moneda)}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.65rem' }}>
                    {d.estado === 'ABIERTA' && (
                      <button onClick={() => setCobrando({ tipo: 'deuda_simple', id: d.id, clienteNombre: nombreDe.get(d.cliente_id) ?? '—', label: d.concepto, saldo: parseFloat(d.saldo_pendiente), moneda: d.moneda })} style={{ ...btnFlat('success'), flex: 1, fontSize: '0.72rem', padding: '0.4rem' }}>Cobrar</button>
                    )}
                    <button onClick={() => setEditando(d)} style={{ ...btnBordered('neutral'), flex: d.estado === 'ABIERTA' ? '0 0 auto' : 1, fontSize: '0.72rem', padding: '0.4rem 0.7rem' }}>Editar</button>
                    <button onClick={() => setEliminando(d)} style={{ ...btnBordered('danger'), flex: '0 0 auto', fontSize: '0.72rem', padding: '0.4rem 0.7rem' }}>Eliminar</button>
                  </div>
                </div>
              ))}
            </div>
            {/* Desktop: tabla */}
            <div className="hidden sm:block" style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '640px' }}>
                <thead>
                  <tr>
                    <th style={TH}>Cliente</th>
                    <th style={TH}>Razón</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Original</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Saldo</th>
                    <th style={TH}>Fecha</th>
                    <th style={TH}>Estado</th>
                    <th style={{ ...TH, padding: '0.625rem 1rem' }} />
                  </tr>
                </thead>
                <tbody>
                  {deudas.map((d) => (
                    <tr key={d.id}
                      onMouseEnter={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'var(--ov-002)'}
                      onMouseLeave={(e) => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}>
                      <td style={{ ...TD, fontWeight: 600 }}>{nombreDe.get(d.cliente_id) ?? '—'}</td>
                      <td style={{ ...TD, color: 'rgba(148,163,184,0.7)', maxWidth: '220px', whiteSpace: 'normal', wordBreak: 'break-word' }}>{d.concepto}</td>
                      <td style={{ ...TD, textAlign: 'right', color: 'rgba(100,116,139,0.6)' }}>{fmtMoneda(d.monto, d.moneda)}</td>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#fbbf24' }}>{fmtMoneda(d.saldo_pendiente, d.moneda)}</td>
                      <td style={{ ...TD, color: 'rgba(100,116,139,0.6)', fontSize: '0.72rem', whiteSpace: 'nowrap' }}>{fmtDate(d.fecha)}</td>
                      <td style={TD}><EstadoBadge estado={d.estado} /></td>
                      <td style={{ ...TD, textAlign: 'right' }}>
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                          {d.estado === 'ABIERTA' && (
                            <button onClick={() => setCobrando({ tipo: 'deuda_simple', id: d.id, clienteNombre: nombreDe.get(d.cliente_id) ?? '—', label: d.concepto, saldo: parseFloat(d.saldo_pendiente), moneda: d.moneda })} style={{ ...btnFlat('success'), fontSize: '0.68rem', padding: '2px 8px' }}>Cobrar</button>
                          )}
                          <button onClick={() => setEditando(d)} style={{ ...btnBordered('neutral'), fontSize: '0.68rem', padding: '2px 8px' }}>Editar</button>
                          <button onClick={() => setEliminando(d)} style={{ ...btnBordered('danger'), fontSize: '0.68rem', padding: '2px 8px' }}>Eliminar</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {creando && <ModalNuevaDeudaSimple onClose={() => setCreando(false)} onSuccess={handleSuccess} />}
      {cobrando && <ModalPagarDeuda deuda={cobrando} onClose={() => setCobrando(null)} onSuccess={handleSuccess} />}
      {editando && <ModalEditarDeudaSimple deuda={editando} onClose={() => setEditando(null)} onSuccess={handleSuccess} />}
      {eliminando && <ModalEliminar entidad="deuda_simple" id={eliminando.id} onClose={() => setEliminando(null)} onSuccess={handleSuccess} />}
    </div>
  )
}
