import { API_BASE } from './client'

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export async function exportarJSON(): Promise<void> {
  const res = await fetch(`${API_BASE}/backup/exportar`)
  if (!res.ok) throw new Error('Error al exportar JSON')
  const blob = await res.blob()
  const fecha = new Date().toISOString().slice(0, 10)
  triggerDownload(blob, `backup_${fecha}.json`)
}

export async function exportarExcel(): Promise<void> {
  const res = await fetch(`${API_BASE}/backup/exportar-excel`)
  if (!res.ok) throw new Error('Error al exportar Excel')
  const blob = await res.blob()
  const fecha = new Date().toISOString().slice(0, 10)
  triggerDownload(blob, `datos_${fecha}.xlsx`)
}

export async function importarJSON(
  file: File,
): Promise<{ ok: boolean; tablas: Record<string, number> }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE}/backup/importar`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail?: string }).detail ?? 'Error al importar')
  }
  return res.json()
}
