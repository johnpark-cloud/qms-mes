import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 빌드 결과(dist)는 Django가 /static/app/ 아래에서 서빙한다. 개발 서버는 API·관리 화면을 Django로 넘긴다.
const django = 'http://127.0.0.1:8000'

// 개발 서버(5173)는 /app/ 에서 열어 라우터 basename 과 맞추고, /static 프록시가 Vite 자체 파일 요청을 가로채지 않게 한다.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/app/' : '/app/',
  plugins: [react()],
  build: { outDir: 'dist' },
  server: { proxy: { '/api': django, '/admin': django, '/static': django } },
}))
