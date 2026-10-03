import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 分析产物由后端 tools/serve_api.py 提供（/api 代理），前端不直接读文件。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
