/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEMO_MODE?: string;
  readonly VITE_PORTFOLIO_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
