import { Alert, Button, Form, Input, Modal, Select, Space, Switch, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { ItemDetail, ItemNumberOptions, ItemRow, NumberRuleOptions } from '../../api/master'
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
  { title: '품번', dataIndex: 'code', render: (c: string, r) => (r.code_parts ? <Tooltip title={r.code_parts}>{c}</Tooltip> : c) },
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
  const [form] = Form.useForm()
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [auto, setAuto] = useState(true)
  const [rules, setRules] = useState<NumberRuleOptions[]>([])
  const [ruleId, setRuleId] = useState<number | undefined>()
  const [values, setValues] = useState<(string | undefined)[]>([])
  const [preview, setPreview] = useState('')
  const [previewErr, setPreviewErr] = useState('')

  useEffect(() => {
    if (!open) return
    setAuto(true)
    setValues([])
    setPreview('')
    api<ItemNumberOptions>('/api/core/numbering/item-options/')
      .then((r) => {
        setRules(r.rules)
        setRuleId(r.rules[0]?.id)
      })
      .catch(() => setErr('번호 규칙을 불러오지 못했습니다.'))
  }, [open])

  const rule = rules.find((r) => r.id === ruleId)
  const full = !!rule && rule.fields.length > 0 && rule.fields.every((_, i) => values[i])

  useEffect(() => {
    setPreview('')
    setPreviewErr('')
    if (!auto || !rule || !full) return
    let stale = false
    const qs = values.map((x) => `&v=${encodeURIComponent(x!)}`).join('')
    api<{ number: string; item_type: string }>(`/api/core/numbering/item-preview/?rule=${rule.id}${qs}`)
      .then((r) => {
        if (stale) return
        setPreview(r.number)
        form.setFieldValue('item_type', r.item_type)
      })
      .catch((e) => !stale && setPreviewErr(e instanceof Error ? e.message : '번호를 만들지 못했습니다.'))
    return () => {
      stale = true
    }
  }, [auto, rule, full, values]) // eslint-disable-line react-hooks/exhaustive-deps

  const optionsOf = (i: number) => {
    const f = rule!.fields[i]
    const parent = f.parent == null ? undefined : rule!.fields[f.parent].options.find((o) => o.code === values[f.parent!])
    return f.options
      .filter((o) => f.parent == null || (parent !== undefined && o.parent_id === parent.id))
      .map((o) => ({ value: o.code, label: `${o.code} ${o.name}` }))
  }
  const pick = (i: number, v: string) => setValues((p) => [...p.slice(0, i), v])

  const manual = () => {
    form.setFieldsValue({ code: preview })
    setAuto(false)
  }

  const submit = async (v: { code?: string; name: string; item_type: string }) => {
    setErr('')
    setSaving(true)
    try {
      const body = auto ? { name: v.name, item_type: v.item_type, auto: { rule: ruleId, values } } : v
      const d = await api<ItemDetail>('/api/core/items/', { method: 'POST', body: JSON.stringify(body) })
      nav(`/items/${d.id}`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '만들지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} title="새 품번" footer={null} destroyOnHidden afterOpenChange={() => setErr('')}>
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item label="자동 번호">
          <Switch checked={auto} onChange={setAuto} aria-label="자동 번호" />
        </Form.Item>
        {auto ? (
          <>
            <Form.Item label="규칙">
              <Select
                aria-label="규칙"
                value={ruleId}
                options={rules.map((r) => ({ value: r.id, label: r.name }))}
                onChange={(id) => {
                  setRuleId(id)
                  setValues([])
                }}
              />
            </Form.Item>
            {rule?.fields.map((f, i) => (
              <Form.Item key={`${rule.id}-${i}`} label={f.label}>
                <Select
                  aria-label={f.label}
                  showSearch={{ optionFilterProp: 'label' }}
                  placeholder={`${f.label} 선택`}
                  value={values[i]}
                  options={optionsOf(i)}
                  onChange={(v) => pick(i, v)}
                />
              </Form.Item>
            ))}
            {(preview || previewErr) && (
              <Form.Item>
                {preview ? (
                  <Space>
                    <span data-testid="number-preview">다음 번호: {preview} (저장할 때 확정)</span>
                    <Button size="small" onClick={manual}>
                      직접 고치기
                    </Button>
                  </Space>
                ) : (
                  <Alert type="error" message={previewErr} />
                )}
              </Form.Item>
            )}
          </>
        ) : (
          <Form.Item label="품번" name="code" rules={[{ required: true, whitespace: true, message: '품번을 입력하세요.' }]}>
            <Input />
          </Form.Item>
        )}
        <Form.Item label="품명" name="name" rules={[{ required: true, whitespace: true, message: '품명을 입력하세요.' }]}>
          <Input />
        </Form.Item>
        <Form.Item label="구분" name="item_type" rules={[{ required: true, message: '구분을 고르세요.' }]}>
          <Select options={TYPES} placeholder="구분 선택" />
        </Form.Item>
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Space>
          <Button type="primary" htmlType="submit" loading={saving} disabled={auto && !preview}>
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
