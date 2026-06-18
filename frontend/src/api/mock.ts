/**
 * Datos falsos para desarrollo local del frontend (modo demo).
 *
 * Se activa con `VITE_MOCK=1` (ver script `npm run dev:mock`). Cuando está activo,
 * `apiFetch` enruta acá en vez de pegarle al backend → no hace falta Postgres ni la API.
 * Las fechas se generan relativas a "hoy" para que siempre se vean actuales.
 */
import type {
  Cheque, Cliente, Cuota, Fiado, GastoOperativo,
  MovimientoEfectivo, Pasivo, Prestamo, ReporteGanancias,
} from '../types'

const DAY = 86_400_000
const NOW = Date.now()
/** Fecha YYYY-MM-DD desplazada `off` días respecto de hoy. */
const d = (off: number) => new Date(NOW + off * DAY).toISOString().slice(0, 10)
/** Timestamp ISO completo desplazado `off` días respecto de hoy. */
const ts = (off: number) => new Date(NOW + off * DAY).toISOString()

// ── Clientes ──────────────────────────────────────────────────────────
const clientes: Cliente[] = [
  { id: 'cli-1', nombre: 'Carlos Méndez',             cuit: '20-30111222-3', telefono: '11-5555-0001', created_at: ts(-200), updated_at: ts(-200) },
  { id: 'cli-2', nombre: 'Lucía Fernández',           cuit: '27-28999888-4', telefono: '11-5555-0002', created_at: ts(-180), updated_at: ts(-180) },
  { id: 'cli-3', nombre: 'Distribuidora del Sur SRL', cuit: '30-71222333-9', telefono: '11-5555-0003', created_at: ts(-160), updated_at: ts(-160) },
  { id: 'cli-4', nombre: 'Martín Gómez',              cuit: null,            telefono: '11-5555-0004', created_at: ts(-90),  updated_at: ts(-90) },
  { id: 'cli-5', nombre: 'Ana Torres',                cuit: '27-33444555-1', telefono: null,           created_at: ts(-60),  updated_at: ts(-60) },
]

// ── Cheques ───────────────────────────────────────────────────────────
function enCartera(id: string, nro: string, banco: string | null, monto: string, pagoOff: number | null, compra: string, origen: string | null, createdOff: number): Cheque {
  return {
    id, nro_cheque: nro, banco, monto,
    fecha_emision: d(createdOff - 30), fecha_pago: pagoOff === null ? null : d(pagoOff),
    porcentaje_compra: compra, porcentaje_venta: null, ganancia: '0.00',
    estado: 'EN_CARTERA', ultimo_evento_manual_at: null, ultimo_operador_id: null,
    ultimo_motivo_manual: null, cliente_origen_id: origen, cliente_destino_id: null,
    tiene_foto: false, created_at: ts(createdOff), updated_at: ts(createdOff),
  }
}

function vendido(id: string, nro: string, banco: string, monto: string, compra: string, venta: string, ganancia: string, ventaOff: number, origen: string, destino: string): Cheque {
  return {
    id, nro_cheque: nro, banco, monto,
    fecha_emision: d(ventaOff - 40), fecha_pago: d(ventaOff + 30),
    porcentaje_compra: compra, porcentaje_venta: venta, ganancia,
    estado: 'VENDIDO', ultimo_evento_manual_at: ts(ventaOff), ultimo_operador_id: 'panel-web',
    ultimo_motivo_manual: 'Venta a financiera', cliente_origen_id: origen, cliente_destino_id: destino,
    tiene_foto: false, created_at: ts(ventaOff - 20), updated_at: ts(ventaOff),
  }
}

