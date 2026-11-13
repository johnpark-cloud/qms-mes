import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Spin, Table } from 'antd'
import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import type { InspectionDetail } from '../../api/inspect'
import MemoPanel from '../../components/MemoPanel'
import AttachmentPanel from '../../components/AttachmentPanel'
import RelationsPanel from '../../components/RelationsPanel'
import RecordPage from '../../components/RecordPage'
import { center, decimalsOf, fmtNum, specPosition } from '../../lib/num'
import { addRecent } from '../../lib/recent'

type M = InspectionDetail['measurements'][number]

const dec = (m: M) => m.decimals ?? decimalsOf(m.lsl, m.usl)
const dash = <span className="num-quiet">—</span>
const VERDICT = { 합격: 'verdict-pass', 불합격: 'verdict-fail', 미판정: 'verdict-none' } as const

// 계수형은 한계·단위가 없으므로 「—」, 판정은 서버 passed 값을 그대로 보인다.
const COLUMNS = [
  { title: '항목', key: 'name', render: (_: unknown, m: M) => <>{m.name}{m.special && <span className="cc-tag">{m.special}</span>}</> },
  { title: '하한', key: 'lsl', align: 'right' as const,className: 'num', render: (_: unknown, m: M) => (m.is_variable && m.lsl != null ? fmtNum(m.lsl, dec(m)) : dash) },
  { title: '기준(중앙)', key: 'center', align: 'right' as const, className: 'num num-quiet', render: (_: unknown, m: M) => (m.is_variable ? center(m.lsl, m.usl, dec(m)) : '—') },
  { title: '상한', key: 'usl', align: 'right' as const,className: 'num', render: (_: unknown, m: M) => (m.is_variable && m.usl != null ? fmtNum(m.usl, dec(m)) : dash) },
  { title: '단위', key: 'unit', render: (_: unknown, m: M) => (m.is_variable && m.unit ? m.unit : dash) },
  { title: '측정값', key: 'value', align: 'right' as const,className: 'num', render: (_: unknown, m: M) => (m.is_variable ? fmtNum(m.value, dec(m)) : (m.value ?? '—')) },
  {
    title: '위치',
    key: 'pos',
    render: (_: unknown, m: M) => {
      const p = m.is_variable ? specPosition(m.lsl, m.usl, m.value) : null
      return p ? (
        <div className="pos-bar" role="img" aria-label={`규격 안 위치 ${Math.round(p.pct)}%`}>
          <span className={`pos-dot pos-${p.tone}`} style={{ left: `${p.pct}%` }} />
        </div>
      ) : null
    },
  },
  { title: '판정', key: 'passed', render: (_: unknown, m: M) => (m.passed === null ? '미판정' : <span className={m.passed ? 'text-pass' : 'text-fail'}>{m.passed ? '합격' : '불합격'}</span>) },
  { title: '계측기', key: 'gauge', render: (_: unknown, m: M) => (m.gauge ? `${m.gauge}${m.gauge_name ? ` ${m.gauge_name}` : ''}` : '') },
]

export default function InspectionPage() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['inspection', id], queryFn: () => api<InspectionDetail>(`/api/qms/inspections/${id}/`) })
  const d = q.data
  useEffect(() => {
    if (d) addRecent({ label: d.title, href: `/app/inspections/${d.id}` })
  }, [d])
  if (q.isError) return <Alert type="error" message={q.error instanceof ApiError ? q.error.detail : '검사 기록을 불러오지 못했습니다.'} style={{ margin: 16 }} />
  if (!d) return <Spin />
  const s = d.spec
  return (
    <RecordPage
      title={d.title}
      status={d.status}
      lead={<span className={`verdict ${VERDICT[d.status]}`}>{d.status}</span>}
      // 판정된 검사는 고칠 수 없으므로 편집 버튼이 없다.
      actions={<Button type="primary" onClick={() => nav(`/inspections/${id}/print`)}>인쇄/PDF</Button>}
      record={{ ct: 'qms.inspection', id }}
      menu={[
        { key: 'xlsx', label: <a href={`/api/qms/inspections/${id}/document/?export=xlsx`} download>엑셀 받기</a> },
        ...d.templates.map((t) => ({ key: `t${t.id}`, label: <a href={t.url} download>엑셀 양식: {t.name}</a> })),
      ]}
      props={[
        { label: 'LOT', node: <Link to={`/trace?lot=${encodeURIComponent(d.lot.number)}`}>{d.lot.number}</Link> },
        { label: '품번', node: `${d.item.code} · ${d.item.name}` },
        { label: '공급사', node: d.lot.supplier || '—' },
        { label: '입고 수량', node: d.lot.qty ?? '—' },
        { label: '검사기준', node: <Link to={`/specs/${s.id}`}>{s.title}</Link> },
        { label: '샘플링', node: s.sampling || '—' },
        { label: '기준 승인', node: s.approved_by ? `${s.approved_by} · ${(s.approved_at ?? '').slice(0, 10)}` : '—' },
        { label: '검사자', node: d.inspector },
        { label: '검사 일시', node: d.inspected_at.slice(0, 16).replace('T', ' ') },
        { label: '부적합', node: d.nonconformance ? <a href={d.nonconformance.url}>{d.nonconformance.number}</a> : '없음' },
        { label: 'CAPA', node: d.capa?.length ? d.capa.map((c, i) => <span key={c.id}>{i > 0 && ', '}<a href={c.url}>{c.number}</a></span>) : '없음' },
      ]}
      side={[
        { key: 'relations', label: '연결', node: <RelationsPanel ct="qms.inspection" id={id} /> },
        { key: 'memo', label: '메모', node: <MemoPanel ct="qms.inspection" id={id} /> },
        { key: 'files', label: '첨부', node: <AttachmentPanel ct="qms.inspection" id={id} /> },
      ]}
    >
      <Table<M> size="small" columns={COLUMNS} dataSource={d.measurements} rowKey={(m) => m.name} pagination={false} scroll={{ x: 'max-content' }} locale={{ emptyText: '측정 결과가 없습니다' }} />
    </RecordPage>
  )
}
