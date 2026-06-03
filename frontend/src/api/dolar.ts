import type { DolarBlue } from '../types'

export async function getDolarBlue(): Promise<DolarBlue> {
  const res = await fetch('https://dolarapi.com/v1/dolares/blue')
  if (!res.ok) throw new Error('No se pudo obtener la cotización')
  return res.json() as Promise<DolarBlue>
}
