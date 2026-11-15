import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import {loadEnv} from 'vite';
import {publicAuthConfig} from './src/lib/authConfig.ts';
export default defineConfig(({mode})=>{
  const values=loadEnv(mode,'.','VITE_');
  const key=values.VITE_SUPABASE_PUBLISHABLE_KEY ?? '';
  const url=values.VITE_SUPABASE_URL ?? '';
  // Fail before bundling a mistakenly configured private credential. Never echo it.
  if(key)publicAuthConfig(url,key);
  return {
  plugins: [react()],
  test: { environment: 'jsdom', setupFiles: './src/tests/setup.ts', maxWorkers: 1 },
  build: { rollupOptions: { output: { manualChunks: (id) => /node_modules[\\/](echarts|zrender)[\\/]/.test(id) ? 'charts' : undefined } } },
  };
});
