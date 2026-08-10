import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/writer/',
  server: {
    port: 5177,
    proxy: {
      '/writer/api': {
        target: 'http://localhost:8011',
        rewrite: (path) => path.replace(/^\/writer\/api/, ''),
      },
    },
  },
})
