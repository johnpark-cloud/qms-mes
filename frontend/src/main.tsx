import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import koKR from 'antd/locale/ko_KR'
import dayjs from 'dayjs'
import 'dayjs/locale/ko'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './app.css'
import type { GridColumn } from './components/EditGrid'
import AppLayout from './layout/AppLayout'
import AuditLog from './pages/AuditLog'
import InspectPage from './pages/inspect/InspectPage'
import MeasurePage from './pages/inspect/MeasurePage'
import Login from './pages/Login'
import InspectionList from './pages/inspections/InspectionList'
import InspectionPage from './pages/inspections/InspectionPage'
import InspectionPrint from './pages/inspections/InspectionPrint'
import Overview from './pages/Overview'
import ItemList from './pages/items/ItemList'
import ItemPage from './pages/items/ItemPage'
import ImportPage from './pages/import/ImportPage'
import TablePage from './pages/master/TablePage'
import PlanList from './pages/plans/PlanList'
import PlanPage from './pages/plans/PlanPage'
import PlanPrint from './pages/plans/PlanPrint'
import SpecList from './pages/specs/SpecList'
import SpecPage from './pages/specs/SpecPage'
import SpecPrint from './pages/specs/SpecPrint'
import Memos from './pages/Memos'
import Todo from './pages/Todo'
import Trace from './pages/Trace'
import { useAppTheme } from './theme'

dayjs.locale('ko')

const PROCESS_COLUMNS: GridColumn[] = [
  { key: 'code', label: '공정 코드', kind: 'text', width: 200 },
  { key: 'name', label: '공정명', kind: 'text' },
]
const RULE_COLUMNS: GridColumn[] = [
  { key: 'customer', label: '고객사', kind: 'text' },
  { key: 'containment_hours', label: '봉쇄(D3) 기한(시간)', kind: 'number', width: 180 },
  { key: 'corrective_days', label: '대책(D5) 기한(일)', kind: 'number', width: 180 },
]

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
            <Route path="plans/:id/print" element={<PlanPrint />} />
            <Route path="inspections/:id/print" element={<InspectionPrint />} />
            <Route element={<AppLayout />}>
              <Route path="overview" element={<Overview />} />
              <Route path="todo" element={<Todo />} />
              <Route path="specs" element={<SpecList />} />
              <Route path="specs/:id" element={<SpecPage />} />
              <Route path="plans" element={<PlanList />} />
              <Route path="plans/:id" element={<PlanPage />} />
              <Route path="import" element={<ImportPage />} />
              <Route path="items" element={<ItemList />} />
              <Route path="items/:id" element={<ItemPage />} />
              <Route path="processes" element={<TablePage title="공정" endpoint="/api/core/processes/" exportName="공정" columns={PROCESS_COLUMNS} />} />
              <Route path="customer-rules" element={<TablePage title="고객사별 8D 기한" endpoint="/api/qms/customer-rules/" exportName="고객사별 8D 기한" columns={RULE_COLUMNS} />} />
              <Route path="inspect" element={<InspectPage />} />
              <Route path="inspect/:lotId/:specId" element={<MeasurePage />} />
              <Route path="inspections" element={<InspectionList />} />
              <Route path="inspections/:id" element={<InspectionPage />} />
              <Route path="trace" element={<Trace />} />
              <Route path="memos" element={<Memos />} />
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
