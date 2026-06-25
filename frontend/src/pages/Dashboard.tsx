import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getChequeCartera } from '../api/cheques'
import { getFiados } from '../api/fiados'
import { getPrestamos } from '../api/prestamos'
import { getClientes } from '../api/clientes'
import { getReporteCaja } from '../api/reportes'
import { fmtARS, fmtMonto, fmtDate, daysUntil, monthStartISO, todayISO } from '../lib/fmt'
import type { Cheque, Prestamo } from '../types'
import { FinanceDashboardCard } from '../components/FinanceDashboardCard'
import { SkeletonKpis, Skeleton } from '../components/Skeleton'

// ── helpers ───────────────────────────────────────────────────────────

function cuotasVencidas(prestamos: Prestamo[]) {
  return prestamos
    .filter((p) => p.estado === 'ACTIVO')
    .flatMap((p) =>
      p.cuotas_detalle
        .filter((c) => c.estado !== 'COBRADA' && daysUntil(c.fecha_vencimiento) < 0)
        .map((c) => ({ ...c, prestamo_id: p.id, cliente_id: p.cliente_id, moneda: p.moneda }))
    )
    .sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento))
}

function chequesPorVencer(cheques: Cheque[], dias: number) {
  return cheques
    .filter((c) => {
      if (!c.fecha_pago) return false
      const d = daysUntil(c.fecha_pago)
      return d >= 0 && d <= dias
    })
    .sort((a, b) => (a.fecha_pago ?? '').localeCompare(b.fecha_pago ?? ''))
}

// ── design tokens ─────────────────────────────────────────────────────

const CARD_BG = "var(--surface-grad)"
const CARD_BORDER = "1px solid var(--bd-006)"
const CARD_SHADOW = "var(--shadow-card), inset 0 1px 0 var(--ov-004)"
const DIVIDER = "1px solid var(--ov-005)"
const TEXT_PRIMARY = "var(--text-1)"
const TEXT_MUTED = "rgba(148,163,184,0.6)"
const TEXT_FAINT = "rgba(100,116,139,0.7)"
const FONT_UI = "'Manrope', sans-serif"
const FONT_NUM = "'Bebas Neue', sans-serif"

// ── sub-componentes ───────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p style={{
      fontFamily: FONT_UI,
      fontSize: "0.65rem",
      fontWeight: 700,
      letterSpacing: "0.18em",
      textTransform: "uppercase" as const,
      color: "rgba(100,116,139,0.8)",
      marginBottom: "0.75rem",
    }}>
      {children}
    </p>
  )
}

interface AlertCardProps {
  dot: string
  label: string
  count?: number
  children: React.ReactNode
}

