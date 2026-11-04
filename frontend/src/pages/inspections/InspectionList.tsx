import { useQuery } from '@tanstack/react-query'
import { Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { InspectionDetail, InspectionRow, InspectionSummary } from '../../api/inspect'
import { INSPECTION_TYPES, type Page } from '../../api/specs'
import DataList from '../../components/DataList'
import Tile from '../../components/Tile'
import { addRecent } from '../../lib/recent'

const COLOR = { 합격: 'green', 불합격: 'red', 미판정: 'orange' } as const

const COLUMNS: ColumnsType<InspectionRow> = [
  { title: '검사 일시', dataIndex: 'inspected_at', render: (v: string) => v.slice(0, 16).replace('T', ' ') },
  { title: 'LOT', dataIndex: 'lot_number' },
  { title: '품번', dataIndex: 'item_code' },
  { title: '협력사', dataIndex: 'supplier' },
  { title: '검사기준', dataIndex: 'spec_title' },
  { title: '검사자', dataIndex: 'inspector' },
  { title: '판정', dataIndex: 'result_display', render: (v: InspectionRow['result_display']) => <Tag color={COLOR[v]}>{v}</Tag> },
  { title: '부적합', dataIndex: 'nc_number' },
]

const exportHref = (tab: string, q: string) => `/api/qms/inspections/?tab=${tab}&q=${encodeURIComponent(q)}&export=xlsx`

// 합격률은 판정된 것만 분모로 센다(미판정 제외).
function Summary({ s }: { s: InspectionSummary }) {
  const judged = s.passed + s.failed
  const tiles = [
    { title: '전체', tile: { value: s.total, sub: s.pending ? `미판정 ${s.pending}건` : '' } },
    { title: '합격', tile: { value: s.passed, tone: s.passed ? 'positive' : '' } },
    { title: '불합격', tile: { value: s.failed, tone: s.failed ? 'negative' : '' } },
    { title: '합격률', tile: { value: judged ? `${((s.passed / judged) * 100).toFixed(1)}%` : '—', sub: '판정된 검사 기준' } },
  ]
  return (
    <div data-summary style={{ display: 'grid', gap: 12, marginBottom: 16, gridTemplateColumns: 'repeat(auto-fill, minmax(min(160px, 100%), 1fr))' }}>
      {tiles.map((t) => <Tile key={t.title} title={t.title} tile={t.tile} />)}
    </div>
  )
}

function Peek({ row }: { row: InspectionRow }) {
  const { data } = useQuery({ queryKey: ['inspection', row.id], queryFn: () => api<InspectionDetail>(`/api/qms/inspections/${row.id}/`) })
  return (
    <div className="prop-grid">
      <span>LOT</span>
      <span>{row.lot_number}</span>
      <span>품번</span>
      <span>
        {row.item_code} · {row.item_name}
      </span>
      <span>협력사</span>
      <span>{row.supplier}</span>
      <span>검사기준</span>
      <span>{row.spec_title}</span>
      <span>검사자</span>
      <span>{row.inspector}</span>
      <span>판정</span>
      <span>{row.result_display}</span>
      <span>측정 항목</span>
      <span>{data ? `${data.measurements.length}개` : '불러오는 중'}</span>
    </div>
  )
}

export default function InspectionList() {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const t = sp.get('tab')
  const tab = INSPECTION_TYPES.some((x) => x.value === t) ? (t as string) : INSPECTION_TYPES[0].value
  const [summary, setSummary] = useState<InspectionSummary | null>(null)
  const first = useRef(0) // 늦게 온 이전 탭·검색의 요약이 새 요약을 덮지 않게 한다
  // 요약은 첫 쪽 응답에 함께 온다(탭·검색 반영).
  const fetchPage = useCallback(async (tab: string, q: string, page: number) => {
    const my = page === 1 ? ++first.current : 0
    const r = await api<Page<InspectionRow> & { summary: InspectionSummary }>(`/api/qms/inspections/?tab=${tab}&q=${encodeURIComponent(q)}&page=${page}`)
    if (my && my === first.current) setSummary(r.summary)
    return r
  }, [])
  return (
    <div>
      <h1 className="page-title">검사 기록</h1>
      {summary && <Summary s={summary} />}
      <DataList<InspectionRow>
        columns={COLUMNS}
        tabs={INSPECTION_TYPES.map((x) => ({ key: x.value, label: x.label }))}
        tab={tab}
        onTab={(k) => setSp({ tab: k }, { replace: true })}
        fetchPage={fetchPage}
        exportHref={exportHref}
        peek={(r) => <Peek row={r} />}
        onOpen={(r) => {
          addRecent({ label: `${r.lot_number} ${r.spec_title}`, href: `/app/inspections/${r.id}` })
          nav(`/inspections/${r.id}`)
        }}
        rowKey={(r) => r.id}
      />
    </div>
  )
}
