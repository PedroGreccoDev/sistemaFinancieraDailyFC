/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" activa el modo demo con datos falsos locales (ver src/api/mock.ts). */
  readonly VITE_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