function AlertCard({ dot, label, count, children }: AlertCardProps) {
  return (
    <div style={{
      background: CARD_BG,
      border: CARD_BORDER,
      boxShadow: CARD_SHADOW,
      borderRadius: "var(--r-lg)",
      overflow: "hidden",
      marginBottom: "0.875rem",
    }}>
      <div style={{
        padding: "0.75rem 1.1rem",
        borderBottom: DIVIDER,
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
      }}>
        <span style={{
          width: "6px",
          height: "6px",
          borderRadius: "50%",
          background: dot,
          boxShadow: `0 0 3px ${dot}80`,
          flexShrink: 0,
        }} />
        <span style={{
          fontFamily: FONT_UI,
          fontSize: "0.8rem",
          fontWeight: 600,
          letterSpacing: "0.01em",
          color: TEXT_PRIMARY,
        }}>
          {label}
        </span>
        {count !== undefined && count > 0 && (
          <span style={{
            marginLeft: "auto",
            fontFamily: FONT_NUM,
            fontSize: "0.9rem",
            letterSpacing: "0.05em",
            color: dot,
            background: `${dot}18`,
            padding: "0 0.5rem",
            lineHeight: "1.5rem",
          }}>
            {count}
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

function RowItem({
  primary, secondary, value, valueColor, onClick,
}: { primary: string; secondary: string; value: string; valueColor?: string; onClick?: () => void }) {
  return (
    <div
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}
      onMouseEnter={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.background = "var(--ov-004)" } : undefined}
      onMouseLeave={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent" } : undefined}
      style={{
      padding: "0.7rem 1.1rem",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: "0.75rem",
      borderBottom: DIVIDER,
      cursor: onClick ? "pointer" : undefined,
      transition: "background 0.15s ease",
    }}>
      <div style={{ minWidth: 0 }}>
        <p style={{
          fontFamily: FONT_UI,
          fontSize: "0.84rem",
          fontWeight: 600,
          color: TEXT_PRIMARY,
          wordBreak: "break-word" as const,
        }}>
          {primary}
        </p>
        <p style={{
          fontFamily: FONT_UI,
          fontSize: "0.72rem",
          fontWeight: 500,
          color: TEXT_MUTED,
          marginTop: "2px",
        }}>
          {secondary}
        </p>
      </div>
      <span style={{
        fontFamily: FONT_NUM,
        fontSize: "1.2rem",
        letterSpacing: "0.03em",
        color: valueColor ?? TEXT_PRIMARY,
        flexShrink: 0,
      }}>
        {value}
      </span>
    </div>
  )
}

function LoadingRows({ rows = 2 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', padding: '0.7rem 1.1rem', borderBottom: '1px solid var(--ov-004)' }}>
          <div style={{ flex: 1 }}>
            <Skeleton w={`${50 + i * 12}%`} h={12} />
            <Skeleton w="30%" h={8} style={{ marginTop: '0.45rem' }} />
          </div>
          <Skeleton w={70} h={14} />
        </div>
      ))}
    </div>
  )
}

function EmptyRow({ text }: { text: string }) {
  return (
    <div style={{
      padding: "0.875rem 1rem",
      fontFamily: FONT_UI,
      fontSize: "0.72rem",
      fontWeight: 500,
      color: TEXT_FAINT,
    }}>
      {text}
    </div>
  )
}