const cheques: Cheque[] = [
  // En cartera (varían vencimientos para el semáforo)
  enCartera('ch-1', '00012345', 'Galicia',   '450000',  5,    '10.00', 'cli-1', -10),
  enCartera('ch-2', '00023456', 'Santander', '1200000', 12,   '8.50',  'cli-3', -8),
  enCartera('ch-3', '00034567', 'BBVA',      '280000',  -3,   '12.00', 'cli-2', -20),
  enCartera('ch-4', '00045678', 'Nación',    '750000',  0,    '9.00',  'cli-4', -15),
  enCartera('ch-5', '00056789', 'Macro',     '95000',   20,   '11.50', 'cli-5', -6),
  enCartera('ch-6', '00067890', 'Galicia',   '3200000', 45,   '7.00',  'cli-3', -4),
  enCartera('ch-7', '00078901', null,        '180000',  60,   '13.00', 'cli-1', -2),
  enCartera('ch-8', '00089012', 'Santander', '520000',  null, '10.50', 'cli-2', -1),
  // Vendidos en el mes corriente (para el historial de ventas)
  vendido('ch-v1', '00090123', 'Galicia',   '600000', '10.00', '6.00', '24000', -2,  'cli-1', 'cli-4'),
  vendido('ch-v2', '00091234', 'BBVA',      '350000', '12.00', '7.00', '17500', -5,  'cli-2', 'cli-5'),
  vendido('ch-v3', '00092345', 'Macro',     '900000', '9.00',  '5.00', '36000', -8,  'cli-3', 'cli-1'),
  vendido('ch-v4', '00093456', 'Nación',    '150000', '11.00', '8.00', '4500',  -12, 'cli-4', 'cli-2'),
  vendido('ch-v5', '00094567', 'Santander', '420000', '10.50', '6.50', '16800', -1,  'cli-5', 'cli-3'),
]

// ── Fiados ────────────────────────────────────────────────────────────
const fiados: Fiado[] = [
  { id: 'fi-1', cheque_nro: '00055111', cliente_id: 'cli-2', monto_original: '300000', porcentaje_venta: '8.00',  saldo_pendiente: '276000', estado: 'ABIERTO',   fecha_fiado: d(-7),  created_at: ts(-7),  updated_at: ts(-7) },
  { id: 'fi-2', cheque_nro: '00055222', cliente_id: 'cli-4', monto_original: '180000', porcentaje_venta: '10.00', saldo_pendiente: '120000', estado: 'ABIERTO',   fecha_fiado: d(-15), created_at: ts(-15), updated_at: ts(-4) },
  { id: 'fi-3', cheque_nro: '00055333', cliente_id: 'cli-1', monto_original: '500000', porcentaje_venta: '6.00',  saldo_pendiente: '470000', estado: 'ABIERTO',   fecha_fiado: d(-3),  created_at: ts(-3),  updated_at: ts(-3) },
  { id: 'fi-4', cheque_nro: '00055444', cliente_id: 'cli-5', monto_original: '90000',  porcentaje_venta: '9.00',  saldo_pendiente: '0',      estado: 'CANCELADO', fecha_fiado: d(-40), created_at: ts(-40), updated_at: ts(-12) },
]

// ── Préstamos ─────────────────────────────────────────────────────────
function cuotas(prestamoId: string, specs: { venc: number; monto: string; estado: Cuota['estado']; cobro?: number }[]): Cuota[] {
  return specs.map((s, i) => ({
    id: `${prestamoId}-c${i + 1}`, prestamo_id: prestamoId, numero_cuota: i + 1,
    fecha_vencimiento: d(s.venc), monto: s.monto, estado: s.estado,
    fecha_cobro: s.cobro != null ? d(s.cobro) : null,
    created_at: ts(-90), updated_at: ts(-5),
  }))
}

