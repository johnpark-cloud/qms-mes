import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Dropdown, Spin, Table, Tag } from 'antd'
import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import type { InspectionDetail } from '../../api/inspect'
import MemoPanel from '../../components/MemoPanel'
import RecordPage from '../../components/RecordPage'
import { addRecent } from '../../lib/recent'

type M = InspectionDetail['measurements'][number]

const COLUMNS = [
  { title: '항목', dataIndex: 'name' },
  { title: '규격', dataIndex: 'spec_text' },
  { title: '측정값', dataIndex: 'value', render: (v: string | null) => v ?? '' },
  { title: '계측기', dataIndex: 'gauge' },
  { title: '판정', dataIndex: 'passed', render: (v: boolean | null) => (v === null ? '' : <Tag color={v ? 'green' : 'red'}>{v ? '합격' : '불합격'}</Tag>) },
]

export default function InspectionPage() {
  const id = Number(useParams().id)
  const q = useQuery({ queryKey: ['inspection', id], queryFn: () => api<InspectionDetail>(`/api/qms/inspections/${id}/`) })
  const d = q.data
  useEffect(() => {
    if (d) addRecent({ label: d.title, href: `/app/inspections/${d.id}` })
  }, [d])
  if (q.isError) return <Alert type="error" message={q.error instanceof ApiError ? q.error.detail : '검사 기록을 불러오지 못했습니다.'} style={{ margin: 16 }} />
  if (!d) return <Spin />
  return (
    <RecordPage
      title={d.title}
      status={d.status}
      // 판정된 검사는 고칠 수 없으므로 편집 버튼이 없다.
      actions={
        <Dropdown
          menu={{
            items: [
              { key: 'xlsx', label: <a href={`/api/qms/inspections/${id}/document/?export=xlsx`} download>.xlsx</a> },
              { key: 'pdf', label: <Link to={`/inspections/${id}/print`}>PDF(인쇄 화면)</Link> },
              ...d.templates.map((t) => ({ key: `t${t.id}`, label: <a href={t.url} download>{t.name}</a> })),
            ],
          }}
        >
          <Button>내보내기 ▾</Button>
        </Dropdown>
      }
      props={[
        { label: 'LOT', node: <Link to={`/trace?lot=${encodeURIComponent(d.lot.number)}`}>{d.lot.number}</Link> },
        { label: '품번', node: `${d.item.code} · ${d.item.name}` },
        { label: '검사기준', node: <Link to={`/specs/${d.spec.id}`}>{d.spec.title}</Link> },
        { label: '검사자', node: d.inspector },
        { label: '검사 일시', node: d.inspected_at.slice(0, 16).replace('T', ' ') },
        { label: '부적합', node: d.nonconformance ? <a href={d.nonconformance.url}>{d.nonconformance.number}</a> : '없음' },
      ]}
      side={[{ key: 'memo', label: '메모', node: <MemoPanel ct="qms.inspection" id={id} /> }]}
    >
      <Table<M> size="small" columns={COLUMNS} dataSource={d.measurements} rowKey={(m) => m.name} pagination={false} locale={{ emptyText: '측정 결과가 없습니다' }} />
    </RecordPage>
  )
}
