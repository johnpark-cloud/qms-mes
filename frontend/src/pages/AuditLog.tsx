import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Alert, Button, Input, Select, Space } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { Page } from '../api/specs'

interface Row {
  history_id: number
  date: string
  user: string
  type: string
  object_id: string
  object_repr: string
  changes: { field: string; old: string; new: string }[]
}

export default function AuditLog() {
  const [sp, setSp] = useSearchParams()
  const model = sp.get('model') ?? ''
  const id = sp.get('id') ?? ''
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v)
    else n.delete(k)
    if (k === 'model') n.delete('id') // 다른 기록 종류의 id가 남아 걸러내지 않게
    setSp(n, { replace: true })
  }
  const models = useQuery({ queryKey: ['audit-models'], queryFn: () => api<{ models: { key: string; label: string }[] }>('/api/audit-log/') })
  const rows = useInfiniteQuery({
    queryKey: ['audit', model, id],
    enabled: !!model,
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      api<Page<Row>>(`/api/audit-log/?model=${encodeURIComponent(model)}&id=${encodeURIComponent(id)}&page=${pageParam}`),
    getNextPageParam: (last) => (last.has_more ? last.page + 1 : undefined),
  })
  const err = models.error ?? rows.error
  // 쪽 번호로 받으므로 그 사이 새 기록이 생기면 같은 줄이 또 올 수 있다: history_id로 한 번만 둔다.
  const list = [...new Map((rows.data?.pages.flatMap((p) => p.results) ?? []).map((r) => [r.history_id, r])).values()]
  return (
    <>
      <h1 className="page-title">감사 기록</h1>
      {err && <Alert type="error" message={err instanceof ApiError ? err.detail : '불러오지 못했습니다.'} style={{ marginBottom: 16 }} />}
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          style={{ minWidth: 220 }}
          placeholder="기록 종류를 고르세요"
          value={model || undefined}
          options={models.data?.models.map((m) => ({ value: m.key, label: m.label }))}
          onChange={(v) => set('model', v)}
        />
        <Input
          style={{ width: 160 }}
          placeholder="기록 번호(id)"
          defaultValue={id}
          key={id}
          allowClear
          onChange={(e) => { if (!e.target.value) set('id', '') }}
          onPressEnter={(e) => set('id', e.currentTarget.value.trim())}
          onBlur={(e) => set('id', e.target.value.trim())}
        />
      </Space>
      {model && !rows.isError && (
        <table className="grid-table">
          <thead><tr><th>일시</th><th>사용자</th><th>구분</th><th>기록</th><th>바뀐 칸</th></tr></thead>
          <tbody>
            {list.map((r) => (
              <tr key={r.history_id} data-audit-row>
                <td>{r.date.slice(0, 19).replace('T', ' ')}</td>
                <td>{r.user}</td>
                <td>{r.type}</td>
                <td>{r.object_repr} (#{r.object_id})</td>
                <td>{r.changes.map((c) => <div key={c.field}>{c.field}: {c.old} → {c.new}</div>)}</td>
              </tr>
            ))}
            {!rows.isLoading && list.length === 0 && <tr><td colSpan={5}>기록이 없습니다.</td></tr>}
          </tbody>
        </table>
      )}
      {rows.hasNextPage && <Button style={{ marginTop: 16 }} loading={rows.isFetchingNextPage} onClick={() => rows.fetchNextPage()}>더 보기</Button>}
    </>
  )
}
