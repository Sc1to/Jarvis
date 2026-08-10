import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/autocoder/',
  server: {
    port: 5176,
    proxy: {
      '/autocoder/api': {
        target: 'http://localhost:8050',
        rewrite: (path) => path.replace(/^\/autocoder\/api/, ''),
        ws: true,
      },
    },
  },
})
