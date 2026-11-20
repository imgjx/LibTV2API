import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端与后端同源部署：API 基址在 src/api.js 中固定为 /api/v1，
// 与旧版 panel.html 完全一致，未做任何路径改动。
// 构建产物输出到本地 dist/，由 FastAPI 面板服务托管（或任意静态服务器 + 反代 /api）。
export default defineConfig({
  plugins: [vue()],
  // 绝对路径便于同源部署：后端在 / 和 /panel 都返回 index.html，
  // 资源统一走 /assets/*（由 FastAPI 挂载 front/dist/assets）。
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    // 本地开发时把 /api 代理到后端 8000 端口，保持前端代码里的路径不变
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
