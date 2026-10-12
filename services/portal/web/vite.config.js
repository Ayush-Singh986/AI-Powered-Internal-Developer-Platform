import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8501',
      '/healthz': 'http://localhost:8501',
    },
  },
});