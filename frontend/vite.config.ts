import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端地址：默认 7968，可用环境变量 VITE_API_TARGET 覆盖
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:7968'

// Vite 配置：开发端口 5173，并将 /api 代理到后端 FastAPI 服务
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // 允许使用 @/ 指向 src 目录
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // 监听所有网卡，便于远程调试访问（默认即对外开放；不需要时用 --host localhost 覆盖）
    host: true,
    // 放开 Host 头校验，允许通过 IP / 主机名 / 隧道访问
    allowedHosts: true,
    proxy: {
      // 前端统一使用相对路径 fetch('/api/...')，由此代理转发到后端
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
