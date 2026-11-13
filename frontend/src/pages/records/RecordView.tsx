import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Checkbox, Empty, Form, Input, InputNumber, Modal, Select, Spin, Table, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import AttachmentPanel from '../../components/AttachmentPanel'
import MemoPanel from '../../components/MemoPanel'
import RecordPage from '../../components/RecordPage'
import RelationsPanel from '../../components/RelationsPanel'
import SignModal from '../../components/SignModal'
import { addRecent } from '../../lib/recent'

// core/api/records.py RecordDetailView 응답
interface Field { key: string; label: string; value: string; url: string | null }
interface Row { id: number; url: string | null; status: string | null; cells: Record<string, string> }
interface Child { key: string; label: string; columns: { key: string; label: string }[]; rows: Row[] }
type Value = string | number | boolean | null
interface Edit {
  key: string; label: string; type: 'str' | 'text' | 'int' | 'date' | 'bool' | 'choice'; value: Value; required: boolean
  choices: { value: string; label: string }[] | null
}
interface Detail {
  ct: string; id: number; title: string; kind: string; status: string | null
  fields: Field[]; children: Child[]; side: string[]; admin_url: string; list_url: string
  version: number; locked: boolean; edit: Edit[]; can_change: boolean; can_approve: boolean
  can_dispose: boolean; dispose: Edit[] | null
  requests: { edit: boolean; delete: boolean }
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

// Form.Item이 넣어 주는 value·checked·onChange·id를 입력 칸에 그대로 넘긴다
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function Editor({ e, ...rest }: { e: Edit; [k: string]: any }) {
  if (e.type === 'bool') return <Checkbox {...rest} />
  if (e.type === 'int') return <InputNumber style={{ width: '100%' }} {...rest} />
  if (e.type === 'date') return <Input type="date" {...rest} />
  if (e.type === 'text') return <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} {...rest} />
  if (e.type === 'choice') return <Select options={e.choices ?? []} {...rest} />
  return <Input {...rest} />
}

