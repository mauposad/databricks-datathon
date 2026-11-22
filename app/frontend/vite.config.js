import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

const here = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  root: here,
  plugins: [react()],
  build: {
    outDir: '../static', emptyOutDir: true,
    // Split stable vendor code from app code so the app chunk stays small and caches well.
    rollupOptions: {
      output: {
        manualChunks: {
          map: ['leaflet', 'react-leaflet'],
          motion: ['motion/react'],
          ui: ['@radix-ui/react-select', '@radix-ui/react-popover', '@radix-ui/react-tooltip', '@radix-ui/react-slider',
               '@radix-ui/react-switch', '@radix-ui/react-dialog', 'cmdk', 'sonner', 'lucide-react'],
        },
      },
    },
  },
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
})
