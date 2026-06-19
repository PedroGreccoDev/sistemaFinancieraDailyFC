import { useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { exportarJSON, exportarExcel, importarJSON } from '../api/backup'
import { useToast } from '../lib/toast'
import { btnFlat, btnSolid, btnBordered, FM } from '../lib/ui'
import { IconDownload, IconUpload, IconFileJson, IconTable, IconAlert, IconClose, IconUserCog } from '../components/icons'

const TABLA_LABELS: Record<string, string> = {
  clientes:             'Clientes',
  cheques:              'Cheques',
  prestamos:            'Préstamos',
  cuotas:               'Cuotas',
  movimientos_efectivo: 'Movimientos',
  fiados:               'Fiados',
  pasivos:              'Pasivos',
  gastos_operativos:    'Gastos',
}

const ALL_TABLAS = Object.keys(TABLA_LABELS)

function SectionCard({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--bd-006)',
      borderRadius: 'var(--r-lg)',
      padding: '1.5rem',
    }}>
      {children}
    </div>
  )
}

function SectionTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
      <div style={{
        width: 40, height: 40, borderRadius: 'var(--r-md)',
        background: 'color-mix(in srgb, var(--primary) 12%, transparent)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, color: 'var(--primary)',
      }}>
        {icon}
      </div>
      <div>
        <div style={{ fontFamily: FM, fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-strong)' }}>
          {title}
        </div>
        <div style={{ fontFamily: FM, fontSize: '0.75rem', color: 'var(--text-2)', marginTop: 2 }}>
          {subtitle}
        </div>
      </div>
    </div>
  )
}

