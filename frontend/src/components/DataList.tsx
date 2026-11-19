import { Button, DatePicker, Drawer, Input, Select, Space, Table, Tabs, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useRef, useState, type Key, type ReactNode } from 'react'

// core/api/listing.py 필터 정의. 선택지는 ?f_열=값, 날짜는 ?f_열_from=·?f_열_to=
export interface ListFilter { key: string; label: string; type: 'choice' | 'date'; options?: { value: string; label: string }[] }

interface Props<T> {
  columns: ColumnsType<T>
  tabs: { key: string; label: string }[]
  // extra: 정렬·필터 조건(&sort=…&f_…=…). 열에 sorter: true를 준 것만 머리를 눌러 정렬한다
  fetchPage: (tab: string, q: string, page: number, extra: string) => Promise<{ count: number; has_more: boolean; results: T[] }>
  exportHref: (tab: string, q: string, extra: string) => string
  filters?: ListFilter[]
  peek?: (row: T) => ReactNode
  onOpen: (row: T) => void
  toolbar?: ReactNode
  rowKey: (row: T) => Key
  emptyText?: string
  tab?: string // 주소 ?tab= 과 맞출 때 쓴다
  onTab?: (tab: string) => void
}

export default function DataList<T extends object>({ columns, tabs, fetchPage, exportHref, filters, peek, onOpen, toolbar, rowKey, emptyText, tab: tabProp, onTab }: Props<T>) {
  const [tabState, setTab] = useState(tabs[0].key)
  const tab = tabProp ?? tabState
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
  const [sort, setSort] = useState('')
  const [fv, setFv] = useState<Record<string, string | undefined>>({})
  const extra = useMemo(() => {
    const p = new URLSearchParams()
    if (sort) p.set('sort', sort)
    Object.entries(fv).forEach(([k, v]) => v && p.set(k, v))
    const s = p.toString()
    return s ? `&${s}` : ''
  }, [sort, fv])

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
        const r = await fetchPage(tab, q, p, extra)
        if (my !== seq.current) return
        setRows((old) => (p === 1 ? r.results : [...old, ...r.results]))
        setCount(r.count)
        setMore(r.has_more)
        setPage(p)
      } catch (e) {
        if (my === seq.current) {
          setError(e instanceof Error ? e.message : '목록을 불러오지 못했습니다.')
          if (p === 1) {
            setRows([])
            setCount(0)
            setMore(false)
          }
        }
      } finally {
        if (my === seq.current) setLoading(false)
      }
    },
    [fetchPage, tab, q, extra],
  )

  useEffect(() => {
    void load(1)
  }, [load])

  return (
    <div>
      <Tabs activeKey={tab} onChange={(k) => {
          if (tabProp === undefined) setTab(k) // 주소로 탭을 정하면 부모가 바꾼다
          onTab?.(k)
        }} items={tabs} />
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search allowClear placeholder="검색" value={text} onChange={(e) => setText(e.target.value)} style={{ width: 260 }} />
        {filters?.map((f) =>
          f.type === 'choice' ? (
            <Select
              key={f.key}
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={f.label}
              style={{ minWidth: 140 }}
              value={fv[`f_${f.key}`]}
              onChange={(v?: string) => setFv((p) => ({ ...p, [`f_${f.key}`]: v }))}
              options={f.options}
            />
          ) : (
            <DatePicker.RangePicker
              key={f.key}
              allowEmpty={[true, true]}
              placeholder={[`${f.label} 부터`, '까지']}
              onChange={(d) =>
                setFv((p) => ({ ...p, [`f_${f.key}_from`]: d?.[0]?.format('YYYY-MM-DD'), [`f_${f.key}_to`]: d?.[1]?.format('YYYY-MM-DD') }))
              }
            />
          ),
        )}
        <a href={exportHref(tab, q, extra)} download>
          엑셀 받기
        </a>
        {toolbar}
        <span>총 {count}건</span>
      </Space>
      {error && (
        <Typography.Text type="danger" role="alert" style={{ display: 'block', marginBottom: 8 }}>
          {error}
        </Typography.Text>
      )}
      <Table<T>
        size="small"
        columns={columns}
        dataSource={rows}
        rowKey={rowKey}
        loading={loading && page === 1}
        pagination={false}
        onChange={(_p, _f, s) => {
          const one = Array.isArray(s) ? s[0] : s
          setSort(one?.order ? `${one.order === 'descend' ? '-' : ''}${String(one.columnKey ?? one.field)}` : '')
        }}
        locale={{ emptyText: emptyText ?? '표시할 기록이 없습니다' }}
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
