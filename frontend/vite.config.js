import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'

// Built files go into the Python package so `pip install` ships them; `ew serve` serves ew/web.
export default defineConfig({
  plugins: [preact()],
  base: './',
  build: { outDir: '../ew/web', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})
