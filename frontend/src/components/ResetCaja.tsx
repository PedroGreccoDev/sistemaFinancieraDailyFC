import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  CONFIRMACION_RESET,
  ejecutarReset,
  previsualizarReset,
  type ResetCajaResumen,
} from '../api/reset_caja'
import { useAuth } from '../auth/AuthContext'
import { fmtDate } from '../lib/fmt'
import { btnSolid, btnBordered } from '../lib/ui'
import { useToast } from '../lib/toast'
import { IconAlert } from './icons'

const FM = "'Manrope', sans-serif"
const INPUT_STYLE: React.CSSProperties = { width: '100%', background: 'var(--bg)', border: '1px solid var(--bd-012)', color: 'var(--text-1)', fontFamily: FM, fontSize: '0.82rem', padding: '0.5rem 0.75rem', outline: 'none', boxSizing: 'border-box' }
const LABEL_STYLE: React.CSSProperties = { display: 'block', fontFamily: FM, fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(100,116,139,0.7)', marginBottom: '0.3rem' }
const HELP: React.CSSProperties = { fontFamily: FM, fontSize: '0.72rem', color: 'rgba(100,116,139,0.75)', lineHeight: 1.5 }
const PELIGRO: React.CSSProperties = {
  background: 'color-mix(in srgb, var(--danger, #f87171) 8%, transparent)',
  border: '1px solid color-mix(in srgb, var(--danger, #f87171) 30%, transparent)',
  borderRadius: 'var(--r-md)',
  padding: '0.875rem 1rem',
}

/**
 * Arrancar la caja de cero conservando lo que el negocio tiene y debe.
 *
 * Son dos pasos separados a propósito: primero se pide el resumen de qué se va a
 * borrar y recién después se ejecuta escribiendo la frase a mano. Un solo botón
 * haría que el resumen se pudiera saltear, y ese resumen es la única chance de
 * ver que hay algo cargado que no se esperaba.
 */
export default function ResetCaja() {
  const { user } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()

  const [resumen, setResumen] = useState<ResetCajaResumen | null>(null)
  const [hecho, setHecho] = useState<ResetCajaResumen | null>(null)
  const [frase, setFrase] = useState('')
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fraseOk = frase.trim().toUpperCase() === CONFIRMACION_RESET

  async function verResumen() {
    setError(null)
    setCargando(true)
    try {
      setResumen(await previsualizarReset())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setCargando(false)
    }
  }

  async function ejecutar() {
    setError(null)
    setCargando(true)
    try {
      const r = await ejecutarReset({
        operador_id: user?.username ?? 'panel',
        confirmacion: frase,
      })
      setHecho(r)
      setResumen(null)
      setFrase('')
      toast('success', 'Caja reseteada. Ahora cargá los saldos de apertura.')
      // Todo lo que lee caja quedó desactualizado de golpe.
      queryClient.invalidateQueries()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setCargando(false)
    }
  }

  function cancelar() {
    setResumen(null)
    setFrase('')
    setError(null)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
      <p style={HELP}>
        Borra <strong>el historial de caja</strong> —los movimientos, los reportes, los
        gastos y el stock de dólares— para que los saldos arranquen de cero con lo que
        contás hoy.
        <br />
        <strong>No toca</strong> los cheques en cartera, lo que los clientes deben, ni lo
        que el negocio debe: todo eso sigue igual.
      </p>

      {/* Lo que hace que el reset sirva, y lo que menos se ve. Si el operador no
          entiende esta parte va a asustarse cuando edite un cheque viejo. */}
      <p style={{ ...HELP, fontSize: '0.68rem' }}>
        Todo lo que quede vivo pasa a contar como <strong>anterior a la línea</strong>: si
        después corregís un cheque o un préstamo viejo, se corrige el dato y{' '}
        <strong>la caja no se mueve</strong> — esa plata se movió antes. Lo que cargues a
        partir de ahí, aunque sea el mismo día, descuenta normalmente.
      </p>

      {hecho && (
        <div style={{ background: 'color-mix(in srgb, var(--success) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--success) 30%, transparent)', borderRadius: 'var(--r-md)', padding: '0.875rem 1rem' }}>
          <p style={{ ...HELP, color: 'var(--text-1)' }}>
            <strong>Caja reseteada.</strong> Se borraron {hecho.movimientos_caja} movimientos
            de caja, {hecho.gastos_operativos} gastos y {hecho.movimientos_efectivo} operaciones
            de dólares. {hecho.cheques_marcados} cheque(s) pasaron a contar como cartera vieja.
            {hecho.fecha_corte && <> La línea quedó en el {fmtDate(hecho.fecha_corte)}.</>}
            <br />
            <br />
            <strong>Ahora cargá los cuatro saldos</strong> en “Apertura del sistema”, acá
            arriba: billetes y cuenta, en pesos y en dólares. Hasta que lo hagas, la caja
            está en cero.
          </p>
        </div>
      )}

      {!resumen ? (
        <div>
          <button
            type="button"
            onClick={verResumen}
            disabled={cargando}
            style={{ ...btnBordered('warning'), padding: '0.55rem 1.1rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem', opacity: cargando ? 0.6 : 1 }}
          >
            <IconAlert size={14} />
            {cargando ? 'Consultando…' : 'Resetear la caja'}
          </button>
        </div>
      ) : (
        <div style={PELIGRO}>
          <p style={{ ...HELP, color: 'var(--text-1)', marginBottom: '0.75rem' }}>
            <strong>Esto no se puede deshacer.</strong> Revisá los números antes de seguir.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.875rem', marginBottom: '0.875rem' }}>
            <div>
              <p style={{ ...LABEL_STYLE, color: '#f87171' }}>Se borra</p>
              <ul style={{ ...HELP, color: 'var(--text-1)', listStyle: 'none', padding: 0, margin: 0 }}>
                <li>{resumen.movimientos_caja} movimientos de caja</li>
                <li>{resumen.gastos_operativos} gastos</li>
                <li>{resumen.ajustes_caja} ajustes de caja</li>
                <li>{resumen.movimientos_efectivo} operaciones de dólares</li>
              </ul>
            </div>
            <div>
              <p style={{ ...LABEL_STYLE, color: 'var(--success)' }}>Queda intacto</p>
              <ul style={{ ...HELP, color: 'var(--text-1)', listStyle: 'none', padding: 0, margin: 0 }}>
                <li>{resumen.conserva.cheques ?? 0} cheques en cartera</li>
                <li>{resumen.conserva.prestamos ?? 0} préstamos</li>
                <li>{resumen.conserva.fiados ?? 0} fiados</li>
                <li>{resumen.conserva.deudas_simples ?? 0} otras deudas</li>
                <li>{resumen.conserva.pasivos ?? 0} deudas del negocio</li>
              </ul>
            </div>
          </div>

          <div style={{ marginBottom: '0.75rem' }}>
            <label style={LABEL_STYLE}>
              Escribí <strong>{CONFIRMACION_RESET}</strong> para confirmar
            </label>
            <input
              type="text"
              value={frase}
              onChange={(e) => setFrase(e.target.value)}
              placeholder={CONFIRMACION_RESET}
              autoComplete="off"
              style={{ ...INPUT_STYLE, maxWidth: '18rem' }}
            />
          </div>

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button type="button" onClick={cancelar} style={{ ...btnBordered('neutral'), padding: '0.5rem 1rem' }}>
              Cancelar
            </button>
            <button
              type="button"
              onClick={ejecutar}
              disabled={!fraseOk || cargando}
              style={{ ...btnSolid('danger'), padding: '0.5rem 1rem', opacity: (!fraseOk || cargando) ? 0.5 : 1 }}
            >
              {cargando ? 'Reseteando…' : 'Resetear la caja'}
            </button>
          </div>
        </div>
      )}

      {error && <p style={{ fontFamily: FM, fontSize: '0.78rem', color: '#f87171' }}>{error}</p>}
    </div>
  )
}
