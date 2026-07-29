import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPrestamos } from '../api/prestamos'
import { getFiados } from '../api/fiados'
import { getDeudasSimples } from '../api/deudas_simples'
import { getClientes } from '../api/clientes'
import { fmtARS, fmtUSD } from '../lib/fmt'
import { chip, btnSolid, btnBordered, btnFlat } from '../lib/ui'
import { IconPlus, IconRefresh } from '../components/icons'
import { SkeletonRows } from '../components/Skeleton'
import ModalPagarDeuda, { type DeudaItem } from '../components/ModalPagarDeuda'
import ModalNuevaDeudaSimple from '../components/ModalNuevaDeudaSimple'
import type { Moneda, Prestamo, Fiado, DeudaSimple, Cliente } from '../types'

const FM = "'Manrope', sans-serif"
const FN = "'Bebas Neue', sans-serif"
const CARD = { background: 'var(--surface-grad)', border: '1px solid var(--bd-006)', boxShadow: 'var(--shadow-card)', borderRadius: 'var(--r-lg)' }

function fmtMoneda(monto: string | number, moneda: Moneda): string {
  return moneda === 'USD' ? fmtUSD(monto) : fmtARS(monto)
}

// ── Modelo consolidado por cliente ────────────────────────────────────

interface DeudorResumen {
  clienteId: string
  nombre: string
  totalArs: number
  totalUsd: number
  deudas: DeudaItem[]
}

// Saldo pendiente de un préstamo = suma del saldo (monto − monto_pagado) de sus
// cuotas no cobradas, en la moneda del préstamo.
function saldoPrestamo(p: Prestamo): number {
  return p.cuotas_detalle
    .filter((c) => c.estado !== 'COBRADA')
    .reduce((acc, c) => acc + (parseFloat(c.monto) - parseFloat(c.monto_pagado || '0')), 0)
}

function construirResumen(
  prestamos: Prestamo[],
  fiados: Fiado[],
  deudasSimples: DeudaSimple[],
  clientes: Cliente[],
): DeudorResumen[] {
  const nombreDe = new Map(clientes.map((c) => [c.id, c.nombre]))
  const map = new Map<string, DeudorResumen>()

  const bucket = (clienteId: string): DeudorResumen => {
    let r = map.get(clienteId)
    if (!r) {
      r = { clienteId, nombre: nombreDe.get(clienteId) ?? '—', totalArs: 0, totalUsd: 0, deudas: [] }
      map.set(clienteId, r)
    }
    return r
  }

  for (const p of prestamos) {
    if (p.estado === 'CANCELADO') continue // ACTIVO o EN_MORA con saldo siguen contando
    const saldo = saldoPrestamo(p)
    if (saldo <= 0.009) continue
    const r = bucket(p.cliente_id)
    const pendientes = p.cuotas_detalle.filter((c) => c.estado !== 'COBRADA').length
    r.deudas.push({
      tipo: 'prestamo',
      id: p.id,
      clienteNombre: r.nombre,
      label: `Préstamo · ${pendientes}/${p.cuotas} cuota${p.cuotas > 1 ? 's' : ''} pend.`,
      saldo,
      moneda: p.moneda,
    })
    if (p.moneda === 'USD') r.totalUsd += saldo
    else r.totalArs += saldo
  }

  for (const f of fiados) {
    if (f.estado !== 'ABIERTO') continue
    const saldo = parseFloat(f.saldo_pendiente)
    if (saldo <= 0.009) continue
    const r = bucket(f.cliente_id)
    r.deudas.push({
      tipo: 'fiado',
      id: f.id,
      clienteNombre: r.nombre,
      label: `Cheque fiado · Nº ${f.cheque_nro}`,
      saldo,
      moneda: 'ARS', // los cheques (y por ende los fiados) son siempre en pesos
    })
    r.totalArs += saldo
  }

  for (const d of deudasSimples) {
    if (d.estado !== 'ABIERTA') continue
    const saldo = parseFloat(d.saldo_pendiente)
    if (saldo <= 0.009) continue
    const r = bucket(d.cliente_id)
    r.deudas.push({
      tipo: 'deuda_simple',
      id: d.id,
      clienteNombre: r.nombre,
      label: d.concepto,
      saldo,
      moneda: d.moneda,
    })
    if (d.moneda === 'USD') r.totalUsd += saldo
    else r.totalArs += saldo
  }

  return [...map.values()].sort((a, b) => a.nombre.localeCompare(b.nombre))
}

// ── Tarjeta de un deudor ──────────────────────────────────────────────

