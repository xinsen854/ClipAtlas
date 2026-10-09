import { existsSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const finecutEntry = fileURLToPath(new URL('../modules/finecut/ui/src/index.ts', import.meta.url))
const finecutStub = fileURLToPath(new URL('./src/integrations/finecut/stub.ts', import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@finecut-ui': existsSync(finecutEntry) ? finecutEntry : finecutStub,
    },
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
