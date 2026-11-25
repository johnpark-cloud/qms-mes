import { Alert, Button, DatePicker, Drawer, Empty, Form, Input, InputNumber, Select, Space, Table, Tag, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import EditGrid, { newKey, withTail, type GridColumn, type GridRow } from '../../components/EditGrid'

interface FieldDef { name: string; kind: string; required?: boolean; choices?: string[] }
interface Rec { id: number; written_on: string; author: string; values: Record<string, string>; approved: boolean; url: string }
interface Ledger {
  form: {
    id: number; code: string; name: string; revision: string; direction: string; fields: FieldDef[]; url: string
    document: { number: string; title: string; url: string }; target_url: string | null; target_display: string
  }
  records: Rec[]; kinds: [string, string][]; can_add: boolean; can_edit: boolean; can_define: boolean
}

const inApp = (url: string) => url.replace(/^\/app/, '')
const body = (v: unknown) => JSON.stringify(v)

// Form.Item이 넣어 주는 id·value·onChange를 그대로 입력 칸에 넘긴다
function FieldInput({ f, ...p }: { f: FieldDef; disabled: boolean; [k: string]: unknown }) {
  if (f.kind === 'long') return <Input.TextArea autoSize={{ minRows: 3 }} {...p} />
  if (f.kind === 'number') return <InputNumber style={{ width: '100%' }} stringMode {...p} />
  if (f.kind === 'date') return <DatePicker style={{ width: '100%' }} {...p} />
  if (f.kind === 'choice') return <Select allowClear options={(f.choices ?? []).map((c) => ({ value: c, label: c }))} {...p} />
  return <Input {...p} />
}

// 항목 정의 → 입력 칸 값(날짜는 dayjs) / 저장 값(글자)
const toForm = (fields: FieldDef[], v: Record<string, string>) =>
  Object.fromEntries(fields.map((f) => [f.name, f.kind === 'date' && v[f.name] ? dayjs(v[f.name]) : v[f.name]]))
const fromForm = (fields: FieldDef[], v: Record<string, unknown>) =>
  Object.fromEntries(fields.map((f) => {
    const x = v[f.name]
    return [f.name, x == null ? '' : dayjs.isDayjs(x) ? x.format('YYYY-MM-DD') : String(x)]
  }))

// 양식 기록 대장(P6b): 시스템 기록이 없는 양식을 항목 정의대로 한 줄 한 건으로 쓴다. 승인·첨부·이력은 기록 화면에서.
export default function FormLedgerPage() {
  const { id } = useParams()
  const qc = useQueryClient()
  const key = ['form-ledger', id]
  const { data, error } = useQuery({ queryKey: key, queryFn: () => api<Ledger>(`/api/qms/forms/${id}/`) })
  const [open, setOpen] = useState<Rec | 'new' | null>(null)
  const [defs, setDefs] = useState<GridRow[] | null>(null)
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [form] = Form.useForm()

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => {
      const payload = body({ values: fromForm(data!.form.fields, v) })
      return open === 'new'
        ? api(`/api/qms/forms/${id}/records/`, { method: 'POST', body: payload })
        : api(`/api/qms/formrecords/${(open as Rec).id}/`, { method: 'PATCH', body: payload })
    },
    onSuccess: () => { message.success('저장했습니다.'); setOpen(null); qc.invalidateQueries({ queryKey: key }) },
    onError: (e) => message.error(e instanceof ApiError ? e.detail : '저장하지 못했습니다.'),
  })
  const define = useMutation({
    mutationFn: (rows: GridRow[]) => api(`/api/qms/forms/${id}/fields/`, {
      method: 'PUT',
      body: body({
        fields: rows.filter((r) => !r.delete && String(r.name ?? '').trim()).map((r) => ({
          name: String(r.name).trim(), kind: String(r.kind || 'text'), ...(r.required === 'Y' ? { required: true } : {}),
          ...(r.kind === 'choice' ? { choices: String(r.choices ?? '').split(',').map((c) => c.trim()).filter(Boolean) } : {}),
        })),
      }),
    }),
    onSuccess: () => { message.success('항목을 저장했습니다.'); setDefs(null); setErrors({}); qc.invalidateQueries({ queryKey: key }) },
    onError: (e) => { if (e instanceof ApiError) { setErrors(e.fields); message.error(e.detail) } },
  })

  if (error) return <Alert type="error" message={error instanceof ApiError ? error.detail : '불러오지 못했습니다.'} />
  if (!data) return null
  const { form: f, records } = data
  const cols: GridColumn[] = [
    { key: 'name', label: '항목 이름', kind: 'text' },
    { key: 'kind', label: '종류', kind: 'select', options: data.kinds.map(([v, l]) => ({ value: v, label: l })), width: 120 },
    { key: 'choices', label: '선택지(쉼표로 구분)', kind: 'text' },
    { key: 'required', label: '필수', kind: 'select', options: [{ value: 'Y', label: '필수' }, { value: '', label: '-' }], width: 90 },
  ]
  const openDefs = () => setDefs(withTail(f.fields.map((x) => ({
    _key: newKey(), id: 0, name: x.name, kind: x.kind, choices: (x.choices ?? []).join(', '), required: x.required ? 'Y' : '',
  })), cols))
  const openRec = (r: Rec | 'new') => {
    setOpen(r)
    form.setFieldsValue(r === 'new' ? Object.fromEntries(f.fields.map((x) => [x.name, undefined])) : toForm(f.fields, r.values))
  }
  const readOnly = open !== null && (open === 'new' ? !data.can_add : open.approved || !data.can_edit)

  return (
    <div>
      <h1 className="page-title">{f.code} {f.name}</h1>
      <Space wrap style={{ marginBottom: 12 }}>
        <span className="doc-hint">
          결재서 <Link to={inApp(f.document.url)}>{f.document.number} {f.document.title}</Link> · {f.direction} 양식{f.revision && ` · Rev.${f.revision}`}
        </span>
        {f.target_url && <Link to={inApp(f.target_url)}><Button>{f.target_display}에서 쓰기</Button></Link>}
        {data.can_add && f.fields.length > 0 && <Button type="primary" onClick={() => openRec('new')}>새 기록</Button>}
        {data.can_define && <Button onClick={openDefs}>항목 정의</Button>}
        <Link to={inApp(f.url)}><Button type="text">양식 정보</Button></Link>
      </Space>
      {!f.fields.length ? (
        <Empty description={data.can_define ? '먼저 「항목 정의」로 이 양식에 적을 칸을 정하세요.' : '아직 항목이 정의되지 않은 양식입니다.'} />
      ) : (
        <Table<Rec>
          size="small" rowKey="id" dataSource={records} scroll={{ x: 'max-content' }}
          onRow={(r) => ({ onClick: () => openRec(r), style: { cursor: 'pointer' } })}
          locale={{ emptyText: '아직 기록이 없습니다. 「새 기록」으로 작성하세요.' }}
          columns={[
            { title: '작성일', dataIndex: 'written_on', width: 110 },
            { title: '작성자', dataIndex: 'author', width: 100 },
            ...f.fields.map((x) => ({
              title: x.name, key: x.name, ellipsis: x.kind === 'long',
              render: (_: unknown, r: Rec) => r.values[x.name] ?? '',
            })),
            {
              title: '승인', width: 90,
              render: (_: unknown, r: Rec) => (
                <Link to={inApp(r.url)} onClick={(e) => e.stopPropagation()}>
                  {r.approved ? <Tag color="green">승인</Tag> : <Tag>작성 중</Tag>}
                </Link>
              ),
            },
          ]}
        />
      )}
      <Drawer
        open={open !== null} onClose={() => setOpen(null)} width={480} destroyOnHidden
        title={open === 'new' ? `새 기록 · ${f.code}` : `기록 · ${open?.written_on ?? ''}`}
        extra={open && open !== 'new' && <Link to={inApp(open.url)}>승인·첨부·이력</Link>}
        footer={!readOnly && <Button type="primary" loading={save.isPending} onClick={() => form.submit()}>저장</Button>}
      >
        {open && open !== 'new' && open.approved && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="승인된 기록이라 고칠 수 없습니다. 고치려면 기록 화면에서 수정 요청을 하세요." />}
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)} preserve={false}>
          {f.fields.map((x) => (
            <Form.Item key={x.name} name={x.name} label={x.name} rules={x.required ? [{ required: true, message: `${x.name}을(를) 적으세요.` }] : []}>
              <FieldInput f={x} disabled={readOnly} />
            </Form.Item>
          ))}
        </Form>
      </Drawer>
      <Drawer
        open={defs !== null} onClose={() => setDefs(null)} width={720} title={`항목 정의 · ${f.code}`}
        footer={<Button type="primary" loading={define.isPending} onClick={() => defs && define.mutate(defs)}>저장</Button>}
      >
        <p className="doc-hint">한 줄에 한 칸. 종류가 「선택」이면 선택지를 쉼표로 적습니다. 엑셀에서 여러 줄을 붙여넣을 수 있습니다.</p>
        {defs && <EditGrid columns={cols} rows={defs} onChange={setDefs} readOnly={false} errors={errors} errorPrefix="fields" />}
      </Drawer>
    </div>
  )
}
