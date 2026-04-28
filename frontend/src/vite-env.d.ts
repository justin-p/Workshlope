/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_AUTHJS_URL?: string
  readonly VITE_USER_REGISTRATION_ENABLED?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
