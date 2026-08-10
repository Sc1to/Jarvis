import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/coding/',
  server: {
    proxy: {
      '/coding/api': {
        target: 'http://localhost:8012',
        rewrite: (path) => path.replace(/^\/coding\/api/, ''),
      },
    },
  },
})
