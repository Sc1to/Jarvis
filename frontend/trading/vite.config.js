import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/trading/',
  server: {
    proxy: {
      '/trading/audit': {
        target: 'http://localhost:8031',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/trading\/audit/, '/audit'),
      },
      '/trading/api': {
        target: 'http://localhost:8030',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/trading\/api/, ''),
      },
    },
  },
})
