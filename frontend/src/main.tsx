import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import koKR from 'antd/locale/ko_KR'
import dayjs from 'dayjs'
import 'dayjs/locale/ko'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './app.css'
import AppLayout from './layout/AppLayout'
import AuditLog from './pages/AuditLog'
import Login from './pages/Login'
import Overview from './pages/Overview'
import SpecList from './pages/specs/SpecList'
import SpecPage from './pages/specs/SpecPage'
import SpecPrint from './pages/specs/SpecPrint'
import Todo from './pages/Todo'
import { useAppTheme } from './theme'

dayjs.locale('ko')

// 화면 데이터는 늘 서버가 맞다: 창으로 돌아와도 자동으로 다시 받지 않고, 실패 재시도도 하지 않는다.
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })

function App() {
  const theme = useAppTheme()
  return (
    <ConfigProvider locale={koKR} theme={theme}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename="/app">
          <Routes>
            <Route path="login" element={<Login />} />
            <Route path="specs/:id/print" element={<SpecPrint />} />
            <Route element={<AppLayout />}>
              <Route path="overview" element={<Overview />} />
              <Route path="todo" element={<Todo />} />
              <Route path="specs" element={<SpecList />} />
              <Route path="specs/:id" element={<SpecPage />} />
              <Route path="audit" element={<AuditLog />} />
            </Route>
            <Route path="*" element={<Navigate to="/todo" replace />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ConfigProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
