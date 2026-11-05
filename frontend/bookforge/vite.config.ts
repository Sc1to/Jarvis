import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/bookforge/',
  server: {
    port: 5178,
    proxy: {
      '/bookforge/api': {
        target: 'http://localhost:8100',
        rewrite: (path) => path.replace('/bookforge', ''),
      },
    },
  },
})
