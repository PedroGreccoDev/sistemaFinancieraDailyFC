/**
 * Manda al backend los errores que revientan en la pantalla del operador.
 *
 * Hasta acá el registro de bugs solo veía lo que pasaba en el servidor. Un error
 * de JavaScript no llega a ningún log: deja la pantalla en blanco o un botón que
 * no hace nada, el operador reintenta, se cansa y sigue a mano. Nadie se entera.
 *
 * Tres cosas que conviene no deshacer:
 *
 * 1. **Usa `fetch` pelado y no `apiFetch`.** Si el reporte pasara por el cliente
 *    de la API y ese cliente fallara, el fallo dispararía otro reporte y así
 *    para siempre. Además el buzón es público: no necesita el token.
 * 2. **Nunca lanza.** Un error al reportar un error solo puede empeorar la
 *    pantalla que ya está rota.
 * 3. **Dedupe en el navegador.** Un error dentro de un render de React se
 *    repite en cada re-render: sin esto, un solo bug manda cientos de POST.
 */

const BUZON = '/api/v1/bugs/frontend'

/** Errores ya reportados en esta pestaña, por huella. */
const yaReportados = new Set<string>()

/** Tope por pestaña: si algo entra en loop, que no inunde al backend. */
const TOPE = 25
let enviados = 0

export type ClaseError = 'error' | 'promesa' | 'render' | 'red'

/**
 * `archivo.js:línea` de la primera línea útil del stack.
 *
 * Es lo que agrupa el bug del lado del servidor, así que tiene que ser estable
 * entre recargas: el mensaje puede traer un monto o un nombre distinto cada vez,
 * la línea no.
 */
function ubicacionDe(stack: string): string {
  const linea = stack
    .split('\n')
    .slice(1)
    .find((l) => l.includes('.js') || l.includes('.tsx') || l.includes('.ts'))
  if (!linea) return ''

  const m = linea.match(/([\w.-]+\.(?:js|tsx?|mjs)):(\d+)/)
  return m ? `${m[1]}:${m[2]}` : ''
}

/**
 * La pantalla donde está parado el operador, sin los identificadores.
 *
 * `/deudores/clientes/3f2a…` y el mismo con otro cliente son la misma pantalla:
 * si el id entrara, el backend abriría un bug por cada cliente que la abriera.
 */
function rutaActual(): string {
  return window.location.pathname
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '{id}')
    .replace(/\b\d{2,}\b/g, '{id}')
}

export function reportarError(
  error: unknown,
  clase: ClaseError = 'error',
  ubicacionExtra = '',
): void {
  try {
    if (enviados >= TOPE) return

    const err = error instanceof Error ? error : new Error(String(error))
    const stack = err.stack ?? ''
    const ubicacion = ubicacionExtra || ubicacionDe(stack) || 'navegador'
    const ruta = rutaActual()

    // La huella imita a la del servidor: qué se rompió, dónde y en qué pantalla.
    const huella = `${clase}|${ubicacion}|${ruta}`
    if (yaReportados.has(huella)) return
    yaReportados.add(huella)
    enviados += 1

    void fetch(BUZON, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mensaje: (err.message || 'error sin mensaje').slice(0, 500),
        ubicacion: ubicacion.slice(0, 200),
        ruta: ruta.slice(0, 200),
        stack: stack.slice(0, 8000),
        clase,
        navegador: navigator.userAgent.slice(0, 300),
      }),
      // El operador puede estar cerrando la pestaña justo cuando reventó: con
      // keepalive el navegador manda igual el pedido en vez de cancelarlo.
      keepalive: true,
    }).catch(() => {
      /* Si el buzón no contesta no hay nada más que hacer: no se reintenta ni
         se loguea, o el fallo del reporte se reportaría a sí mismo. */
    })
  } catch {
    /* Ver el punto 2 del encabezado. */
  }
}

/**
 * Engancha los dos capturadores globales del navegador.
 *
 * `error` agarra las excepciones que nadie atrapó; `unhandledrejection`, las
 * promesas que fallaron sin `catch` — que en un panel con llamadas a la API son
 * la mitad de los errores reales y no aparecen por ningún otro lado.
 */
export function instalarCapturaDeErrores(): void {
  window.addEventListener('error', (ev) => {
    reportarError(
      ev.error ?? ev.message,
      'error',
      ev.filename ? `${ev.filename.split('/').pop()}:${ev.lineno}` : '',
    )
  })

  window.addEventListener('unhandledrejection', (ev) => {
    reportarError(ev.reason, 'promesa')
  })
}
