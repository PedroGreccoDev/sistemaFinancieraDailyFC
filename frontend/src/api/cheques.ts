import { apiFetch, API_BASE } from './client'
import type { Cheque, ChequeTipo, Fiado, MedioPago } from '../types'

/** URL directa a la foto del cheque (misma-origen: sirve para <img>, descarga y compartir). */
export const chequeFotoUrl = (cheque_id: string): string =>
  `${API_BASE}/cheques/${encodeURIComponent(cheque_id)}/foto`

export const getChequeCartera = (): Promise<Cheque[]> =>
  apiFetch<Cheque[]>('/cheques/cartera')

export const getCheques = (estado?: string): Promise<Cheque[]> =>
  apiFetch<Cheque[]>(`/cheques${estado ? `?estado=${estado}` : ''}`)

// Uno solo, por id. Lo necesita la pantalla de fiados: ahi se ve la deuda, no el
// cheque, y para corregirlo hay que traerlo. Por id y no por numero, que con la
// recompra puede repetirse.
export const getCheque = (cheque_id: string): Promise<Cheque> =>
  apiFetch<Cheque>(`/cheques/${encodeURIComponent(cheque_id)}`)

// Alta manual de un cheque desde el panel (equivale al REGISTRAR_CHEQUE del bot).
// El cheque entra siempre EN_CARTERA y su compra descuenta la caja ARS en el backend.
export interface ChequeCreatePayload {
  /** Opcional: el comprobante de emisión de un e-cheq no trae número. */
  nro_cheque?: string | null
  banco?: string | null
  monto: number
  fecha_emision?: string | null
  fecha_pago?: string | null
  porcentaje_compra: number
  cliente_origen_id?: string | null
  /** Por cuál de las dos cajas salió lo abonado. Efectivo si no se manda. */
  medio_pago?: MedioPago
  /** Papel o e-cheq. Papel si no se manda: es el caso normal. */
  tipo?: ChequeTipo
  // Cuánto se abonó por el cheque. Omitir = se pagó todo (la compra normal).
  // Menos que el valor neto deja el resto a deber: no descuenta la caja y genera
  // la deuda con el vendedor, que pasa a ser obligatorio (§Comprar sin abonar).
  monto_abonado?: number
}

export const crearCheque = (payload: ChequeCreatePayload): Promise<Cheque> =>
  apiFetch<Cheque>('/cheques', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// Venta de un cheque de la cartera. Va por la transición manual genérica —el
// backend no tiene un /vender— con `target_state: VENDIDO`: eso pasa el cheque a
// estado terminal, calcula la ganancia (monto · (%compra − %venta)) y asienta el
// ingreso a la caja de `medio_pago` por el neto: monto · (1 − %venta).
interface VenderChequePayload {
  porcentaje_venta: number
  /** A quién se lo vendió. Opcional: la venta de mostrador no siempre tiene nombre. */
  cliente_destino_id?: string | null
  motivo: string
  operador_id: string
  /** Por cuál de las dos cajas entra la plata. Efectivo si no se manda. */
  medio_pago?: MedioPago
}

export const venderCheque = (cheque_id: string, payload: VenderChequePayload): Promise<Cheque> =>
  apiFetch<Cheque>(`/cheques/${encodeURIComponent(cheque_id)}/transiciones`, {
    method: 'POST',
    body: JSON.stringify({ target_state: 'VENDIDO', ...payload }),
  })

interface FiarChequePayload {
  cliente_destino_id: string
  porcentaje_venta: number
  motivo: string
  operador_id: string
}

export interface FiarChequeResult {
  cheque: Cheque
  fiado: Fiado
}

export const fiarCheque = (cheque_id: string, payload: FiarChequePayload): Promise<FiarChequeResult> =>
  apiFetch<FiarChequeResult>(`/cheques/${encodeURIComponent(cheque_id)}/fiar`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// Corrección de la carga de un cheque. Solo se mandan los campos a cambiar.
export interface ChequeUpdatePayload {
  nro_cheque?: string | null
  banco?: string | null
  // El tipo se corrige como cualquier otro dato mal cargado: es una etiqueta y
  // no recalcula nada. El error tipico es un e-cheq que entro por foto como papel.
  tipo?: ChequeTipo
  monto?: number
  fecha_emision?: string | null
  fecha_pago?: string | null
  porcentaje_compra?: number
  porcentaje_venta?: number
  cliente_origen_id?: string | null
  cliente_destino_id?: string | null
}

export const editarCheque = (cheque_id: string, payload: ChequeUpdatePayload): Promise<Cheque> =>
  apiFetch<Cheque>(`/cheques/${encodeURIComponent(cheque_id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
