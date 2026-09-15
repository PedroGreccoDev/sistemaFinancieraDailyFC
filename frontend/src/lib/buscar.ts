// Búsqueda por nombre, pensada para el mostrador: el operador tipea como le sale
// —sin tildes, en minúscula, apurado— y tiene que encontrar al cliente igual.
//
// Por eso `normalizar` saca los acentos y la ñ se compara como n: "peña" y
// "pena" son la misma tecla para el que busca, y equivocarse de tecla no puede
// esconderle una deuda.

/** Minúsculas, sin tildes ni diacríticos, sin espacios de sobra. */
export function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim()
}

/**
 * ¿`texto` contiene todas las palabras de `consulta`?
 *
 * Palabra por palabra y no la frase entera, así "juan perez" encuentra a
 * "Pérez, Juan Carlos" —el orden en que está cargado el nombre no es el orden
 * en que el operador lo dice—. Una consulta vacía no filtra nada.
 */
export function coincide(texto: string, consulta: string): boolean {
  const q = normalizar(consulta)
  if (!q) return true
  const t = normalizar(texto)
  return q.split(/\s+/).every((palabra) => t.includes(palabra))
}
