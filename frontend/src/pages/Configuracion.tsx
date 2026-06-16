import { useRef, useState } from 'react'
import { exportarJSON, exportarExcel, importarJSON } from '../api/backup'
import { useToast } from '../lib/toast'
import { btnFlat, btnSolid, btnBordered, FM } from '../lib/ui'
import { IconDownload, IconUpload, IconFileJson, IconTable, IconAlert, IconClose } from '../components/icons'

const TABLA_LABELS: Record<string, string> = {
  clientes: 'Clientes',
  cheques: 'Cheques',
  prestamos: 'Préstamos',
  cuotas: 'Cuotas',
  movimientos_efectivo: 'Movimientos',
  fiados: 'Fiados',
  pasivos: 'Pasivos',
  gastos_operativos: 'Gastos',
}

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

export default function Configuracion() {
  const push = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<Record<string, number> | null>(null)
  const [loadingJson, setLoadingJson] = useState(false)
  const [loadingExcel, setLoadingExcel] = useState(false)

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
    setLoadingExcel(true)
    try {
      await exportarExcel()
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
    <div style={{ padding: '1.5rem', maxWidth: 760, margin: '0 auto' }}>
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

        {/* ── Backup JSON ─────────────────────────────────────────── */}
        <SectionCard>
          <SectionTitle
            icon={<IconFileJson size={20} />}
            title="Backup completo (JSON)"
            subtitle="Para restaurar el sistema ante un fallo. Incluye todos los datos: clientes, cheques, préstamos, fiados, pasivos y gastos."
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

        {/* ── Excel ───────────────────────────────────────────────── */}
        <SectionCard>
          <SectionTitle
            icon={<IconTable size={20} />}
            title="Exportar a Excel"
            subtitle="Archivo .xlsx legible con todas las tablas en hojas separadas. Útil para revisar datos o compartir con terceros."
          />

          <button
            onClick={handleExportExcel}
            style={{ ...btnSolid('success'), display: 'flex', alignItems: 'center', gap: '0.4rem', opacity: loadingExcel ? 0.7 : 1 }}
            disabled={loadingExcel}
          >
            <IconDownload size={14} />
            {loadingExcel ? 'Generando…' : 'Descargar Excel'}
          </button>
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
