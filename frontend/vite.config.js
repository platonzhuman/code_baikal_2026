import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/chat': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/logs': 'http://localhost:8000',
      '/login': 'http://localhost:8000',
      '/schema': 'http://localhost:8000',
      '/history': 'http://localhost:8000',
    },
  },
})