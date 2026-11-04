import { Alert, Button, Form, Input, Modal, Select, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { ItemDetail, ItemRow } from '../../api/master'
import type { Page } from '../../api/specs'
import DataList from '../../components/DataList'
import { addRecent } from '../../lib/recent'

// core/models.py Item.TYPES 와 같은 값이다.
const TYPES = [
  { value: 'RAW', label: '원자재' },
  { value: 'SEMI', label: '반제품' },
  { value: 'FIN', label: '완제품' },
]
const TABS = [{ key: 'all', label: '전체' }, ...TYPES.map((t) => ({ key: t.value, label: t.label }))]

const COLUMNS: ColumnsType<ItemRow> = [
  { title: '품번', dataIndex: 'code' },
  { title: '품명', dataIndex: 'name' },
  { title: '구분', dataIndex: 'item_type_display' },
  { title: 'BOM 수', dataIndex: 'bom_count', align: 'right' },
  { title: '라우팅 수', dataIndex: 'routing_count', align: 'right' },
]

const fetchPage = (tab: string, q: string, page: number) =>
  api<Page<ItemRow>>(`/api/core/items/?tab=${tab}&q=${encodeURIComponent(q)}&page=${page}`)

const exportHref = (tab: string, q: string) => `/api/core/items/?tab=${tab}&q=${encodeURIComponent(q)}&export=xlsx`

function NewItem({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async (v: { code: string; name: string; item_type: string }) => {
    setErr('')
    setSaving(true)
    try {
      const d = await api<ItemDetail>('/api/core/items/', { method: 'POST', body: JSON.stringify(v) })
      nav(`/items/${d.id}`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '만들지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} title="새 품번" footer={null} destroyOnHidden afterOpenChange={() => setErr('')}>
      <Form layout="vertical" onFinish={submit}>
        <Form.Item label="품번" name="code" rules={[{ required: true, whitespace: true, message: '품번을 입력하세요.' }]}>
          <Input />
        </Form.Item>
        <Form.Item label="품명" name="name" rules={[{ required: true, whitespace: true, message: '품명을 입력하세요.' }]}>
          <Input />
        </Form.Item>
        <Form.Item label="구분" name="item_type" rules={[{ required: true, message: '구분을 고르세요.' }]}>
          <Select options={TYPES} placeholder="구분 선택" />
        </Form.Item>
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

export default function ItemList() {
  const nav = useNavigate()
  const [creating, setCreating] = useState(false)
  const open = (r: ItemRow) => {
    addRecent({ label: `${r.code} ${r.name}`, href: `/app/items/${r.id}` })
    nav(`/items/${r.id}`)
  }
  return (
    <div>
      <h1 className="page-title">품번</h1>
      <DataList<ItemRow>
        columns={COLUMNS}
        tabs={TABS}
        fetchPage={fetchPage}
        exportHref={exportHref}
        onOpen={open}
        rowKey={(r) => r.id}
        toolbar={
          <Button type="primary" onClick={() => setCreating(true)}>
            새 품번
          </Button>
        }
      />
      <NewItem open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
