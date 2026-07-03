import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// В dev режиме /api проксируется на локальный backend (порт 5000).
// В проде nginx сам проксирует /api на сервис backend.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        timeout: 200000,
      },
    },
  },
})
