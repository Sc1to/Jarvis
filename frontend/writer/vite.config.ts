import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  base: '/writer/',
  server: {
    port: 5177,
    proxy: {
      '/writer/api': {
        target: 'http://localhost:8011',
        rewrite: (path) => path.replace('/writer/api', ''),
      },
    },
  },
})
