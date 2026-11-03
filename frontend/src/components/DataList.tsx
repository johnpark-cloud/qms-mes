import { Button, Drawer, Input, Space, Table, Tabs } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useRef, useState, type Key, type ReactNode } from 'react'

interface Props<T> {
  columns: ColumnsType<T>
  tabs: { key: string; label: string }[]
  fetchPage: (tab: string, q: string, page: number) => Promise<{ count: number; has_more: boolean; results: T[] }>
  exportHref: (tab: string, q: string) => string
  peek?: (row: T) => ReactNode
  onOpen: (row: T) => void
  toolbar?: ReactNode
  rowKey: (row: T) => Key
}

export default function DataList<T extends object>({ columns, tabs, fetchPage, exportHref, peek, onOpen, toolbar, rowKey }: Props<T>) {
  const [tab, setTab] = useState(tabs[0].key)
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<T[]>([])
  const [count, setCount] = useState(0)
  const [more, setMore] = useState(false)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState<T | null>(null)
  const seq = useRef(0) // 늦게 온 이전 응답이 새 결과를 덮지 않게 한다

  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 300)
    return () => clearTimeout(t)
  }, [text])

  const load = useCallback(
    async (p: number) => {
      const my = ++seq.current
      setLoading(true)
      setError('')
      try {
        const r = await fetchPage(tab, q, p)
        if (my !== seq.current) return
        setRows((old) => (p === 1 ? r.results : [...old, ...r.results]))
        setCount(r.count)
        setMore(r.has_more)
        setPage(p)
      } catch (e) {
        if (my === seq.current) setError(e instanceof Error ? e.message : '목록을 불러오지 못했습니다.')
      } finally {
        if (my === seq.current) setLoading(false)
      }
    },
    [fetchPage, tab, q],
  )

  useEffect(() => {
    void load(1)
  }, [load])

  return (
    <div>
      <Tabs activeKey={tab} onChange={setTab} items={tabs} />
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search allowClear placeholder="검색" value={text} onChange={(e) => setText(e.target.value)} style={{ width: 260 }} />
        <a href={exportHref(tab, q)} download>
          엑셀로
        </a>
        {toolbar}
        <span>총 {count}건</span>
      </Space>
      {error && (
        <div role="alert" style={{ color: '#c00', marginBottom: 8 }}>
          {error}
        </div>
      )}
      <Table<T>
        size="small"
        columns={columns}
        dataSource={rows}
        rowKey={rowKey}
        loading={loading && page === 1}
        pagination={false}
        locale={{ emptyText: '표시할 기록이 없습니다' }}
        onRow={(row) => ({ 'data-row': '', onClick: () => (peek ? setPicked(row) : onOpen(row)), style: { cursor: 'pointer' } }) as object}
      />
      {more && (
        <Button style={{ marginTop: 12 }} loading={loading} onClick={() => void load(page + 1)}>
          더 보기
        </Button>
      )}
      <Drawer
        open={picked !== null}
        onClose={() => setPicked(null)}
        size="large"
        title="미리보기"
        extra={
          <Button type="primary" onClick={() => picked && onOpen(picked)}>
            전체 화면으로
          </Button>
        }
      >
        {picked && peek?.(picked)}
      </Drawer>
    </div>
  )
}
