import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 빌드 결과(dist)는 Django가 /static/app/ 아래에서 서빙한다. 개발 서버는 API·관리 화면을 Django로 넘긴다.
const django = 'http://127.0.0.1:8000'

export default defineConfig({
  base: '/static/app/',
  plugins: [react()],
  build: { outDir: 'dist' },
  server: { proxy: { '/api': django, '/admin': django, '/static': django } },
})
