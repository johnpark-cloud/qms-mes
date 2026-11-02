import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import koKR from 'antd/locale/ko_KR'
import dayjs from 'dayjs'
import 'dayjs/locale/ko'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './layout/AppLayout'
import Login from './pages/Login'
import { useAppTheme } from './theme'

dayjs.locale('ko')

// 화면 데이터는 늘 서버가 맞다: 창으로 돌아와도 자동으로 다시 받지 않고, 실패 재시도도 하지 않는다.
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })

// 실제 화면(종합현황·내 할 일)은 다음 작업에서 이 자리에 들어간다.
const Placeholder = ({ title }: { title: string }) => <h2 style={{ margin: 0 }}>{title}</h2>

function App() {
  const theme = useAppTheme()
  return (
    <ConfigProvider locale={koKR} theme={theme}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename="/app">
          <Routes>
            <Route path="login" element={<Login />} />
            <Route element={<AppLayout />}>
              <Route path="overview" element={<Placeholder title="공장 종합현황" />} />
              <Route path="todo" element={<Placeholder title="내 할 일" />} />
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
