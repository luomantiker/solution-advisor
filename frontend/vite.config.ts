import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // 开发时复用本地 Compose 的 Web 网关：它同时处理 Cookie 和 /api 转发，
  // 使 Vite 预览与部署入口的鉴权行为一致。
  server: { proxy: { '/api': 'http://127.0.0.1:8080' } },
})
