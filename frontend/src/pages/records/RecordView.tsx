import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Spin, Table, Typography } from 'antd'
import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import AttachmentPanel from '../../components/AttachmentPanel'
import MemoPanel from '../../components/MemoPanel'
import RecordPage from '../../components/RecordPage'
import RelationsPanel from '../../components/RelationsPanel'
import { addRecent } from '../../lib/recent'

// core/api/records.py RecordDetailView 응답
interface Field { key: string; label: string; value: string; url: string | null }
interface Row { id: number; url: string | null; status: string | null; cells: Record<string, string> }
interface Child { key: string; label: string; columns: { key: string; label: string }[]; rows: Row[] }
interface Detail {
  ct: string; id: number; title: string; kind: string; status: string | null
  fields: Field[]; children: Child[]; side: string[]; admin_url: string; list_url: string
}
interface Hist { history_id: number; date: string; user: string; type: string; changes: { field: string; old: string; new: string }[] }

/** /app/ 안 주소는 라우터로, 그 밖(관리 화면·파일)은 그냥 링크 */
export function Go({ url, children }: { url: string | null; children: ReactNode }) {
  if (!url) return <>{children}</>
  return url.startsWith('/app/') ? <Link to={url.slice(4)}>{children}</Link> : <a href={url}>{children}</a>
}

function History({ label, id }: { label: string; id: number }) {
  const q = useQuery({ queryKey: ['record-history', label, id], queryFn: () => api<{ results: Hist[] }>(`/api/records/${label}/${id}/history/`) })
  if (q.isLoading) return <Spin />
  if (q.error) return <Alert type="error" message={(q.error as Error).message} />
  const rows = q.data?.results ?? []
  if (!rows.length) return <Empty description="변경 이력이 없습니다" />
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {rows.map((h) => (
        <li key={h.history_id} style={{ marginBottom: 12 }}>
          <div>{h.date.slice(0, 16).replace('T', ' ')} · {h.user} · {h.type}</div>
          {h.changes.map((c) => (
            <Typography.Text key={c.field} type="secondary" style={{ display: 'block' }}>{c.field}: {c.old || '—'} → {c.new || '—'}</Typography.Text>
          ))}
        </li>
      ))}
    </ul>
  )
}

export default function RecordView() {
  const { app, model, id } = useParams()
  const label = `${app}.${model}`
  const q = useQuery({ queryKey: ['record', label, id], queryFn: () => api<Detail>(`/api/records/${label}/${id}/`) })
  const d = q.data
  useEffect(() => {
    if (d) addRecent({ label: d.title, href: `/app/r/${app}/${model}/${d.id}` })
  }, [d, app, model])
  if (q.isLoading) return <Spin />
  if (q.error || !d) return <Alert type="error" message={(q.error as Error)?.message ?? '기록을 열 수 없습니다.'} />
  const SIDE: Record<string, { label: string; node: ReactNode }> = {
    relations: { label: '관련 기록', node: <RelationsPanel ct={d.ct} id={d.id} /> },
    memo: { label: '메모', node: <MemoPanel ct={d.ct} id={d.id} /> },
    files: { label: '첨부', node: <AttachmentPanel ct={d.ct} id={d.id} /> },
    history: { label: '변경 이력', node: <History label={label} id={d.id} /> },
  }
  return (
    <RecordPage
      title={d.title}
      status={d.status ?? undefined}
      record={{ ct: d.ct, id: d.id }}
      actions={
        <>
          <Link to={d.list_url.slice(4)}><Button>{d.kind} 목록</Button></Link>
          <a href={d.admin_url}><Button type="primary">수정</Button></a>
        </>
      }
      props={d.fields.map((f) => ({ label: f.label, node: <Go url={f.url}>{f.value || '—'}</Go> }))}
      side={d.side.filter((k) => SIDE[k]).map((k) => ({ key: k, ...SIDE[k] }))}
    >
      {d.children.map((c) => (
        <section key={c.key} style={{ marginBottom: 24 }}>
          <h3>{c.label}</h3>
          <Table<Row>
            size="small"
            pagination={false}
            rowKey="id"
            dataSource={c.rows}
            columns={c.columns.map((col, i) => ({
              title: col.label,
              key: col.key,
              render: (_: unknown, r: Row) => (i === 0 ? <Go url={r.url}>{r.cells[col.key] || '—'}</Go> : r.cells[col.key]),
            }))}
          />
        </section>
      ))}
    </RecordPage>
  )
}
