import { useQuery } from '@tanstack/react-query'
import { Spin } from 'antd'
import { useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import DataList from '../../components/DataList'

// core/api/records.py RecordListView 응답
interface Row { id: number; url: string | null; status: string | null; cells: Record<string, string> }
interface ListPage {
  title: string; tabs: { key: string; label: string }[]; columns: { key: string; label: string }[]
  count: number; page: number; has_more: boolean; results: Row[]; can_add: boolean
}

export default function RecordList() {
  const { app, model } = useParams()
  const label = `${app}.${model}`
  const base = `/api/records/${label}/`
  const nav = useNavigate()
  // 탭·열 모양은 첫 쪽 응답에서 얻는다
  const head = useQuery({ queryKey: ['record-list-head', label], queryFn: () => api<ListPage>(base) })
  // DataList는 fetchPage가 바뀌면 다시 불러온다 → 주소가 같으면 같은 함수
  const fetchPage = useCallback(
    (tab: string, q: string, page: number) => api<ListPage>(`${base}?tab=${tab}&q=${encodeURIComponent(q)}&page=${page}`),
    [base],
  )
  if (!head.data) return <Spin />
  const h = head.data
  return (
    <div>
      <h1 className="page-title">{h.title}</h1>
      <DataList<Row>
        key={label}
        columns={h.columns.map((c) => ({ title: c.label, key: c.key, render: (_: unknown, r: Row) => r.cells[c.key] }))}
        tabs={h.tabs}
        fetchPage={fetchPage}
        exportHref={(tab, q) => `${base}?tab=${tab}&q=${encodeURIComponent(q)}&export=xlsx`}
        onOpen={(r) => nav(`/r/${app}/${model}/${r.id}`)}
        rowKey={(r) => r.id}
        toolbar={h.can_add ? <a href={`/admin/${app}/${model}/add/`}>새로 만들기</a> : undefined}
      />
    </div>
  )
}
