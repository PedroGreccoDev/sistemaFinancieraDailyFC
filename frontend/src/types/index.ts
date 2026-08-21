export type ChequeEstado = 'EN_CARTERA' | 'VENDIDO' | 'FIADO' | 'COBRADO' | 'RECHAZADO'
export type CuotaEstado = 'PENDIENTE' | 'COBRADA' | 'EN_MORA'
export type PrestamoEstado = 'ACTIVO' | 'CANCELADO' | 'EN_MORA'
export type Moneda = 'ARS' | 'USD'
export type Frecuencia = 'DIARIA' | 'SEMANAL' | 'QUINCENAL' | 'MENSUAL' | 'ANUAL'
export type PasivoEstado = 'PENDIENTE' | 'CANCELADA'
export type FiadoEstado = 'ABIERTO' | 'CANCELADO'
export type DeudaSimpleEstado = 'ABIERTA' | 'CANCELADA'

export interface Cheque {
  id: string
  nro_cheque: string
  banco: string | null
  monto: string
  fecha_emision: string | null
  fecha_pago: string | null
  porcentaje_compra: string
  // Cuánto se abonó al comprarlo. null = se pagó todo; menos que el valor neto
  // significa que hay una deuda abierta con el vendedor (§Comprar sin abonar).
  monto_abonado: string | null
  porcentaje_venta: string | null
  ganancia: string
  estado: ChequeEstado
  ultimo_evento_manual_at: string | null
  ultimo_operador_id: string | null
  ultimo_motivo_manual: string | null
  cliente_origen_id: string | null
  cliente_destino_id: string | null
  tiene_foto: boolean
  created_at: string
  updated_at: string
}

export interface Cuota {
  id: string
  prestamo_id: string
  numero_cuota: number
  fecha_vencimiento: string
  monto: string
  monto_pagado: string
  estado: CuotaEstado
  fecha_cobro: string | null
  created_at: string
  updated_at: string
}

export interface Prestamo {
  id: string
  cliente_id: string
  credito: string
  moneda: Moneda
  cuotas: number
  frecuencia: Frecuencia
  total_a_cobrar: string
  ganancia: string
  estado: PrestamoEstado
  fecha_inicio: string
  cuotas_detalle: Cuota[]
  created_at: string
  updated_at: string
}

export interface Cliente {
  id: string
  nombre: string
  cuit: string | null
  telefono: string | null
  created_at: string
  updated_at: string
}

export interface SaldoPasivos {
  pendiente_ars: string
  pendiente_usd: string
}

export interface CajaLinea {
  fecha: string
  categoria: string
  tipo: 'INGRESO' | 'EGRESO'
  monto: string
  detalle: string | null
  ganancia: string | null
  medio_pago: MedioPago | null
  cotizacion: string | null
}

export interface CajaMoneda {
  moneda: string
  ingresos_total: string
  egresos_total: string
  /** Flujo del período: ingresos − egresos. Un día de solo compras da negativo. */
  neto: string
  /** Plata que había al abrir el período (todo lo anterior + efectivo de arranque). */
  saldo_apertura: string
  /** Lo que queda al cerrar: apertura + neto. */
  saldo_cierre: string
  lineas: CajaLinea[]
}

export interface ReporteCaja {
  desde: string
  hasta: string
  ars: CajaMoneda
  usd: CajaMoneda
  ganancia_divisas: string
  saldo_pasivos: SaldoPasivos
}

export interface CuotaCobradaHistorialItem {
  cuota_id: string
  prestamo_id: string
  cliente_id: string
  cliente_nombre: string
  numero_cuota: number
  monto: string
  moneda: string
  fecha_cobro: string
  fecha_vencimiento: string
}

// Feed unificado de Movimientos: TODA operación (libro de caja + ingresos de
// cheques a cartera), venga del bot o del panel. Lo sirve GET /reportes/movimientos.
export type MovimientoGrupo =
  | 'COBROS' | 'CHEQUES' | 'DIVISAS' | 'GASTOS' | 'OTORGAMIENTOS' | 'PASIVOS'
  | 'APERTURA' | 'AJUSTES' | 'OTROS'
