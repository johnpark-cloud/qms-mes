import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Select, Space, Spin, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'

/** 분석 화면: 품질 KPI(/app/kpi)·공급자 평가(/app/suppliers)·SPC 관리도(/app/spc/:id). 계산은 서버(qms/kpi.py·spc.py) */

const n = (v: number | null | undefined, d = 1) => (v == null ? '—' : v.toLocaleString('ko-KR', { maximumFractionDigits: d }))

function Months({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <Select value={value} onChange={onChange} style={{ width: 120 }}
      options={[3, 6, 12, 24].map((m) => ({ value: m, label: `최근 ${m}개월` }))} />
  )
}

function useMonths(): [number, (v: number) => void] {
  const [sp, setSp] = useSearchParams()
  return [Number(sp.get('months')) || 6, (v) => setSp({ months: String(v) }, { replace: true })]
}

function Err({ e }: { e: unknown }) {
  return e ? <Alert type="error" showIcon title={e instanceof ApiError ? e.detail : '불러오지 못했습니다.'} style={{ marginBottom: 16 }} /> : null
}

interface KpiRow { month: string; shipped: number | null; claims: number; ppm: number | null; fpy: number | null; d3_on_time: number | null; copq: number | null }
interface Pareto { defect_type: string; n: number; qty: number | null; share: number; cum: number }
interface Yield { process: string; n: number; input: number | null; good: number | null; defect: number | null; yield: number | null }
interface KpiData { months: number; show: { quality: boolean; yield: boolean }; rows: KpiRow[]; pareto: Pareto[]; yields: Yield[] }

export function Kpi() {
  const [months, setMonths] = useMonths()
  const q = useQuery({ queryKey: ['kpi', months], queryFn: () => api<KpiData>(`/api/qms/kpi/?months=${months}`) })
  const d = q.data
  const cur = d?.rows[d.rows.length - 1]
  const cols: ColumnsType<KpiRow> = [
    { title: '월', dataIndex: 'month' },
    { title: '출하 수량', dataIndex: 'shipped', align: 'right', render: (v) => n(v, 0) },
    { title: '클레임', dataIndex: 'claims', align: 'right' },
    { title: '고객 PPM', dataIndex: 'ppm', align: 'right', render: (v) => n(v, 0) },
    { title: '직행률(%)', dataIndex: 'fpy', align: 'right', render: (v) => n(v) },
    { title: '8D 봉쇄 기한 준수(%)', dataIndex: 'd3_on_time', align: 'right', render: (v) => n(v) },
    { title: '실패비용(원)', dataIndex: 'copq', align: 'right', render: (v) => n(v, 0) },
  ]
  return (
    <>
      <h1 className="page-title">품질 KPI</h1>
      <Space style={{ marginBottom: 16 }} wrap>
        <Months value={months} onChange={setMonths} />
        <Link to="/suppliers"><Button>공급자 평가</Button></Link>
      </Space>
      <Err e={q.error} />
      {q.isLoading && <Spin />}
      {d && !d.show.quality && !d.show.yield && <Alert type="info" showIcon title="소속 부서의 KPI가 없습니다." />}
      {d?.show.quality && (
        <>
          {cur && (
            <div className="hub-grid" style={{ marginBottom: 16 }}>
              {([['고객 PPM', n(cur.ppm, 0)], ['직행률 %', n(cur.fpy)], ['8D 봉쇄 기한 준수 %', n(cur.d3_on_time)], ['실패비용 원', n(cur.copq, 0)]] as const)
                .map(([t, v]) => <Card key={t} size="small" title={`${t} · ${cur.month}`}><span style={{ fontSize: 24 }}>{v}</span></Card>)}
            </div>
          )}
          <h2>월별 추이</h2>
          <Table rowKey="month" size="small" columns={cols} dataSource={d.rows} pagination={false} scroll={{ x: true }} />
          <h2>부적합 유형 파레토 <small>기간 전체</small></h2>
          <Table rowKey="defect_type" size="small" pagination={false} dataSource={d.pareto} scroll={{ x: true }} columns={[
            { title: '부적합 유형', dataIndex: 'defect_type' },
            { title: '건수', dataIndex: 'n', align: 'right' },
            { title: '수량', dataIndex: 'qty', align: 'right', render: (v) => n(v, 0) },
            { title: '비율(%)', dataIndex: 'share', align: 'right', render: (v) => n(v) },
            { title: '누적(%)', dataIndex: 'cum', align: 'right', render: (v) => n(v) },
          ]} />
        </>
      )}
      {d?.show.yield && (
        <>
          <h2>공정별 수율 <small>작업 실적, 기간 전체</small></h2>
          <Table rowKey="process" size="small" pagination={false} dataSource={d.yields} scroll={{ x: true }} columns={[
            { title: '공정', dataIndex: 'process' },
            { title: '실적', dataIndex: 'n', align: 'right' },
            { title: '투입', dataIndex: 'input', align: 'right', render: (v) => n(v, 0) },
            { title: '양품', dataIndex: 'good', align: 'right', render: (v) => n(v, 0) },
            { title: '불량', dataIndex: 'defect', align: 'right', render: (v) => n(v, 0) },
            { title: '수율(%)', dataIndex: 'yield', align: 'right', render: (v) => n(v) },
          ]} />
        </>
      )}
    </>
  )
}

interface SupRow { name: string; lots: number; received: number | null; inspections: number; fail_rate: number | null; ppm: number | null; scars: number; scar_on_time: number | null }