function ConfirmModal({
  onConfirm,
  onCancel,
  loading,
}: {
  onConfirm: () => void
  onCancel: () => void
  loading: boolean
}) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'rgba(0,0,0,0.65)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '1rem',
    }}>
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--bd-006)',
        borderRadius: 'var(--r-lg)',
        padding: '1.75rem',
        width: '100%', maxWidth: 420,
        boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <IconAlert size={20} style={{ color: 'var(--danger)' }} />
            <span style={{ fontFamily: FM, fontWeight: 700, fontSize: '1rem', color: 'var(--text-strong)' }}>
              Confirmar importación
            </span>
          </div>
          <button onClick={onCancel} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-2)', padding: 4 }}>
            <IconClose size={18} />
          </button>
        </div>

        <div style={{
          background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
          border: '1px solid color-mix(in srgb, var(--danger) 30%, transparent)',
          borderRadius: 'var(--r-md)',
          padding: '0.9rem 1rem',
          marginBottom: '1.25rem',
        }}>
          <p style={{ fontFamily: FM, fontSize: '0.8rem', color: 'var(--danger)', margin: 0, lineHeight: 1.6 }}>
            <strong>Esta acción reemplaza TODOS los datos actuales</strong> con el contenido del archivo seleccionado.
            Se eliminarán clientes, cheques, préstamos, fiados, pasivos y gastos.
            <br /><strong>No se puede deshacer.</strong>
          </p>
        </div>

        <p style={{ fontFamily: FM, fontSize: '0.8rem', color: 'var(--text-2)', marginBottom: '1.25rem' }}>
          Asegurate de haber seleccionado el archivo correcto antes de continuar.
        </p>

        <div style={{ display: 'flex', gap: '0.6rem', justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={btnBordered('neutral')} disabled={loading}>
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            style={{ ...btnSolid('danger'), opacity: loading ? 0.7 : 1 }}
            disabled={loading}
          >
            {loading ? 'Importando…' : 'Sí, importar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Estilos reutilizables ──────────────────────────────────────────────────

const labelStyle: CSSProperties = {
  fontFamily: FM,
  fontSize: '0.72rem',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.1em',
  color: 'var(--text-2)',
  marginBottom: '0.5rem',
}

const dateInputStyle: CSSProperties = {
  fontFamily: FM,
  fontSize: '0.82rem',
  padding: '0.4rem 0.6rem',
  borderRadius: 'var(--r-sm)',
  border: '1px solid var(--bd-006)',
  background: 'var(--surface)',
  color: 'var(--text-1)',
  outline: 'none',
}

export default function Configuracion() {
  const push = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<Record<string, number> | null>(null)
  const [loadingJson, setLoadingJson] = useState(false)
  const [loadingExcel, setLoadingExcel] = useState(false)

  // Filtros para Excel
  const [showFilters, setShowFilters] = useState(false)
  const [excelDesde, setExcelDesde] = useState('')
  const [excelHasta, setExcelHasta] = useState('')
  const [tablasSeleccionadas, setTablasSeleccionadas] = useState<Set<string>>(new Set(ALL_TABLAS))

  const todasSeleccionadas = tablasSeleccionadas.size === ALL_TABLAS.length
  const algunaSeleccionada = tablasSeleccionadas.size > 0

  function toggleTabla(key: string) {
    setTablasSeleccionadas(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function toggleAll() {
    setTablasSeleccionadas(todasSeleccionadas ? new Set() : new Set(ALL_TABLAS))
  }

  const hayFiltrosActivos = excelDesde || excelHasta || !todasSeleccionadas

  async function handleExportJson() {
    setLoadingJson(true)
    try {
      await exportarJSON()
      push('success', 'Backup JSON descargado')
    } catch {
      push('error', 'Error al exportar JSON')
    } finally {
      setLoadingJson(false)
    }
  }

  async function handleExportExcel() {
    if (!algunaSeleccionada) {
      push('error', 'Seleccioná al menos una tabla para exportar')
      return
    }
    setLoadingExcel(true)
    try {
      await exportarExcel({
        desde: excelDesde || null,
        hasta: excelHasta || null,
        tablas: todasSeleccionadas ? undefined : Array.from(tablasSeleccionadas),
      })
      push('success', 'Excel descargado')
    } catch {
      push('error', 'Error al exportar Excel')
    } finally {
      setLoadingExcel(false)
    }
  }

  function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setSelectedFile(f)
    setImportResult(null)
    setShowConfirm(true)
    e.target.value = ''
  }

  async function handleConfirmImport() {
    if (!selectedFile) return
    setImporting(true)
    try {
      const res = await importarJSON(selectedFile)
      setImportResult(res.tablas)
      push('success', 'Base de datos restaurada correctamente')
    } catch (err) {
      push('error', err instanceof Error ? err.message : 'Error al importar')
    } finally {
      setImporting(false)
      setShowConfirm(false)
      setSelectedFile(null)
    }
  }

  return (
    <div className="px-4 pt-5 sm:px-8 sm:pt-6 pb-fab" style={{ maxWidth: 760, margin: '0 auto' }}>
      <div style={{ marginBottom: '1.75rem' }}>
        <h1 style={{
          fontFamily: "'Bebas Neue', sans-serif",
          fontSize: '2rem',
          letterSpacing: '0.05em',
          color: 'var(--text-strong)',
          margin: 0,
        }}>
          Configuración
        </h1>
        <p style={{ fontFamily: FM, fontSize: '0.8rem', color: 'var(--text-2)', marginTop: 4 }}>
          Exportación e importación de datos del sistema
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

        {/* ── Usuarios ─────────────────────────────────────────────────── */}
        <SectionCard>
          <SectionTitle
            icon={<IconUserCog size={20} />}
            title="Usuarios"
            subtitle="Invitá personas, editá roles y gestioná el acceso al panel."
          />
          <Link
            to="/usuarios"
            style={{ ...btnSolid('primary'), display: 'inline-flex', alignItems: 'center', gap: '0.4rem', textDecoration: 'none' }}
          >
            <IconUserCog size={14} />
            Gestionar usuarios
          </Link>
        </SectionCard>

        {/* ── Backup JSON ──────────────────────────────────────────────── */}
        <SectionCard>
          <SectionTitle
            icon={<IconFileJson size={20} />}
            title="Backup completo (JSON)"
            subtitle="Exporta todos los datos para restaurar el sistema ante un fallo. La importación reemplaza toda la base de datos."
          />

          <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
            <button
              onClick={handleExportJson}
              style={{ ...btnSolid('primary'), display: 'flex', alignItems: 'center', gap: '0.4rem', opacity: loadingJson ? 0.7 : 1 }}
              disabled={loadingJson}
            >
              <IconDownload size={14} />
              {loadingJson ? 'Exportando…' : 'Exportar JSON'}
            </button>

            <button
              onClick={() => fileInputRef.current?.click()}
              style={{ ...btnFlat('warning'), display: 'flex', alignItems: 'center', gap: '0.4rem' }}
            >
              <IconUpload size={14} />
              Importar JSON
            </button>

            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              style={{ display: 'none' }}
              onChange={handleFileSelected}
            />
          </div>

          {importResult && (
            <div style={{
              marginTop: '1.1rem',
              background: 'color-mix(in srgb, var(--success) 10%, transparent)',
              border: '1px solid color-mix(in srgb, var(--success) 25%, transparent)',
              borderRadius: 'var(--r-md)',
              padding: '0.9rem 1rem',
            }}>
              <p style={{ fontFamily: FM, fontSize: '0.75rem', fontWeight: 700, color: 'var(--success)', margin: '0 0 0.6rem' }}>
                Restauración completada
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                {Object.entries(importResult).map(([key, count]) => (
                  <span key={key} style={{
                    fontFamily: FM, fontSize: '0.7rem', fontWeight: 600,
                    background: 'color-mix(in srgb, var(--success) 15%, transparent)',
                    color: 'var(--success)',
                    border: '1px solid color-mix(in srgb, var(--success) 30%, transparent)',
                    borderRadius: 'var(--r-sm)',
                    padding: '2px 8px',
                  }}>
                    {TABLA_LABELS[key] ?? key}: {count}
                  </span>
                ))}
              </div>
            </div>
          )}
        </SectionCard>

        {/* ── Excel ────────────────────────────────────────────────────── */}
        <SectionCard>
          <SectionTitle
            icon={<IconTable size={20} />}
            title="Exportar a Excel"
            subtitle="Archivo .xlsx legible con todas las tablas en hojas separadas, incluyendo fotos de cheques. Filtrá por período o elegí qué tablas incluir."
          />

          <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              onClick={handleExportExcel}
              style={{ ...btnSolid('success'), display: 'flex', alignItems: 'center', gap: '0.4rem', opacity: loadingExcel ? 0.7 : 1 }}
              disabled={loadingExcel}
            >
              <IconDownload size={14} />
              {loadingExcel ? 'Generando…' : 'Descargar Excel'}
            </button>

            <button
              onClick={() => setShowFilters(v => !v)}
              style={{
                ...btnBordered('neutral'),
                display: 'flex', alignItems: 'center', gap: '0.35rem',
                ...(hayFiltrosActivos ? { borderColor: 'var(--primary)', color: 'var(--primary)' } : {}),
              }}
            >
              Filtros
              {hayFiltrosActivos && (
                <span style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 16, height: 16, borderRadius: '50%',
                  background: 'var(--primary)', color: '#fff',
                  fontSize: '0.6rem', fontWeight: 700,
                }}>
                  {(excelDesde || excelHasta ? 1 : 0) + (!todasSeleccionadas ? 1 : 0)}
                </span>
              )}
              <span style={{ fontSize: '0.65rem' }}>{showFilters ? '▲' : '▼'}</span>
            </button>
          </div>

          {showFilters && (
            <div style={{
              marginTop: '1rem',
              borderTop: '1px solid var(--bd-006)',
              paddingTop: '1rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}>

              {/* Período */}
              <div>
                <p style={labelStyle}>Período (fecha de registro)</p>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                  <input
                    type="date"
                    value={excelDesde}
                    onChange={e => setExcelDesde(e.target.value)}
                    style={dateInputStyle}
                  />
                  <span style={{ fontFamily: FM, fontSize: '0.8rem', color: 'var(--text-2)' }}>—</span>
                  <input
                    type="date"
                    value={excelHasta}
                    onChange={e => setExcelHasta(e.target.value)}
                    style={dateInputStyle}
                  />
                  {(excelDesde || excelHasta) && (
                    <button
                      onClick={() => { setExcelDesde(''); setExcelHasta('') }}
                      style={{ ...btnBordered('neutral'), fontSize: '0.75rem', padding: '0.3rem 0.6rem' }}
                    >
                      Limpiar
                    </button>
                  )}
                </div>
              </div>

              {/* Tablas */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <p style={{ ...labelStyle, margin: 0 }}>Tablas a incluir</p>
                  <button
                    onClick={toggleAll}
                    style={{ fontFamily: FM, fontSize: '0.72rem', color: 'var(--primary)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                  >
                    {todasSeleccionadas ? 'Desmarcar todo' : 'Seleccionar todo'}
                  </button>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem 1.2rem' }}>
                  {ALL_TABLAS.map(key => (
                    <label
                      key={key}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '0.35rem',
                        cursor: 'pointer', fontFamily: FM, fontSize: '0.82rem',
                        color: tablasSeleccionadas.has(key) ? 'var(--text-1)' : 'var(--text-2)',
                        userSelect: 'none',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={tablasSeleccionadas.has(key)}
                        onChange={() => toggleTabla(key)}
                        style={{ accentColor: 'var(--primary)', width: 14, height: 14, cursor: 'pointer' }}
                      />
                      {TABLA_LABELS[key]}
                    </label>
                  ))}
                </div>
                {!algunaSeleccionada && (
                  <p style={{ fontFamily: FM, fontSize: '0.75rem', color: 'var(--danger)', marginTop: '0.4rem' }}>
                    Seleccioná al menos una tabla.
                  </p>
                )}
              </div>

            </div>
          )}
        </SectionCard>

      </div>

      {showConfirm && (
        <ConfirmModal
          onConfirm={handleConfirmImport}
          onCancel={() => { setShowConfirm(false); setSelectedFile(null) }}
          loading={importing}
        />
      )}
    </div>
  )
}
