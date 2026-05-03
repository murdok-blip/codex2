import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 3100,
    strictPort: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 4100,
    strictPort: true,
  },
})
