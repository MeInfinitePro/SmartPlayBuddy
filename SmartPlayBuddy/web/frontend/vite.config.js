import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// 开发：npm run dev（默认 http://localhost:5173）
//   - /api 代理到后端（需同时运行 python web/backend/app.py，默认 8765）
// 生产：npm run build → dist/ 由后端静态托管
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
