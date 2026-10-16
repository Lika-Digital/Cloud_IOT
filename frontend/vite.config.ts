import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API_TARGET exists for the e2e run (playwright.config.ts), which points it at a closed port so
// no spec can reach whatever backend happens to be on :8000. Everyone else gets the default.
const apiTarget = process.env.API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // '/api/', with the slash, as nginx on the cabinet (`location /api/`): a bare '/api' is a
      // string prefix and also caught the PAGE /api-gateway, which then never loaded in dev or e2e.
      '/api/': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: apiTarget.replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
