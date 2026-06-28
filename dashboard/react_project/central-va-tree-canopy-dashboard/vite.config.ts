import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Sets base path to match the GitHub repository name in production
  //base: process.env.NODE_ENV === 'production' ? '/central-va-tree-canopy-dashboard/' : '/',
  //base: process.env.NODE_ENV === 'production' ? '/' : '/',
  base: '/',
  optimizeDeps: {
    include: ['plotly.js'], // Forces Vite to pre-bundle Plotly correctly
  }
})