export type MovimientoFlujo = 'INGRESO' | 'EGRESO' | 'NEUTRO'

export interface MovimientoUnificado {
  id: string
  fecha: string
  moneda: Moneda
  grupo: MovimientoGrupo
  categoria: string
  flujo: MovimientoFlujo
  descripcion: string
  monto: string
  ganancia: string | null
  medio_pago: MedioPago | null
  cotizacion: string | null
  referencia_tipo: string | null
  referencia_id: string | null
}

export type MovimientoTipo = 'COMPRA' | 'VENTA'

export interface MovimientoEfectivo {
  id: string
  cliente_id: string | null
  tipo: MovimientoTipo
  moneda: Moneda
  monto: string
  cotizacion_aplicada: string
  // Pesos abonados. null = se pagó todo; menos que monto × cotización significa
  // que hay una deuda abierta con el vendedor (§Comprar sin abonar).
  monto_abonado: string | null
  ganancia: string
  usd_restante: string
  fecha_operacion: string
  observaciones: string | null
  created_at: string
  updated_at: string
}

export type MedioPago = 'EFECTIVO' | 'TRANSFERENCIA'

export interface Pasivo {
  id: string
  acreedor: string
  concepto: string
  monto: string
  saldo_pendiente: string
  moneda: Moneda
  estado: PasivoEstado
  fecha_vencimiento: string | null
  fecha_cancelacion: string | null
  observaciones: string | null
  cotizacion_pago: string | null
  created_at: string
  updated_at: string
}

/** Por qué se tocó la caja a mano. */
export type AjusteCajaMotivo = 'CORRECCION' | 'APORTE' | 'RETIRO' | 'OTRO'

/**
 * Plata agregada o restada a la caja sin una operación de negocio detrás.
 * `tipo` da el sentido: INGRESO suma efectivo, EGRESO lo resta (`monto` siempre
 * positivo). `cotizacion_usd` solo viene cuando el ajuste sumó dólares: es el
 * costo del lote FIFO que se creó para poder venderlos después.
 */
export interface AjusteCaja {
  id: string
  fecha: string
  moneda: Moneda
  tipo: 'INGRESO' | 'EGRESO'
  motivo: AjusteCajaMotivo
  monto: string
  cotizacion_usd: string | null
  lote_id: string | null
  descripcion: string | null
  operador_id: string
  created_at: string
  updated_at: string
}

export interface GastoOperativo {
  id: string
  concepto: string
  monto: string
  moneda: Moneda
  fecha_operacion: string
  hora_operacion: string | null
  observaciones: string | null
  created_at: string
  updated_at: string
}

export interface Fiado {
  id: string
  cheque_nro: string
  cliente_id: string
  monto_original: string
  porcentaje_venta: string
  saldo_pendiente: string
  estado: FiadoEstado
  fecha_fiado: string
  created_at: string
  updated_at: string
}

export interface CobrarConChequeResult {
  fiado: Fiado
  cheque_ingresado: Cheque
  diferencia: string
}

// Deuda libre de un cliente (sin cuotas ni cheque). Al registrarla sale un egreso
// de caja; al cobrarla (total/parcial, cross-currency) entra un ingreso.
export interface DeudaSimple {
  id: string
  cliente_id: string
  concepto: string
  monto: string
  saldo_pendiente: string
  moneda: Moneda
  estado: DeudaSimpleEstado
  fecha: string
  fecha_cancelacion: string | null
  observaciones: string | null
  cotizacion_pago: string | null
  created_at: string
  updated_at: string
}

export interface CuotaCobrarConChequeResult {
  cuota: Cuota
  cheque: Cheque
}

export interface CuotasLoteCobrarConChequeResult {
  cuotas: Cuota[]
  cheque: Cheque
}

export interface DolarBlue {
  compra: number
  venta: number
  fechaActualizacion: string
}