function DeudorCard({ deudor, onPagar }: { deudor: DeudorResumen; onPagar: (d: DeudaItem) => void }) {
  return (
    <div className="lift" style={{ ...CARD, padding: '1rem 1.15rem' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
        <h3 style={{ fontFamily: FM, fontSize: '0.92rem', fontWeight: 700, color: 'var(--text-1)', wordBreak: 'break-word' }}>{deudor.nombre}</h3>
        <div style={{ display: 'flex', gap: '1.25rem', textAlign: 'right' }}>
          {deudor.totalArs > 0.009 && (
            <div>
              <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>Total ARS</p>
              <p style={{ fontFamily: FN, fontSize: '1.2rem', color: '#fbbf24', lineHeight: 1.1, overflowWrap: 'anywhere' }}>{fmtARS(deudor.totalArs)}</p>
            </div>
          )}
          {deudor.totalUsd > 0.009 && (
            <div>
              <p style={{ fontFamily: FM, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.6)' }}>Total USD</p>
              <p style={{ fontFamily: FN, fontSize: '1.2rem', color: '#38bdf8', lineHeight: 1.1, overflowWrap: 'anywhere' }}>{fmtUSD(deudor.totalUsd)}</p>
            </div>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--bd-006)' }}>
        {deudor.deudas.map((d) => (
          <div key={`${d.tipo}-${d.id}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.6rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
              <span style={chip(d.tipo === 'prestamo' ? 'primary' : d.tipo === 'deuda_simple' ? 'warning' : 'secondary')}>{d.tipo === 'prestamo' ? 'Préstamo' : d.tipo === 'deuda_simple' ? 'Deuda' : 'Fiado'}</span>
              <span style={{ fontFamily: FM, fontSize: '0.76rem', color: 'rgba(100,116,139,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.label}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexShrink: 0 }}>
              <span style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-1)', whiteSpace: 'nowrap' }}>{fmtMoneda(d.saldo, d.moneda)}</span>
              <button onClick={() => onPagar(d)} style={{ ...btnFlat('success'), fontSize: '0.7rem', padding: '0.3rem 0.7rem' }}>Pagar</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function DeudoresGeneral() {
  const [pagando, setPagando] = useState<DeudaItem | null>(null)
  const [creando, setCreando] = useState(false)
  const queryClient = useQueryClient()

  const { data: prestamos, isLoading: loadingP, error: errP } = useQuery({
    queryKey: ['prestamos'],
    queryFn: () => getPrestamos(),
    refetchInterval: 30_000,
  })
  const { data: fiados, isLoading: loadingF, error: errF } = useQuery({
    queryKey: ['fiados', 'ABIERTO'],
    queryFn: () => getFiados('ABIERTO'),
    refetchInterval: 30_000,
  })
  const { data: deudasSimples, isLoading: loadingD, error: errD } = useQuery({
    queryKey: ['deudas-simples', 'ABIERTA'],
    queryFn: () => getDeudasSimples('ABIERTA'),
    refetchInterval: 30_000,
  })
  const { data: clientes } = useQuery({ queryKey: ['clientes'], queryFn: getClientes, staleTime: 60_000 })

  const isLoading = loadingP || loadingF || loadingD
  const error = errP || errF || errD
  const resumen = construirResumen(prestamos ?? [], fiados ?? [], deudasSimples ?? [], clientes ?? [])

  const totalArs = resumen.reduce((acc, r) => acc + r.totalArs, 0)
  const totalUsd = resumen.reduce((acc, r) => acc + r.totalUsd, 0)

  function invalidar() {
    queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
    queryClient.invalidateQueries({ queryKey: ['deudas-simples'] })
  }

  function handleSuccess() {
    setPagando(null)
    invalidar()
  }

  function handleCreada() {
    setCreando(false)
    invalidar()
    queryClient.invalidateQueries({ queryKey: ['clientes'] })
  }

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FM }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h1 style={{ fontFamily: FN, fontSize: '2rem', letterSpacing: '0.06em', color: 'var(--text-1)', lineHeight: 1, marginBottom: '0.2rem' }}>General</h1>
          <p style={{ fontFamily: FM, fontSize: '0.78rem', fontWeight: 500, color: 'rgba(100,116,139,0.8)' }}>Deuda consolidada de cada cliente (préstamos + cheques fiados)</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button onClick={() => setCreando(true)} style={{ ...btnSolid('primary'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', padding: '0.45rem 0.875rem' }}><IconPlus size={15} />Nuevo</button>
          <button onClick={invalidar} style={{ ...btnBordered('neutral'), display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.875rem' }}><IconRefresh size={14} />Actualizar</button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 sm:max-w-xl" style={{ marginBottom: '1.25rem' }}>
        {[
          { label: 'Total a cobrar ARS', value: fmtARS(totalArs), color: '#fbbf24' },
          { label: 'Total a cobrar USD', value: fmtUSD(totalUsd), color: '#38bdf8' },
        ].map(({ label, value, color }) => (
          <div key={label} className="lift" style={{ ...CARD, padding: '0.8rem 1rem' }}>
            <p style={{ fontFamily: FM, fontSize: '0.63rem', fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }}>{label}</p>
            <p style={{ fontFamily: FN, fontSize: 'clamp(1.15rem, 6vw, 1.75rem)', color, letterSpacing: '0.02em', lineHeight: 1.05, marginBottom: '0.2rem', overflowWrap: 'anywhere' }}>{value}</p>
            <p style={{ fontFamily: FM, fontSize: '0.65rem', color: 'rgba(100,116,139,0.5)' }}>{resumen.length} deudor(es)</p>
          </div>
        ))}
      </div>

      {/* Lista */}
      {isLoading && <div style={{ ...CARD, overflow: 'hidden' }}><SkeletonRows rows={6} /></div>}
      {error && <div style={{ ...CARD, padding: '3rem', textAlign: 'center', color: '#f87171', fontFamily: FM, fontSize: '0.82rem' }}>Error al cargar los deudores.</div>}
      {!isLoading && !error && resumen.length === 0 && (
        <div style={{ ...CARD, padding: '3rem', textAlign: 'center' }}>
          <p style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>✅</p>
          <p style={{ fontFamily: FM, fontSize: '0.82rem', fontWeight: 600, color: 'rgba(100,116,139,0.6)' }}>Ningún cliente tiene deuda pendiente</p>
        </div>
      )}
      {!isLoading && !error && resumen.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {resumen.map((d) => <DeudorCard key={d.clienteId} deudor={d} onPagar={setPagando} />)}
        </div>
      )}

      {pagando && <ModalPagarDeuda deuda={pagando} onClose={() => setPagando(null)} onSuccess={handleSuccess} />}
      {creando && <ModalNuevaDeudaSimple onClose={() => setCreando(false)} onSuccess={handleCreada} />}
    </div>
  )
}
