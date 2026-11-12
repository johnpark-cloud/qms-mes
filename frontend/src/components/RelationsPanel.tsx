import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Spin, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../api/client'

interface RelationItem {
  id: number
  text: string
  status: string
  url: string | null
}
interface RelationGroup {
  key: string
  label: string
  model: string
  field: string
  direction: 'in' | 'out'
  count: number
  items: RelationItem[]
}
interface RelationsPayload {
  record: RelationItem & { model: string }
  incoming: RelationGroup[]
  outgoing: RelationGroup[]
}
interface GroupPage extends RelationGroup {
  page: number
  pages: number
}

const COLOR: Record<string, string> = { 승인됨: 'green', 합격: 'green', 종결: 'green', 초안: 'orange', 진행: 'orange', 미판정: 'orange', 불합격: 'red' }

function RecordLink({ item }: { item: RelationItem }) {
  if (!item.url) return <span>{item.text}</span>
  return item.url.startsWith('/app/') ? <Link to={item.url.slice(4)}>{item.text}</Link> : <a href={item.url}>{item.text}</a>
}

// 묶음 하나: 제목 단추로 접고 펼친다. 처음 5개만 오고, '모두 보기'는 20개씩 다음 쪽을 이어 붙인다.
function Group({ ct, id, group }: { ct: string; id: number; group: RelationGroup }) {
  const [open, setOpen] = useState(true)
  const [more, setMore] = useState<RelationItem[] | null>(null)
  const [page, setPage] = useState(0)
  const [pages, setPages] = useState(1)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const items = more ?? group.items
  const loadNext = async () => {
    setLoading(true)
    setErr('')
    try {
      const next = page + 1
      const d = await api<GroupPage>(`/api/relations/${ct}/${id}/?key=${encodeURIComponent(group.key)}&page=${next}`)
      setMore((cur) => (next === 1 ? d.items : [...(cur ?? []), ...d.items]))
      setPage(next)
      setPages(d.pages)
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }
  const hasMore = page === 0 ? group.count > group.items.length : page < pages
  return (
    <div className="relation-group" data-relation={group.key}>
      <h3 style={{ margin: '12px 0 4px', fontSize: 14 }}>
        <Button type="text" size="small" aria-expanded={open} onClick={() => setOpen(!open)} style={{ padding: 0, fontWeight: 600 }}>
          {group.label} <Typography.Text type="secondary">{group.count}</Typography.Text>
        </Button>
      </h3>
      {open && (
        <>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4 }}>
            {items.map((it) => (
              <li key={it.id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', overflowWrap: 'anywhere' }}>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <RecordLink item={it} />
                </span>
                {it.status && <Tag color={COLOR[it.status] ?? 'default'} style={{ margin: 0 }}>{it.status}</Tag>}
              </li>
            ))}
          </ul>
          {hasMore && (
            <Button size="small" type="link" style={{ padding: 0 }} loading={loading} onClick={() => void loadNext()}>
              {page === 0 ? `모두 보기 (${group.count})` : '더 보기'}
            </Button>
          )}
          {err && <Alert type="error" message={err} role="alert" />}
        </>
      )}
    </div>
  )
}

// 이 기록과 연결된 기록: 이 기록을 가리키는 것(위)과 이 기록이 가리키는 것(구분선 아래).
export default function RelationsPanel({ ct, id }: { ct: string; id: number }) {
  const q = useQuery({ queryKey: ['relations', ct, id], queryFn: () => api<RelationsPayload>(`/api/relations/${ct}/${id}/`) })
  if (q.isError) return <Alert type="error" message={q.error instanceof ApiError ? q.error.detail : '연결을 불러오지 못했습니다.'} />
  if (!q.data) return <Spin />
  const { incoming, outgoing } = q.data
  const total = [...incoming, ...outgoing].reduce((n, g) => n + g.count, 0)
  return (
    <section aria-label="연결">
      <Typography.Text strong>연결 {total}</Typography.Text>
      {total === 0 && (
        <div>
          <Typography.Text type="secondary">연결된 기록이 없습니다.</Typography.Text>
        </div>
      )}
      {incoming.map((g) => (
        <Group key={g.key} ct={ct} id={id} group={g} />
      ))}
      {outgoing.length > 0 && (
        <>
          <div className="relation-divider" style={{ margin: '16px 0 0', borderTop: '1px solid var(--ant-color-border-secondary, #e5e5e5)', paddingTop: 8 }}>
            <Typography.Text type="secondary">이 기록이 가리키는 것</Typography.Text>
          </div>
          {outgoing.map((g) => (
            <Group key={g.key} ct={ct} id={id} group={g} />
          ))}
        </>
      )}
    </section>
  )
}
