export type ChequeEstado = 'EN_CARTERA' | 'VENDIDO' | 'FIADO' | 'COBRADO' | 'RECHAZADO'
export type CuotaEstado = 'PENDIENTE' | 'COBRADA' | 'EN_MORA'
export type PrestamoEstado = 'ACTIVO' | 'CANCELADO' | 'EN_MORA'
export type Moneda = 'ARS' | 'USD'
export type Frecuencia = 'DIARIA' | 'SEMANAL' | 'QUINCENAL' | 'MENSUAL' | 'ANUAL'
export type PasivoEstado = 'PENDIENTE' | 'CANCELADA'
export type FiadoEstado = 'ABIERTO' | 'CANCELADO'

export interface Cheque {
  id: string
  nro_cheque: string
  banco: string | null
  monto: string
  fecha_emision: string | null
  fecha_pago: string | null
  porcentaje_compra: string
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

export interface ReporteGanancias {
  desde: string
  hasta: string
  ganancia_cheques: string
  ganancia_prestamos: string
  ganancia_movimientos_efectivo: string
  gastos_operativos: string
  total_ganancias: string
  neto: string
  saldo_pasivos: SaldoPasivos
  cobros_cuotas_ars: string
  cobros_cuotas_usd: string
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

export type MovimientoTipo = 'COMPRA' | 'VENTA'

export interface MovimientoEfectivo {
  id: string
  cliente_id: string | null
  tipo: MovimientoTipo
  moneda: Moneda
  monto: string
  cotizacion_aplicada: string
  ganancia: string
  fecha_operacion: string
  observaciones: string | null
  created_at: string
  updated_at: string
}

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
