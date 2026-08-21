import { apiFetch } from './client'
import type { Moneda } from '../types'
import type { RenglonImputado } from './deudores'

/**
 * Compensación: saldar la deuda de un cliente contra una deuda del negocio.
 *
 * El negocio le debe a Y y X le debe al negocio. En vez de cobrarle a X y
 * después pagarle a Y, **X le transfiere directo a Y**: bajan las dos deudas y
 * por la caja del negocio no pasa un peso.
 *
 * No asienta ninguna línea en el libro de caja, y esa es toda la gracia: esa
 * plata nunca pasó por acá. Cargarlo como dos operaciones sueltas —un cobro y un
 * pago— sigue funcionando, pero deja en el reporte un ingreso y un egreso que no
 * existieron.
 *
 * Imputa FIFO de los dos lados: del lado del cliente cruzando fiados, deudas
 * libres y préstamos (igual que el cobro consolidado), y del lado del acreedor
 * entre todas las deudas que el negocio le tiene, de la más vieja a la más
 * nueva. Por eso se manda el **acreedor**, no una deuda puntual.
 */

export interface CompensacionPayload {
  cliente_id: string
  /** Nombre exacto del acreedor: la transferencia se reparte entre todas sus deudas. */
  acreedor: string
  /** Contra qué moneda de las deudas con ese acreedor se imputa. */
  moneda_pasivo: Moneda
  /** Contra qué moneda de la deuda del cliente se imputa (ARS y USD no se suman). */
  moneda_deuda: Moneda
  /** Lo que realmente se transfirió, en `moneda`. */
  monto: number
  moneda: Moneda
  /** $/USD. Obligatoria si alguna de las dos deudas está en la otra moneda. */
  cotizacion?: number | null
  fecha?: string | null
  observaciones?: string | null
}

export interface CompensacionResult {
  id: string
  fecha: string
  cliente_id: string
  cliente_nombre: string
  acreedor: string
  moneda: Moneda
  monto: string
  moneda_deuda: Moneda
  moneda_pasivo: Moneda
  /** Lado del cliente: qué deudas se alcanzaron y cuánto le tocó a cada una. */
  renglones: RenglonImputado[]
  imputado_cliente: string
  canceladas: number
  saldo_restante_cliente: string
  /** Lado del acreedor: total imputado, lo que queda y cuántas deudas se saldaron. */
  imputado_pasivo: string
  saldo_restante_pasivo: string
  pasivos_cancelados: number
  /** Lo que el cliente transfirió de más: le queda a favor, en `moneda`. */
  excedente: string
  pasivo_excedente_id: string | null
}

export const compensar = (payload: CompensacionPayload): Promise<CompensacionResult> =>
  apiFetch<CompensacionResult>('/compensaciones', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface Compensacion {
  id: string
  fecha: string
  cliente_id: string
  acreedor: string
  moneda: Moneda
  monto: string
  moneda_deuda: Moneda
  moneda_pasivo: Moneda
  cotizacion: string | null
  imputado_cliente: string
  imputado_pasivo: string
  excedente: string
  pasivo_excedente_id: string | null
  observaciones: string | null
  created_at: string
}

export const getCompensaciones = (params?: {
  cliente_id?: string
  acreedor?: string
}): Promise<Compensacion[]> => {
  const qs = new URLSearchParams()
  if (params?.cliente_id) qs.set('cliente_id', params.cliente_id)
  if (params?.acreedor) qs.set('acreedor', params.acreedor)
  const sufijo = qs.toString() ? `?${qs}` : ''
  return apiFetch<Compensacion[]>(`/compensaciones${sufijo}`)
}