const prestamos: Prestamo[] = [
  {
    id: 'pr-1', cliente_id: 'cli-1', credito: '500000', moneda: 'ARS', cuotas: 6, frecuencia: 'MENSUAL',
    total_a_cobrar: '600000', ganancia: '100000', estado: 'ACTIVO', fecha_inicio: d(-90),
    cuotas_detalle: cuotas('pr-1', [
      { venc: -60, monto: '100000', estado: 'COBRADA', cobro: -60 },
      { venc: -30, monto: '100000', estado: 'COBRADA', cobro: -30 },
      { venc: -10, monto: '100000', estado: 'PENDIENTE' }, // vencida
      { venc: 20,  monto: '100000', estado: 'PENDIENTE' },
      { venc: 50,  monto: '100000', estado: 'PENDIENTE' },
      { venc: 80,  monto: '100000', estado: 'PENDIENTE' },
    ]),
    created_at: ts(-90), updated_at: ts(-5),
  },
  {
    id: 'pr-2', cliente_id: 'cli-3', credito: '1000', moneda: 'USD', cuotas: 4, frecuencia: 'MENSUAL',
    total_a_cobrar: '1200', ganancia: '200', estado: 'ACTIVO', fecha_inicio: d(-25),
    cuotas_detalle: cuotas('pr-2', [
      { venc: -25, monto: '300', estado: 'COBRADA', cobro: -25 },
      { venc: 5,   monto: '300', estado: 'PENDIENTE' },
      { venc: 35,  monto: '300', estado: 'PENDIENTE' },
      { venc: 65,  monto: '300', estado: 'PENDIENTE' },
    ]),
    created_at: ts(-25), updated_at: ts(-5),
  },
  {
    id: 'pr-3', cliente_id: 'cli-4', credito: '200000', moneda: 'ARS', cuotas: 5, frecuencia: 'SEMANAL',
    total_a_cobrar: '250000', ganancia: '50000', estado: 'ACTIVO', fecha_inicio: d(-40),
    cuotas_detalle: cuotas('pr-3', [
      { venc: -33, monto: '50000', estado: 'COBRADA', cobro: -33 },
      { venc: -26, monto: '50000', estado: 'COBRADA', cobro: -26 },
      { venc: -19, monto: '50000', estado: 'EN_MORA' },   // vencida
      { venc: -12, monto: '50000', estado: 'EN_MORA' },   // vencida
      { venc: -5,  monto: '50000', estado: 'PENDIENTE' }, // vencida
    ]),
    created_at: ts(-40), updated_at: ts(-2),
  },
  {
    id: 'pr-4', cliente_id: 'cli-5', credito: '120000', moneda: 'ARS', cuotas: 3, frecuencia: 'MENSUAL',
    total_a_cobrar: '150000', ganancia: '30000', estado: 'CANCELADO', fecha_inicio: d(-120),
    cuotas_detalle: cuotas('pr-4', [
      { venc: -90, monto: '50000', estado: 'COBRADA', cobro: -90 },
      { venc: -60, monto: '50000', estado: 'COBRADA', cobro: -60 },
      { venc: -30, monto: '50000', estado: 'COBRADA', cobro: -30 },
    ]),
    created_at: ts(-120), updated_at: ts(-30),
  },
]

// ── Pasivos ───────────────────────────────────────────────────────────
const pasivos: Pasivo[] = [
  { id: 'pa-1', acreedor: 'Proveedor Papelería SA', concepto: 'Resma y tóner',       monto: '120000', saldo_pendiente: '120000', moneda: 'ARS', estado: 'PENDIENTE', fecha_vencimiento: d(10), fecha_cancelacion: null,  observaciones: null,            created_at: ts(-12), updated_at: ts(-12) },
  { id: 'pa-2', acreedor: 'Inmobiliaria Centro',    concepto: 'Alquiler del local',  monto: '200000', saldo_pendiente: '200000', moneda: 'ARS', estado: 'PENDIENTE', fecha_vencimiento: d(3),  fecha_cancelacion: null,  observaciones: 'Mes corriente', created_at: ts(-8),  updated_at: ts(-8) },
  { id: 'pa-3', acreedor: 'Importadora Global',     concepto: 'Mercadería en USD',   monto: '1500',   saldo_pendiente: '1500',   moneda: 'USD', estado: 'PENDIENTE', fecha_vencimiento: d(20), fecha_cancelacion: null,  observaciones: null,            created_at: ts(-5),  updated_at: ts(-5) },
  { id: 'pa-4', acreedor: 'Ferretería Norte',       concepto: 'Insumos varios',      monto: '45000',  saldo_pendiente: '0',      moneda: 'ARS', estado: 'CANCELADA', fecha_vencimiento: d(-2), fecha_cancelacion: d(-5), observaciones: null,            created_at: ts(-20), updated_at: ts(-5) },
]