// 수정 요청: 사유와 본인 비밀번호 (core.rules.submit_edit_request). 삭제(요청)는 RecordPage 「⋯」 메뉴의 서버 화면으로 간다.
function EditRequestModal({ open, onClose, onSubmit }: {
  open: boolean; onClose: () => void; onSubmit: (v: { reason: string; password: string }) => Promise<void>
}) {
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => setErr(''), [open])
  const submit = async (v: { reason: string; password: string }) => {
    setBusy(true)
    try {
      await onSubmit(v)
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '요청하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onCancel={onClose} title="수정 요청" footer={null} destroyOnHidden>
      <Form layout="vertical" onFinish={submit}>
        <Form.Item label="사유" name="reason" rules={[{ required: true, whitespace: true, message: '사유를 입력하세요.' }]}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} autoFocus />
        </Form.Item>
        <Form.Item label="비밀번호" name="password" rules={[{ required: true, message: '비밀번호를 입력하세요.' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Button type="primary" htmlType="submit" loading={busy}>요청</Button>
      </Form>
    </Modal>
  )
}

// 부적합 MRB 처분: 처분·특채 승인번호·실패비용 + 품질팀장 비밀번호 (core.rules.dispose_nc). 규칙 문구는 서버 그대로 보인다.
function DisposeModal({ open, fields, onClose, onSubmit }: {
  open: boolean; fields: Edit[]; onClose: () => void; onSubmit: (v: Record<string, Value>) => Promise<void>
}) {
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => setErr(''), [open])
  const submit = async (v: Record<string, Value>) => {
    setBusy(true)
    try {
      await onSubmit(Object.fromEntries(Object.entries(v).filter(([, x]) => x !== undefined && x !== null)))
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '처분하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onCancel={onClose} title="MRB 처분 승인" footer={null} destroyOnHidden>
      <Form layout="vertical" onFinish={submit} initialValues={Object.fromEntries(fields.map((e) => [e.key, e.value === '' ? undefined : e.value]))}>
        {fields.map((e) => (
          <Form.Item key={e.key} label={e.label} name={e.key}
            rules={e.key === 'disposition' ? [{ required: true, message: '처분을 선택하세요.' }] : []}>
            <Editor e={e} />
          </Form.Item>
        ))}
        <Form.Item label="MRB 승인 비밀번호" name="password" rules={[{ required: true, message: '비밀번호를 입력하세요.' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Button type="primary" htmlType="submit" loading={busy}>처분 승인</Button>
      </Form>
    </Modal>
  )
}

export default function RecordView() {
  const { app, model, id } = useParams()
  const label = `${app}.${model}`
  const base = `/api/records/${label}/${id}/`
  const qc = useQueryClient()
  const [form] = Form.useForm()
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [signing, setSigning] = useState(false)
  const [asking, setAsking] = useState(false)
  const [disposing, setDisposing] = useState(false)
  const q = useQuery({ queryKey: ['record', label, id], queryFn: () => api<Detail>(base) })
  const d = q.data
  useEffect(() => {
    if (d) addRecent({ label: d.title, href: `/app/r/${app}/${model}/${d.id}` })
  }, [d, app, model])
  useEffect(() => {
    setEditing(false)
    setErr('')
  }, [label, id])
  if (q.isLoading) return <Spin />
  if (q.error || !d) return <Alert type="error" message={(q.error as Error)?.message ?? '기록을 열 수 없습니다.'} />

  const fresh = (next: Detail) => {
    qc.setQueryData(['record', label, id], next)
    qc.invalidateQueries({ queryKey: ['record-history', label, d.id] })
  }
  const startEdit = () => {
    form.resetFields()
    form.setFieldsValue(Object.fromEntries(d.edit.map((e) => [e.key, e.value])))
    setErr('')
    setEditing(true)
  }
  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    setErr('')
    try {
      fresh(await api<Detail>(base, { method: 'PATCH', body: JSON.stringify({ values, version: d.version }) }))
      setEditing(false)
      message.success('저장했습니다.')
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fields).length) {
        form.setFields(Object.entries(e.fields).filter(([k]) => k !== '__all__').map(([name, errors]) => ({ name, errors })))
        setErr(e.fields.__all__?.join(' ') ?? '')
      } else setErr(e instanceof Error ? e.message : '저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }
  const approve = async (password: string) => {
    fresh(await api<Detail>(base + 'approve/', { method: 'POST', body: JSON.stringify({ password }) }))
    message.success('승인했습니다.')
  }
  const dispose = async (v: Record<string, Value>) => {
    fresh(await api<Detail>(base + 'dispose/', { method: 'POST', body: JSON.stringify(v) }))
    message.success('처분했습니다.')
  }
  const requestEdit = async (v: { reason: string; password: string }) => {
    const r = await api<{ error: string | null; decide_url: string | null }>(base + 'request/',
      { method: 'POST', body: JSON.stringify({ kind: 'EDIT', ...v }) })
    if (r.decide_url) {
      location.href = r.decide_url
      return
    }
    await q.refetch()
    message.success('요청했습니다. 시스템 관리자가 승인하면 수정할 수 있습니다.')
  }

  const editable = new Map(d.edit.map((e) => [e.key, e]))
  const SIDE: Record<string, { label: string; node: ReactNode }> = {
    relations: { label: '관련 기록', node: <RelationsPanel ct={d.ct} id={d.id} /> },
    memo: { label: '메모', node: <MemoPanel ct={d.ct} id={d.id} /> },
    files: { label: '첨부', node: <AttachmentPanel ct={d.ct} id={d.id} /> },
    history: { label: '변경 이력', node: <History label={label} id={d.id} /> },
  }
  return (
    <Form form={form} component={false}>
      <SignModal open={signing} onClose={() => setSigning(false)} title="승인 서명" onSubmit={approve} />
      <EditRequestModal open={asking} onClose={() => setAsking(false)} onSubmit={requestEdit} />
      {d.dispose && <DisposeModal open={disposing} fields={d.dispose} onClose={() => setDisposing(false)} onSubmit={dispose} />}
      {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
      <RecordPage
        title={d.title}
        status={d.status ?? undefined}
        record={{ ct: d.ct, id: d.id }}
        actions={
          editing ? (
            <>
              <Button onClick={() => setEditing(false)}>취소</Button>
              <Button type="primary" loading={saving} onClick={save}>저장</Button>
            </>
          ) : (
            <>
              <Link to={d.list_url.slice(4)}><Button>{d.kind} 목록</Button></Link>
              {d.requests.edit && !d.can_change && <Button onClick={() => setAsking(true)}>수정 요청</Button>}
              {d.can_approve && <Button onClick={() => setSigning(true)}>승인</Button>}
              {d.can_dispose && <Button onClick={() => setDisposing(true)}>처분</Button>}
              {d.can_change && <Button type="primary" onClick={startEdit}>수정</Button>}
            </>
          )
        }
        menu={[
          ...(d.ct === 'core.lot' ? [{ key: 'trace', label: <a href={`/trace/?lot=${encodeURIComponent(d.title)}`}>LOT 이력 (추적)</a> }] : []),
          { key: 'admin', label: <a href={d.admin_url}>관리 화면에서 열기</a> },
        ]}
        props={d.fields.map((f) => {
          const e = editable.get(f.key)
          if (!editing || !e) return { label: f.label, node: <Go url={f.url}>{f.value || '—'}</Go> }
          return {
            label: f.label,
            node: (
              <Form.Item name={e.key} valuePropName={e.type === 'bool' ? 'checked' : 'value'} style={{ margin: 0 }}
                rules={e.required && e.type !== 'bool' ? [{ required: true, message: `${e.label}을(를) 입력하세요.` }] : []}>
                <Editor e={e} />
              </Form.Item>
            ),
          }
        })}
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
    </Form>
  )
}
