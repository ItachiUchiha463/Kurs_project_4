import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    // у розробці /api (разом із WebSocket) іде на бекенд; у проді це робить Caddy
    proxy: { '/api': { target: 'http://localhost:8000', ws: true } },
  },
})