// ── Gastos operativos ─────────────────────────────────────────────────
const gastos: GastoOperativo[] = [
  { id: 'ga-1', concepto: 'Nafta',           monto: '15000', moneda: 'ARS', fecha_operacion: d(-2), hora_operacion: '09:30', observaciones: 'Ruta a cliente', created_at: ts(-2), updated_at: ts(-2) },
  { id: 'ga-2', concepto: 'Comida',          monto: '8500',  moneda: 'ARS', fecha_operacion: d(-2), hora_operacion: '13:15', observaciones: null,             created_at: ts(-2), updated_at: ts(-2) },
  { id: 'ga-3', concepto: 'Estacionamiento', monto: '3000',  moneda: 'ARS', fecha_operacion: d(-5), hora_operacion: '11:00', observaciones: null,             created_at: ts(-5), updated_at: ts(-5) },
  { id: 'ga-4', concepto: 'Insumos oficina', monto: '19000', moneda: 'ARS', fecha_operacion: d(-8), hora_operacion: null,    observaciones: 'Librería',       created_at: ts(-8), updated_at: ts(-8) },
  { id: 'ga-5', concepto: 'Peajes',          monto: '4500',  moneda: 'ARS', fecha_operacion: d(-1), hora_operacion: '08:20', observaciones: null,             created_at: ts(-1), updated_at: ts(-1) },
]

// ── Movimientos de efectivo (divisas) ─────────────────────────────────
const movimientos: MovimientoEfectivo[] = [
  { id: 'mo-1', cliente_id: 'cli-1', tipo: 'VENTA',  moneda: 'USD', monto: '500', cotizacion_aplicada: '1450.00', ganancia: '25000', fecha_operacion: ts(-2), observaciones: null,           created_at: ts(-2), updated_at: ts(-2) },
  { id: 'mo-2', cliente_id: 'cli-3', tipo: 'COMPRA', moneda: 'USD', monto: '300', cotizacion_aplicada: '1400.00', ganancia: '12000', fecha_operacion: ts(-4), observaciones: 'Compra mostrador', created_at: ts(-4), updated_at: ts(-4) },
  { id: 'mo-3', cliente_id: null,    tipo: 'VENTA',  moneda: 'USD', monto: '800', cotizacion_aplicada: '1460.00', ganancia: '40000', fecha_operacion: ts(-6), observaciones: null,           created_at: ts(-6), updated_at: ts(-6) },
]

// ── Reporte de ganancias (mismo snapshot para cualquier período) ───────
const reporte: ReporteGanancias = {
  desde: d(-30), hasta: d(0),
  ganancia_cheques: '98800',
  ganancia_prestamos: '142000',
  ganancia_movimientos_efectivo: '77000',
  gastos_operativos: '50000',
  total_ganancias: '317800',
  neto: '267800',
  saldo_pasivos: { pendiente_ars: '320000', pendiente_usd: '1500' },
  cobros_cuotas_ars: '0',
  cobros_cuotas_usd: '0',
}

// ── Router ────────────────────────────────────────────────────────────
export async function mockFetch<T>(path: string, options?: RequestInit): Promise<T> {
  await new Promise((r) => setTimeout(r, 180)) // pequeño delay para ver los skeletons
  const method = (options?.method ?? 'GET').toUpperCase()
  const [raw, query] = path.split('?')
  const estado = new URLSearchParams(query ?? '').get('estado')

  if (method !== 'GET') {
    throw new Error('Modo demo (mock): las acciones de escritura están deshabilitadas.')
  }

  const out = (): unknown => {
    if (raw === '/cheques/cartera')     return cheques.filter((c) => c.estado === 'EN_CARTERA')
    if (raw === '/cheques')             return estado ? cheques.filter((c) => c.estado === estado) : cheques
    if (raw === '/clientes')            return clientes
    if (raw === '/fiados')              return estado ? fiados.filter((f) => f.estado === estado) : fiados
    if (raw === '/prestamos')           return estado ? prestamos.filter((p) => p.estado === estado) : prestamos
    if (raw === '/gastos-operativos')   return gastos
    if (raw === '/movimientos-efectivo') return movimientos
    if (raw === '/pasivos')             return estado ? pasivos.filter((p) => p.estado === estado) : pasivos
    if (raw === '/reportes/ganancias')  return reporte
    throw new Error(`Modo demo (mock): endpoint no simulado: ${raw}`)
  }

  return out() as T
}
