export const API_BASE = '/api/v1'

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  // Modo demo: datos falsos locales sin backend (se activa con VITE_MOCK=1).
  if (import.meta.env.VITE_MOCK === '1') {
    const { mockFetch } = await import('./mock')
    return mockFetch<T>(path, options)
  }
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail?: string }).detail ?? 'Error desconocido')
  }
  return res.json() as Promise<T>
}
