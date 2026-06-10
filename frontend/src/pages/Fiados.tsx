import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getFiados, cobrarEfectivo, cobrarConCheque } from '../api/fiados'
import { getClientes } from '../api/clientes'
import { fmtARS, fmtDate } from '../lib/fmt'
import type { Fiado, FiadoEstado, CobrarConChequeResult } from '../types'

type Filtro = 'ABIERTO' | 'todos' | 'CANCELADO'

function EstadoBadge({ estado }: { estado: FiadoEstado }) {
  return estado === 'ABIERTO' ? (
    <span className="inline-flex items-center text-xs font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 rounded-full px-2 py-0.5">
      Abierto
    </span>
  ) : (
    <span className="inline-flex items-center text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400 rounded-full px-2 py-0.5">
      Cancelado
    </span>
  )
}

function inputCls() {
  return 'w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'
}

function labelCls() {
  return 'block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1'
}

// ── Modal cobrar en efectivo ───────────────────────────────────────────

function ModalEfectivo({
  fiado, clienteNombre, onClose, onSuccess,
}: {
  fiado: Fiado
  clienteNombre: string
  onClose: () => void
  onSuccess: () => void
}) {
  const [monto, setMonto] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const saldo = parseFloat(fiado.saldo_pendiente)
  const montoNum = parseFloat(monto) || 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (montoNum <= 0) { setError('El monto debe ser mayor a 0.'); return }
    if (montoNum > saldo) { setError(`No puede superar el saldo pendiente (${fmtARS(saldo)}).`); return }
    setLoading(true)
    setError(null)
    try {
      await cobrarEfectivo(fiado.id, montoNum, 'panel-web')
      onSuccess()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-slate-800 rounded-xl w-full max-w-sm shadow-xl">
        <div className="p-5 border-b border-slate-200 dark:border-slate-700">
          <h2 className="font-semibold text-slate-900 dark:text-slate-100">Cobrar en efectivo</h2>
          <p className="text-sm text-slate-500 mt-0.5">{clienteNombre} · Cheque {fiado.cheque_nro}</p>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="bg-slate-50 dark:bg-slate-700/50 rounded-lg px-4 py-3">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Saldo pendiente</p>
            <p className="text-lg font-bold text-amber-600 dark:text-amber-400">{fmtARS(saldo)}</p>
          </div>

          <div>
            <label className={labelCls()}>Monto cobrado</label>
            <input
              type="number" step="0.01" min="0.01" max={saldo}
              value={monto} onChange={(e) => setMonto(e.target.value)}
              placeholder="0,00" required
              className={inputCls()}
            />
            {montoNum > 0 && montoNum < saldo && (
              <p className="text-xs text-slate-400 mt-1">Saldo restante: {fmtARS(saldo - montoNum)}</p>
            )}
            {montoNum >= saldo && montoNum > 0 && (
              <p className="text-xs text-green-600 dark:text-green-400 mt-1">Cancela la deuda completamente</p>
            )}
          </div>

          {error && <p className="text-sm text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose}
              className="flex-1 px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={loading || montoNum <= 0}
              className="flex-1 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">
              {loading ? 'Guardando…' : 'Cobrar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal cobrar con cheque ───────────────────────────────────────────

function ModalCheque({
  fiado, clienteNombre, onClose, onSuccess,
}: {
  fiado: Fiado
  clienteNombre: string
  onClose: () => void
  onSuccess: (result: CobrarConChequeResult) => void
}) {
  const [nro, setNro] = useState('')
  const [monto, setMonto] = useState('')
  const [pct, setPct] = useState('')
  const [fechaEmision, setFechaEmision] = useState('')
  const [fechaPago, setFechaPago] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const saldo = parseFloat(fiado.saldo_pendiente)
  const montoNum = parseFloat(monto) || 0
  const pctNum = parseFloat(pct) || 0
  const valorNeto = montoNum * (100 - pctNum) / 100
  const diferencia = valorNeto - saldo
  const showPreview = montoNum > 0 && pct !== ''

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = await cobrarConCheque(fiado.id, {
        nro_cheque_pago: nro.trim(),
        monto_cheque: montoNum,
        porcentaje_compra_cheque: pctNum,
        fecha_emision: fechaEmision || null,
        fecha_pago: fechaPago || null,
        operador_id: 'panel-web',
      })
      onSuccess(result)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-slate-800 rounded-xl w-full max-w-sm shadow-xl max-h-[92vh] overflow-y-auto">
        <div className="p-5 border-b border-slate-200 dark:border-slate-700 sticky top-0 bg-white dark:bg-slate-800 z-10">
          <h2 className="font-semibold text-slate-900 dark:text-slate-100">Cobrar con cheque</h2>
          <p className="text-sm text-slate-500 mt-0.5">{clienteNombre} · Saldo: {fmtARS(saldo)}</p>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-3">
          <div>
            <label className={labelCls()}>Nº de cheque</label>
            <input type="text" value={nro} onChange={(e) => setNro(e.target.value)}
              placeholder="Número del cheque" required className={inputCls()} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls()}>Monto nominal</label>
              <input type="number" step="0.01" min="0.01"
                value={monto} onChange={(e) => setMonto(e.target.value)}
                placeholder="0,00" required className={inputCls()} />
            </div>
            <div>
              <label className={labelCls()}>% de compra</label>
              <input type="number" step="0.0001" min="0" max="100"
                value={pct} onChange={(e) => setPct(e.target.value)}
                placeholder="0,00" required className={inputCls()} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls()}>Fecha emisión</label>
              <input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} className={inputCls()} />
            </div>
            <div>
              <label className={labelCls()}>Fecha de pago</label>
              <input type="date" value={fechaPago} onChange={(e) => setFechaPago(e.target.value)} className={inputCls()} />
            </div>
          </div>

          {showPreview && (
            <div className={`rounded-lg px-4 py-3 text-sm space-y-1 ${diferencia >= 0 ? 'bg-green-50 dark:bg-green-900/20' : 'bg-amber-50 dark:bg-amber-900/20'}`}>
              <div className="flex justify-between text-slate-600 dark:text-slate-400">
                <span>Valor neto del cheque</span>
                <span className="font-semibold">{fmtARS(valorNeto)}</span>
              </div>
              <div className="flex justify-between font-semibold">
                <span className={diferencia >= 0 ? 'text-green-700 dark:text-green-400' : 'text-amber-700 dark:text-amber-400'}>
                  {diferencia > 0 ? 'Le debés al cliente' : diferencia < 0 ? 'Saldo restante' : 'Cancela exacto'}
                </span>
                {diferencia !== 0 && (
                  <span className={diferencia >= 0 ? 'text-green-700 dark:text-green-400' : 'text-amber-700 dark:text-amber-400'}>
                    {fmtARS(Math.abs(diferencia))}
                  </span>
                )}
              </div>
            </div>
          )}

          {error && <p className="text-sm text-red-500">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose}
              className="flex-1 px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={loading}
              className="flex-1 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">
              {loading ? 'Procesando…' : 'Confirmar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal resultado cobro con cheque ──────────────────────────────────

function ModalResultado({ result, onClose }: { result: CobrarConChequeResult; onClose: () => void }) {
  const diferencia = parseFloat(result.diferencia)
  const cancelado = result.fiado.estado === 'CANCELADO'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-slate-800 rounded-xl w-full max-w-sm shadow-xl p-5">
        <div className="text-center mb-4">
          <p className="text-3xl mb-2">{cancelado ? '🎉' : '✅'}</p>
          <h2 className="font-bold text-lg text-slate-900 dark:text-slate-100">
            {cancelado ? 'Fiado cancelado' : 'Pago parcial registrado'}
          </h2>
        </div>

        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-500">Cheque recibido</span>
            <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">
              {result.cheque_ingresado.nro_cheque}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Monto nominal</span>
            <span className="font-semibold text-slate-800 dark:text-slate-200">
              {fmtARS(result.cheque_ingresado.monto)}
            </span>
          </div>

          {cancelado && diferencia > 0 && (
            <div className="flex justify-between pt-2 border-t border-slate-200 dark:border-slate-700 font-semibold">
              <span className="text-amber-600 dark:text-amber-400">Le debés al cliente</span>
              <span className="text-amber-600 dark:text-amber-400">{fmtARS(diferencia)}</span>
            </div>
          )}
          {!cancelado && (
            <div className="flex justify-between pt-2 border-t border-slate-200 dark:border-slate-700 font-semibold">
              <span className="text-amber-600 dark:text-amber-400">Saldo restante</span>
              <span className="text-amber-600 dark:text-amber-400">{fmtARS(result.fiado.saldo_pendiente)}</span>
            </div>
          )}
        </div>

        <button onClick={onClose}
          className="mt-5 w-full px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors">
          Cerrar
        </button>
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────

export default function Fiados() {
  const [filtro, setFiltro] = useState<Filtro>('ABIERTO')
  const [cobrandoEfectivo, setCobrandoEfectivo] = useState<Fiado | null>(null)
  const [cobrandoCheque, setCobrandoCheque] = useState<Fiado | null>(null)
  const [resultado, setResultado] = useState<CobrarConChequeResult | null>(null)
  const queryClient = useQueryClient()

  const estado = filtro === 'todos' ? undefined : filtro as FiadoEstado
  const { data: fiados, isLoading, error, refetch } = useQuery({
    queryKey: ['fiados', filtro],
    queryFn: () => getFiados(estado),
    refetchInterval: 30_000,
  })
  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: getClientes,
    staleTime: 60_000,
  })

  const clienteMap = new Map(clientes?.map((c) => [c.id, c.nombre]) ?? [])
  const abiertos = fiados?.filter((f) => f.estado === 'ABIERTO') ?? []
  const totalSaldo = abiertos.reduce((s, f) => s + parseFloat(f.saldo_pendiente), 0)
  const clientesDistintos = new Set(abiertos.map((f) => f.cliente_id)).size

  function handleEfectivoSuccess() {
    setCobrandoEfectivo(null)
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
  }

  function handleChequeSuccess(result: CobrarConChequeResult) {
    setCobrandoCheque(null)
    queryClient.invalidateQueries({ queryKey: ['fiados'] })
    queryClient.invalidateQueries({ queryKey: ['cartera'] })
    setResultado(result)
  }

  function nombreCliente(id: string) {
    return clienteMap.get(id) ?? '…'
  }

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">Cheques fiados</h1>
          <p className="text-sm text-slate-500 mt-0.5">Deudas de clientes por cheques entregados en crédito</p>
        </div>
        <button onClick={() => refetch()}
          className="text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 border border-slate-200 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
          Actualizar
        </button>
      </div>

      {/* KPIs */}
      {filtro !== 'CANCELADO' && (
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Saldo total a cobrar</p>
            <p className="text-xl sm:text-2xl font-bold text-amber-600 dark:text-amber-400 leading-none">
              {fmtARS(totalSaldo)}
            </p>
            <p className="text-xs text-slate-400 mt-1">{abiertos.length} fiado(s) abierto(s)</p>
          </div>
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-1">Clientes con deuda</p>
            <p className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100 leading-none">
              {clientesDistintos}
            </p>
            <p className="text-xs text-slate-400 mt-1">cliente(s) distintos</p>
          </div>
        </div>
      )}

      {/* Filtros */}
      <div className="flex gap-2 mb-4">
        {(['ABIERTO', 'todos', 'CANCELADO'] as const).map((f) => (
          <button key={f} onClick={() => setFiltro(f)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
              filtro === f
                ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-900'
                : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
            }`}>
            {f === 'ABIERTO' ? 'Abiertos' : f === 'todos' ? 'Todos' : 'Cancelados'}
          </button>
        ))}
      </div>

      {/* Lista */}
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
        {isLoading && <div className="p-12 text-center text-slate-400">Cargando fiados…</div>}
        {error && <div className="p-12 text-center text-red-500">Error al cargar los fiados.</div>}
        {fiados && fiados.length === 0 && (
          <div className="p-12 text-center text-slate-400">
            <p className="text-4xl mb-3">✅</p>
            <p className="font-medium">Sin fiados registrados</p>
          </div>
        )}
        {fiados && fiados.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-700/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Cliente</th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Cheque</th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Monto orig.</th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Saldo</th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Fecha</th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Estado</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {fiados.map((fiado) => (
                  <tr key={fiado.id}
                    className="border-b border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors">
                    <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">
                      {nombreCliente(fiado.cliente_id)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500 dark:text-slate-400">
                      {fiado.cheque_nro}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-400 whitespace-nowrap">
                      <span className="text-xs text-slate-400 mr-1">{fiado.porcentaje_venta}%</span>
                      {fmtARS(fiado.monto_original)}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold whitespace-nowrap">
                      <span className={fiado.estado === 'ABIERTO' ? 'text-amber-600 dark:text-amber-400' : 'text-slate-400'}>
                        {fmtARS(fiado.saldo_pendiente)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {fmtDate(fiado.fecha_fiado)}
                    </td>
                    <td className="px-4 py-3">
                      <EstadoBadge estado={fiado.estado} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      {fiado.estado === 'ABIERTO' && (
                        <div className="flex gap-3 justify-end">
                          <button onClick={() => setCobrandoEfectivo(fiado)}
                            className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-200 font-medium transition-colors whitespace-nowrap">
                            Efectivo
                          </button>
                          <button onClick={() => setCobrandoCheque(fiado)}
                            className="text-xs text-emerald-600 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-200 font-medium transition-colors whitespace-nowrap">
                            Con cheque
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {cobrandoEfectivo && (
        <ModalEfectivo
          fiado={cobrandoEfectivo}
          clienteNombre={nombreCliente(cobrandoEfectivo.cliente_id)}
          onClose={() => setCobrandoEfectivo(null)}
          onSuccess={handleEfectivoSuccess}
        />
      )}
      {cobrandoCheque && (
        <ModalCheque
          fiado={cobrandoCheque}
          clienteNombre={nombreCliente(cobrandoCheque.cliente_id)}
          onClose={() => setCobrandoCheque(null)}
          onSuccess={handleChequeSuccess}
        />
      )}
      {resultado && (
        <ModalResultado result={resultado} onClose={() => setResultado(null)} />
      )}
    </div>
  )
}
