import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './', // 相对路径，适配 Electron file:// 加载
  build: { outDir: 'dist', assetsDir: 'assets' },
  server: { port: 5173, strictPort: true },
});
