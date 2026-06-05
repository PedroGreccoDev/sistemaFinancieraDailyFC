export type ChequeEstado = 'EN_CARTERA' | 'VENDIDO' | 'FIADO' | 'COBRADO' | 'RECHAZADO'
export type CuotaEstado = 'pendiente' | 'cobrada' | 'en_mora'
export type PrestamoEstado = 'activo' | 'cancelado' | 'en_mora'
export type Moneda = 'ARS' | 'USD'
export type Frecuencia = 'diaria' | 'semanal' | 'quincenal' | 'mensual' | 'anual'

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

export interface ReporteGanancias {
  desde: string
  hasta: string
  ganancia_cheques: string
  ganancia_prestamos: string
  ganancia_movimientos_efectivo: string
  total: string
}

export type MovimientoTipo = 'compra' | 'venta'

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

export interface DolarBlue {
  compra: number
  venta: number
  fechaActualizacion: string
}
