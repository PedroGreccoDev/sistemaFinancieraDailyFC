export type ChequeEstado = 'EN_CARTERA' | 'VENDIDO' | 'FIADO' | 'COBRADO' | 'RECHAZADO'
export type CuotaEstado = 'PENDIENTE' | 'COBRADA' | 'EN_MORA'
export type PrestamoEstado = 'ACTIVO' | 'CANCELADO' | 'EN_MORA'
export type Moneda = 'ARS' | 'USD'
export type Frecuencia = 'DIARIA' | 'SEMANAL' | 'QUINCENAL' | 'MENSUAL' | 'ANUAL'
export type PasivoEstado = 'PENDIENTE' | 'CANCELADA'

export interface Cheque {
  nro_cheque: string
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
  cheque_origen_nro: string | null
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
  observaciones: string | null
  created_at: string
  updated_at: string
}

export interface DolarBlue {
  compra: number
  venta: number
  fechaActualizacion: string
}
