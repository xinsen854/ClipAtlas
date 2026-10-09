import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist-lan', rollupOptions: { input: resolve(__dirname, 'lan.html') } },
})
