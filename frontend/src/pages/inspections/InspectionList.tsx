import { useQuery } from '@tanstack/react-query'
import { Button, Descriptions, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { InspectionDetail, InspectionRow, InspectionSummary } from '../../api/inspect'
import { INSPECTION_TYPES, type Page } from '../../api/specs'
import DataList, { type ListFilter } from '../../components/DataList'
import Tile from '../../components/Tile'
import { addRecent } from '../../lib/recent'

const COLOR = { 합격: 'green', 불합격: 'red', 미판정: 'orange' } as const

const COLUMNS: ColumnsType<InspectionRow> = [
  { title: '검사 일시', dataIndex: 'inspected_at', sorter: true, render: (v: string) => v.slice(0, 16).replace('T', ' ') },
  { title: 'LOT', dataIndex: 'lot_number', sorter: true },
  { title: '품번', dataIndex: 'item_code', sorter: true },
  { title: '공급자', dataIndex: 'supplier', sorter: true },
  { title: '검사기준', dataIndex: 'spec_title', sorter: true },
  { title: '검사자', dataIndex: 'inspector', sorter: true },
  { title: '판정', dataIndex: 'result_display', key: 'result', sorter: true, render: (v: InspectionRow['result_display']) => <Tag color={COLOR[v]}>{v}</Tag> },
  { title: '부적합', dataIndex: 'nc_number' },
]

const exportHref = (tab: string, q: string, extra: string) => `/api/qms/inspections/?tab=${tab}&q=${encodeURIComponent(q)}${extra}&export=xlsx`

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

// 미리보기: 판정 머리 → 검사 정보 표 → 측정 결과 표. 전체 화면을 열지 않아도 무엇을 어떻게 판정했는지 한 번에 보인다.
function Peek({ row }: { row: InspectionRow }) {
  const { data } = useQuery({ queryKey: ['inspection', row.id], queryFn: () => api<InspectionDetail>(`/api/qms/inspections/${row.id}/`) })
  const ms = data?.measurements ?? []
  const ng = ms.filter((m) => m.passed === false).length
  const ok = ms.filter((m) => m.passed === true).length
  const time = row.inspected_at.slice(0, 16).replace('T', ' ')
  return (
    <div style={{ display: 'grid', gap: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>{row.lot_number}</Typography.Title>
          <Typography.Text type="secondary">{row.spec_title}</Typography.Text>
        </div>
        <Tag color={COLOR[row.result_display]} style={{ fontSize: 16, padding: '4px 14px', marginInlineEnd: 0 }}>{row.result_display}</Tag>
      </div>
      <Descriptions size="small" bordered column={2} title="검사 정보"
        items={[
          { key: 'item', label: '품번 · 품명', span: 2, children: `${row.item_code} · ${row.item_name}` },
          { key: 'supplier', label: '공급자', children: row.supplier || '—' },
          { key: 'qty', label: 'LOT 수량', children: data?.lot.qty ?? '—' },
          { key: 'spec', label: '검사기준', children: data ? `Rev.${data.spec.revision ?? '—'}` : '—' },
          { key: 'sampling', label: '샘플링', children: data?.spec.sampling || '—' },
          { key: 'inspector', label: '검사자', children: row.inspector || '—' },
          { key: 'at', label: '검사 일시', children: time },
          { key: 'nc', label: '부적합', children: data?.nonconformance ? <a href={data.nonconformance.url}>{data.nonconformance.number}</a> : '없음' },
          { key: 'capa', label: 'CAPA', children: data?.capa?.length ? data.capa.map((c) => <a key={c.id} href={c.url} style={{ marginInlineEnd: 8 }}>{c.number}</a>) : '없음' },
        ]}
      />
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
          <Typography.Text strong style={{ fontSize: 16 }}>측정 결과</Typography.Text>
          <Typography.Text type="secondary">{data ? `${ms.length}항목 · 합격 ${ok} · 불합격 ${ng}` : '불러오는 중'}</Typography.Text>
        </div>
        <Table size="small" pagination={false} loading={!data} rowKey={(_, i) => String(i)} dataSource={ms}
          rowClassName={(m) => (m.passed === false ? 'row-ng' : '')}
          columns={[
            { title: '항목', dataIndex: 'name', render: (v: string, m) => <>{v}{m.special ? <Tag style={{ marginInlineStart: 6 }}>{m.special}</Tag> : null}</> },
            { title: '규격', dataIndex: 'spec_text' },
            { title: '측정값', dataIndex: 'value', align: 'right', render: (v: string | null) => v ?? '—' },
            { title: '판정', dataIndex: 'passed', align: 'center', width: 64, render: (v: boolean | null) => (v === null ? '—' : <Tag color={v ? 'green' : 'red'} style={{ marginInlineEnd: 0 }}>{v ? 'OK' : 'NG'}</Tag>) },
          ]}
        />
      </div>
    </div>
  )
}

export default function InspectionList() {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const t = sp.get('tab')
  const tab = INSPECTION_TYPES.some((x) => x.value === t) ? (t as string) : INSPECTION_TYPES[0].value
  const [summary, setSummary] = useState<InspectionSummary | null>(null)
  const [filters, setFilters] = useState<ListFilter[]>([])
  const first = useRef(0) // 늦게 온 이전 탭·검색의 요약이 새 요약을 덮지 않게 한다
  // 요약은 첫 쪽 응답에 함께 온다(탭·검색 반영).
  const fetchPage = useCallback(async (tab: string, q: string, page: number, extra: string) => {
    const my = page === 1 ? ++first.current : 0
    const r = await api<Page<InspectionRow> & { summary: InspectionSummary; filters: ListFilter[] }>(
      `/api/qms/inspections/?tab=${tab}&q=${encodeURIComponent(q)}&page=${page}${extra}`,
    )
    if (my && my === first.current) {
      setSummary(r.summary)
      setFilters(r.filters)
    }
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
        filters={filters}
        toolbar={<Button onClick={() => nav(`/nc-new?origin=${tab}`)}>부적합 등록</Button>}
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
