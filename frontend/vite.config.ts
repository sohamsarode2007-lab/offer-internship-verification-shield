import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/analyze': 'http://127.0.0.1:8000',
      '/report': 'http://127.0.0.1:8000',
      '/disputes': 'http://127.0.0.1:8000',
      '/indicators': 'http://127.0.0.1:8000',
      '/trends': 'http://127.0.0.1:8000',
      '/config': 'http://127.0.0.1:8000',
      '/sources': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/docs': 'http://127.0.0.1:8000',
      '/openapi.json': 'http://127.0.0.1:8000',
      '/redoc': 'http://127.0.0.1:8000',
    },
  },
})
