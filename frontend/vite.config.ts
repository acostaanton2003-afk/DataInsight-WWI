import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', setupFiles: './src/tests/setup.ts', maxWorkers: 1 },
  build: { rollupOptions: { output: { manualChunks: (id) => /node_modules[\\/](echarts|zrender)[\\/]/.test(id) ? 'charts' : undefined } } },
});
