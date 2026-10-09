import { existsSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const repoRoot = fileURLToPath(new URL('..', import.meta.url))
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
    fs: {
      allow: [repoRoot],
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    include: [
      'src/**/*.test.{ts,tsx}',
      '../modules/finecut/ui/tests/**/*.test.ts',
    ],
    // AntD-heavy pages render slowly under jsdom on loaded machines; several
    // tests were timing out at the 5s default while passing standalone.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
})