export function Suppliers() {
  const [months, setMonths] = useMonths()
  const q = useQuery({ queryKey: ['suppliers', months], queryFn: () => api<{ rows: SupRow[] }>(`/api/qms/suppliers/?months=${months}`) })
  return (
    <>
      <h1 className="page-title">공급자 평가</h1>
      <Space style={{ marginBottom: 16 }} wrap>
        <Months value={months} onChange={setMonths} />
        <Link to="/r/qms/scar"><Button>SCAR 목록</Button></Link>
      </Space>
      <Err e={q.error} />
      <Table rowKey="name" size="small" loading={q.isLoading} pagination={false} dataSource={q.data?.rows} scroll={{ x: true }} columns={[
        { title: '공급자', dataIndex: 'name' },
        { title: '입고 LOT', dataIndex: 'lots', align: 'right' },
        { title: '입고 수량', dataIndex: 'received', align: 'right', render: (v) => n(v, 0) },
        { title: '수입검사', dataIndex: 'inspections', align: 'right' },
        { title: '불합격률(%)', dataIndex: 'fail_rate', align: 'right', render: (v) => n(v), sorter: (a, b) => (a.fail_rate ?? -1) - (b.fail_rate ?? -1) },
        { title: '부적합 PPM', dataIndex: 'ppm', align: 'right', render: (v) => n(v, 0) },
        { title: 'SCAR', dataIndex: 'scars', align: 'right' },
        { title: 'SCAR 회신 준수(%)', dataIndex: 'scar_on_time', align: 'right', render: (v) => n(v) },
      ]} />
    </>
  )
}

interface SpcPoint { inspection: number; lot: string; lot_id: number; inspected_at: string | null; xbar: number; r: number | null; alarms: string[]; nc_url: string | null }
interface SpcData {
  title: string; lsl: number | null; usl: number | null; unit: string; special: string; error?: string
  kind?: string; n?: number; sigma?: number; cpk?: number | null; limits?: Record<string, number>; points?: SpcPoint[]
}

function Chart({ pts, lim }: { pts: SpcPoint[]; lim: Record<string, number> }) {
  const W = 1080, H = 260, P = 30
  const vals = [lim.lcl, lim.ucl, ...pts.map((p) => p.xbar)]
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1
  const y = (v: number) => P + ((hi - v) / span) * (H - 2 * P)
  const x = (i: number) => P + (i * (W - 2 * P)) / Math.max(pts.length - 1, 1)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }} role="img" aria-label="관리도">
      {(['ucl', 'cl', 'lcl'] as const).map((k) => (
        <g key={k}>
          <line x1={P} x2={W - P} y1={y(lim[k])} y2={y(lim[k])} stroke={k === 'cl' ? 'var(--ant-color-text-tertiary, #888)' : 'var(--ant-color-error, #d4380d)'} strokeDasharray={k === 'cl' ? '' : '4 3'} />
          <text x={W - P + 2} y={y(lim[k]) + 4} fontSize="11" fill="currentColor">{k.toUpperCase()}</text>
        </g>
      ))}
      <polyline fill="none" stroke="var(--ant-color-primary, #1677ff)" strokeWidth="1.5" points={pts.map((p, i) => `${x(i)},${y(p.xbar)}`).join(' ')} />
      {pts.map((p, i) => (
        <circle key={p.inspection} cx={x(i)} cy={y(p.xbar)} r={p.alarms.length ? 5 : 3} fill={p.alarms.length ? 'var(--ant-color-error, #d4380d)' : 'var(--ant-color-primary, #1677ff)'}>
          <title>{`${p.lot} · ${p.xbar}${p.alarms.length ? ' · ' + p.alarms.join(', ') : ''}`}</title>
        </circle>
      ))}
    </svg>
  )
}

export function Spc() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['spc', id], queryFn: () => api<SpcData>(`/api/qms/spc/${id}/`) })
  const d = q.data
  const one = d?.n === 1
  return (
    <>
      <h1 className="page-title">{d?.title ?? 'SPC 관리도'}</h1>
      <Err e={q.error} />
      {q.isLoading && <Spin />}
      {d?.error && <Alert type="info" showIcon title={d.error} />}
      {d?.points && d.limits && (
        <>
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag>{d.kind}</Tag>
            {d.special && <Tag color="red">특별특성 {d.special}</Tag>}
            <span>규격 {n(d.lsl, 4)} ~ {n(d.usl, 4)} {d.unit}</span>
            <span>σ {n(d.sigma, 4)}</span>
            <span>Cpk {n(d.cpk, 2)}</span>
            <span>UCL {n(d.limits.ucl, 4)} · CL {n(d.limits.cl, 4)} · LCL {n(d.limits.lcl, 4)}</span>
          </Space>
          <Card size="small" style={{ marginBottom: 16 }}><Chart pts={d.points} lim={d.limits} /></Card>
          <Table rowKey="inspection" size="small" pagination={false} dataSource={[...d.points].reverse()} scroll={{ x: true }} columns={[
            { title: '검사(LOT)', render: (_, p) => <Link to={`/inspections/${p.inspection}`}>{p.lot}</Link> },
            { title: '검사일', dataIndex: 'inspected_at', render: (v) => (v ? String(v).slice(0, 16).replace('T', ' ') : '—') },
            { title: one ? 'X' : 'X̄', dataIndex: 'xbar', align: 'right', render: (v) => n(v, 4) },
            { title: one ? 'MR' : 'R', dataIndex: 'r', align: 'right', render: (v) => n(v, 4) },
            { title: '경보', render: (_, p) => (p.alarms.length ? (
              <Space wrap>{p.alarms.map((a) => <Tag key={a} color="red">{a}</Tag>)}
                {p.nc_url && <Link to={p.nc_url.slice(4)}>부적합 등록</Link>}</Space>) : '') },
          ]} />
        </>
      )}
    </>
  )
}