// ── página ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const navigate = useNavigate()
  const { data: cheques }   = useQuery({ queryKey: ['cartera'],             queryFn: getChequeCartera,              refetchInterval: 30_000 })
  const { data: prestamos } = useQuery({ queryKey: ['prestamos'],           queryFn: () => getPrestamos(),          refetchInterval: 30_000 })
  const { data: clientes }  = useQuery({ queryKey: ['clientes'],            queryFn: getClientes,                   staleTime: 60_000 })
  const { data: fiados }    = useQuery({ queryKey: ['fiados', 'ABIERTO'],   queryFn: () => getFiados('ABIERTO'),    refetchInterval: 30_000 })
  const { data: reporte }   = useQuery({
    queryKey: ['reporte', monthStartISO(), todayISO()],
    queryFn: () => getReporteCaja(monthStartISO(), todayISO()),
  })

  const clienteMap       = new Map(clientes?.map((c) => [c.id, c.nombre]) ?? [])
  const totalCartera     = (cheques  ?? []).reduce((s, c) => s + parseFloat(c.monto), 0)
  const prestamosActivos = (prestamos ?? []).filter((p) => p.estado === 'ACTIVO')
  const capitalEnCalle   = prestamosActivos.reduce((s, p) => s + parseFloat(p.credito), 0)
  const vencidas         = cuotasVencidas(prestamos ?? [])
  const proximos         = chequesPorVencer(cheques ?? [], 7)

  const actividad = [
    ...(cheques  ?? []).map((c) => ({ tipo: 'cheque'   as const, id: c.id,          label: `Cheque ${c.nro_cheque}`,                           sub: fmtARS(c.monto),              date: c.created_at })),
    ...(prestamos ?? []).map((p) => ({ tipo: 'prestamo' as const, id: p.id,          label: `Préstamo — ${clienteMap.get(p.cliente_id) ?? '…'}`, sub: fmtMonto(p.credito, p.moneda), date: p.created_at })),
  ]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 5)

  const fecha = new Date().toLocaleDateString('es-AR', { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ fontFamily: FONT_UI }}>

      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <h1 style={{
          fontFamily: FONT_NUM,
          fontSize: "2.2rem",
          letterSpacing: "0.06em",
          color: "var(--text-1)",
          lineHeight: 1,
          marginBottom: "0.25rem",
        }}>
          RESUMEN
        </h1>
        <p style={{
          fontFamily: FONT_UI,
          fontSize: "0.78rem",
          fontWeight: 500,
          color: "rgba(100,116,139,0.9)",
          textTransform: "capitalize" as const,
        }}>
          {fecha}
        </p>
      </div>

      {/* KPI cards */}
      {!cheques && !prestamos && !reporte ? <SkeletonKpis /> : (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" style={{ marginBottom: "1.75rem" }}>
        <FinanceDashboardCard
          title="Cheques en cartera"
          value={cheques?.length ?? 0}
          subtitle={cheques ? fmtARS(totalCartera) : undefined}
          accentColor="#f59e0b"
          onClick={() => navigate('/cartera')}
        />
        <FinanceDashboardCard
          title="Capital en calle"
          value={capitalEnCalle}
          prefix="$"
          subtitle={`${prestamosActivos.length} préstamo${prestamosActivos.length !== 1 ? 's' : ''} activo${prestamosActivos.length !== 1 ? 's' : ''}`}
          accentColor="#6366f1"
          formatValue={(v) => v.toLocaleString('es-AR', { maximumFractionDigits: 0 })}
          onClick={() => navigate('/deudores')}
        />
        <FinanceDashboardCard
          title="Cuotas vencidas"
          value={vencidas.length}
          subtitle={vencidas.length > 0 ? 'Requieren atención' : 'Todo al día'}
          accentColor={vencidas.length > 0 ? '#ef4444' : '#22c55e'}
          onClick={() => navigate('/deudores')}
        />
        <FinanceDashboardCard
          title="Neto del mes (ARS)"
          value={Number(reporte?.ars?.neto ?? 0)}
          prefix="$"
          subtitle="Caja en pesos"
          accentColor="#10b981"
          formatValue={(v) => v.toLocaleString('es-AR', { maximumFractionDigits: 0 })}
          onClick={() => navigate('/reportes')}
        />
      </div>
      )}

      {/* Lower grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Alertas */}
        <div>
          <SectionLabel>Alertas urgentes</SectionLabel>

          {/* Cuotas vencidas */}
          <AlertCard dot="#ef4444" label="Cuotas vencidas" count={vencidas.length}>
            {vencidas.length === 0 && !prestamos && <LoadingRows />}
            {vencidas.length === 0 && prestamos  && <EmptyRow text="Sin cuotas vencidas" />}
            {vencidas.slice(0, 4).map((c) => (
              <RowItem
                key={c.id}
                primary={clienteMap.get(c.cliente_id) ?? '…'}
                secondary={`Venció ${fmtDate(c.fecha_vencimiento)} · hace ${Math.abs(daysUntil(c.fecha_vencimiento))}d`}
                value={fmtMonto(c.monto, c.moneda)}
                valueColor="#f87171"
                onClick={() => navigate('/deudores')}
              />
            ))}
            {vencidas.length > 4 && (
              <div style={{ padding: "0.4rem 1rem", fontFamily: FONT_UI, fontSize: "0.65rem", fontWeight: 500, color: TEXT_FAINT, textAlign: "center" as const }}>
                +{vencidas.length - 4} más en Deudores
              </div>
            )}
          </AlertCard>

          {/* Fiados abiertos */}
          {((fiados && fiados.length > 0) || !fiados) && (
            <AlertCard dot="#f59e0b" label="Fiados abiertos" count={fiados?.length}>
              {!fiados && <LoadingRows />}
              {fiados?.slice(0, 4).map((f) => (
                <RowItem
                  key={f.id}
                  primary={clienteMap.get(f.cliente_id) ?? '…'}
                  secondary={f.cheque_nro}
                  value={fmtARS(f.saldo_pendiente)}
                  valueColor="#fbbf24"
                  onClick={() => navigate('/deudores/cheques-fiados')}
                />
              ))}
              {fiados && fiados.length > 4 && (
                <div style={{ padding: "0.4rem 1rem", fontFamily: FONT_UI, fontSize: "0.65rem", fontWeight: 500, color: TEXT_FAINT, textAlign: "center" as const }}>
                  +{fiados.length - 4} más en Fiados
                </div>
              )}
            </AlertCard>
          )}

          {/* Cheques próximos a vencer */}
          <AlertCard dot="#facc15" label="Cheques vencen en 7 días" count={proximos.length}>
            {proximos.length === 0 && !cheques  && <LoadingRows />}
            {proximos.length === 0 && cheques   && <EmptyRow text="Sin cheques por vencer" />}
            {proximos.slice(0, 4).map((c) => {
              const dias = daysUntil(c.fecha_pago!)
              return (
                <RowItem
                  key={c.id}
                  primary={c.nro_cheque}
                  secondary={dias === 0 ? 'Vence hoy' : `Vence en ${dias}d · ${fmtDate(c.fecha_pago)}`}
                  value={fmtARS(c.monto)}
                  valueColor="#fde047"
                  onClick={() => navigate('/cartera')}
                />
              )
            })}
          </AlertCard>
        </div>

        {/* Actividad reciente */}
        <div>
          <SectionLabel>Actividad reciente</SectionLabel>
          <div style={{
            background: CARD_BG,
            border: CARD_BORDER,
            boxShadow: CARD_SHADOW,
            borderRadius: "var(--r-lg)",
            overflow: "hidden",
          }}>
            {actividad.length === 0 && (
              !cheques && !prestamos ? <LoadingRows /> : <EmptyRow text="Sin actividad registrada" />
            )}
            {actividad.map((item) => (
              <div
                key={item.id}
                role="button"
                tabIndex={0}
                onClick={() => navigate(item.tipo === 'cheque' ? '/cartera' : '/deudores')}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate(item.tipo === 'cheque' ? '/cartera' : '/deudores') } }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = "var(--ov-004)" }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent" }}
                style={{
                padding: "0.625rem 1rem",
                display: "flex",
                alignItems: "center",
                gap: "0.75rem",
                borderBottom: DIVIDER,
                cursor: "pointer",
                transition: "background 0.15s ease",
              }}>
                <div style={{
                  width: "2rem",
                  height: "2rem",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  background: item.tipo === 'cheque' ? "rgba(99,102,241,0.12)" : "rgba(168,85,247,0.12)",
                }}>
                  <span style={{
                    fontFamily: FONT_NUM,
                    fontSize: "0.8rem",
                    letterSpacing: "0.04em",
                    color: item.tipo === 'cheque' ? "#818cf8" : "#c084fc",
                  }}>
                    {item.tipo === 'cheque' ? 'CH' : 'PR'}
                  </span>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{
                    fontFamily: FONT_UI,
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    color: TEXT_PRIMARY,
                    wordBreak: "break-word" as const,
                  }}>
                    {item.label}
                  </p>
                  <p style={{
                    fontFamily: FONT_UI,
                    fontSize: "0.65rem",
                    fontWeight: 500,
                    color: TEXT_MUTED,
                    marginTop: "1px",
                  }}>
                    {item.sub}
                  </p>
                </div>
                <span style={{
                  fontFamily: FONT_UI,
                  fontSize: "0.65rem",
                  fontWeight: 500,
                  color: TEXT_FAINT,
                  flexShrink: 0,
                }}>
                  {fmtDate(item.date.slice(0, 10))}
                </span>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  )
}
