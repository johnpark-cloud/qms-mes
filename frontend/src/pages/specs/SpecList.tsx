import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Form, Modal, Select, Space, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import { INSPECTION_TYPES, type Page, type SpecDetail, type SpecRow } from '../../api/specs'
import DataList from '../../components/DataList'
import { addRecent } from '../../lib/recent'

const TABS = [
  { key: 'all', label: '전체' },
  { key: 'draft', label: '초안' },
  { key: 'approved', label: '승인됨' },
  { key: 'current', label: '유효본만' },
]

const COLUMNS: ColumnsType<SpecRow> = [
  { title: '품번', dataIndex: 'item_code' },
  { title: '품명', dataIndex: 'item_name' },
  { title: '검사 구분', dataIndex: 'inspection_type_display' },
  { title: '개정', dataIndex: 'revision', render: (v: number) => `Rev.${v}` },
  {
    title: '상태',
    dataIndex: 'status',
    render: (v: string, r) => (
      <Tag color={v === '승인됨' ? 'green' : 'default'}>
        {v}
        {r.is_current ? ' · 유효' : ''}
      </Tag>
    ),
  },
  { title: '항목 수', dataIndex: 'char_count', align: 'right' },
  { title: '승인자·승인일', render: (_, r) => (r.approved_by ? `${r.approved_by} · ${r.approved_at?.slice(0, 10) ?? ''}` : '') },
]

const fetchPage = (tab: string, q: string, page: number) =>
  api<Page<SpecRow>>(`/api/qms/specs/?tab=${tab}&q=${encodeURIComponent(q)}&page=${page}`)

const exportHref = (tab: string, q: string) => `/api/qms/specs/?tab=${tab}&q=${encodeURIComponent(q)}&export=xlsx`

function Peek({ row }: { row: SpecRow }) {
  const { data, error } = useQuery({ queryKey: ['spec', row.id], queryFn: () => api<SpecDetail>(`/api/qms/specs/${row.id}/`) })
  return (
    <div>
      <div className="prop-grid">
        <span>품번</span>
        <span>
          {row.item_code} · {row.item_name}
        </span>
        <span>검사 구분</span>
        <span>{row.inspection_type_display}</span>
        <span>개정</span>
        <span>Rev.{row.revision}</span>
        <span>상태</span>
        <span>{row.status}</span>
      </div>
      <h4>검사항목</h4>
      {data ? (
        data.characteristics.length ? (
          <ul>
            {data.characteristics.map((c) => (
              <li key={c.id}>{c.name}</li>
            ))}
          </ul>
        ) : (
          '검사항목이 없습니다'
        )
      ) : error ? (
        error instanceof ApiError ? error.detail : '불러오지 못했습니다.'
      ) : (
        '불러오는 중'
      )}
    </div>
  )
}

function NewSpec({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [items, setItems] = useState<{ value: number; label: string }[]>([])
  const [dup, setDup] = useState<number | null>(null)
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const search = (q: string) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      const r = await api<{ id: number; code: string; name: string }[]>(`/api/items/?q=${encodeURIComponent(q)}`).catch(() => [])
      setItems(r.map((i) => ({ value: i.id, label: `${i.code} · ${i.name}` })))
    }, 300)
  }
  useEffect(() => {
    setDup(null)
    setErr('')
    setSaving(false)
    if (open) search('')
    return () => clearTimeout(timer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const submit = async (v: { item: number; inspection_type: string }) => {
    setDup(null)
    setErr('')
    setSaving(true)
    try {
      const d = await api<SpecDetail>('/api/qms/specs/', { method: 'POST', body: JSON.stringify(v) })
      nav(`/specs/${d.id}`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setDup(e.body.existing)
      else setErr(e instanceof Error ? e.message : '만들지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} title="새 기준서" footer={null} destroyOnHidden>
      <Form layout="vertical" onFinish={submit}>
        <Form.Item label="품번" name="item" rules={[{ required: true, message: '품번을 고르세요.' }]}>
          <Select showSearch filterOption={false} onSearch={search} options={items} placeholder="품번 검색" notFoundContent="찾는 품번이 없습니다" />
        </Form.Item>
        <Form.Item label="검사 구분" name="inspection_type" rules={[{ required: true, message: '검사 구분을 고르세요.' }]}>
          <Select options={INSPECTION_TYPES} placeholder="검사 구분 선택" />
        </Form.Item>
        {dup !== null && (
          <Alert
            style={{ marginBottom: 12 }}
            type="warning"
            message="이미 있는 검사기준입니다."
            action={
              <Button size="small" onClick={() => nav(`/specs/${dup}`)}>
                그 기준서 열기
              </Button>
            }
          />
        )}
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Space>
          <Button type="primary" htmlType="submit" loading={saving}>
            만들기
          </Button>
          <Button onClick={onClose}>취소</Button>
        </Space>
      </Form>
    </Modal>
  )
}

export default function SpecList() {
  const nav = useNavigate()
  const [creating, setCreating] = useState(false)
  const open = (r: SpecRow) => {
    addRecent({ label: `${r.item_code} ${r.inspection_type_display} Rev.${r.revision}`, href: `/app/specs/${r.id}` })
    nav(`/specs/${r.id}`)
  }
  return (
    <div>
      <h1 className="page-title">검사기준</h1>
      <DataList<SpecRow>
        columns={COLUMNS}
        tabs={TABS}
        fetchPage={fetchPage}
        exportHref={exportHref}
        peek={(r) => <Peek row={r} />}
        onOpen={open}
        rowKey={(r) => r.id}
        toolbar={
          <Button type="primary" onClick={() => setCreating(true)}>
            새 기준서
          </Button>
        }
      />
      <NewSpec open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
