import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Checkbox, Empty, Form, Input, InputNumber, Modal, Select, Space, Spin, Table, Typography, Upload, message } from 'antd'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { fetchMe } from '../../api/auth'
import { ApiError, api } from '../../api/client'
import AttachmentPanel from '../../components/AttachmentPanel'
import MemoPanel from '../../components/MemoPanel'
import RecordPage from '../../components/RecordPage'
import type { PropItem } from '../../components/RecordPage'
import RelationsPanel from '../../components/RelationsPanel'
import ShipmentTrace from '../../components/ShipmentTrace'
import EditRequestModal from '../../components/EditRequestModal'
import SignModal from '../../components/SignModal'
import { addRecent } from '../../lib/recent'

// core/api/records.py RecordDetailView 응답
interface Field { key: string; label: string; value: string; url: string | null; due?: number } // due: 기한까지 남은 날수(지나면 음수)
interface Row {
  id: number; url: string | null; status: string | null; cells: Record<string, string>
  sheets?: { label: string; url: string }[] // 증적(PPAP 요소·심사 증적)에 이어진 문서·기록 양식지
}
interface Child { key: string; label: string; columns: { key: string; label: string }[]; rows: Row[]; add_url: string | null }
type Value = string | number | boolean | null | Record<string, string>[] | string[]
export interface Edit {
  key: string; label: string; type: 'str' | 'text' | 'int' | 'date' | 'datetime' | 'bool' | 'choice' | 'rows' | 'tags' | 'json' | 'file'; value: Value; required: boolean
  choices: { value: string; label: string }[] | null
  columns?: { key: string; label: string }[]  // type 'rows': 한 줄에 들어갈 칸
  help?: string  // type 'json': 적는 예
  hidden?: boolean  // 새로 만들기: 화면에 안 보이고 주소로 채운 값만 보낸다(CAPA 출처 기록)
}
/** 한 칸에 체크 상자로 모아 보일 예/아니오 칸들 (core/recordspec.py groups_of) */
export interface Group { label: string; keys: string[] }
interface Detail {
  ct: string; id: number; title: string; kind: string; status: string | null
  fields: Field[]; children: Child[]; side: string[]; admin_url: string | null; list_url: string; groups: Group[]
  sections: { label: string; keys: string[] }[] // 구역 카드(core/recordspec.py sections_of)
  version: number; locked: boolean; edit: Edit[]; can_change: boolean; can_approve: boolean
  can_dispose: boolean; dispose: Edit[] | null; can_close: boolean; can_ack?: boolean; links: { label: string; url: string }[]
  notices: { message: string; label: string; url: string }[] // 기록 위 안내 띠(반복 부적합 → CAPA 제안)
  requests: { edit: boolean; delete: boolean }
  // 문서 본문(W7): 칸 표 대신 아래 구역. diff = 직전 개정과 줄 비교 [' '|'+'|'-', 줄]
  body: { label: string; value: string; prev: string | null; diff: [string, string][] | null } | null
}
interface Hist { history_id: number; kind?: string; date: string; user: string; type: string; changes: { field: string; old: string; new: string }[] }

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
        <li key={`${h.kind ?? ''}${h.history_id}`} style={{ marginBottom: 12 }}>
          <div>{h.date.slice(0, 16).replace('T', ' ')} · {h.user} · {h.type}</div>
          {h.changes.map((c) => (
            <Typography.Text key={c.field} type="secondary" style={{ display: 'block' }}>{c.field}: {c.old || '—'} → {c.new || '—'}</Typography.Text>
          ))}
        </li>
      ))}
    </ul>
  )
}

// 여러 줄 입력(거래처 담당자): 한 줄에 한 사람, 줄 추가·빼기
function RowsEditor({ e, value, onChange }: { e: Edit; value?: Record<string, string>[] | null; onChange?: (v: Record<string, string>[]) => void }) {
  const rows = value ?? []
  const cols = e.columns ?? []
  const set = (i: number, k: string, v: string) => onChange?.(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {cols.map((c) => (
            <Input key={c.key} value={r[c.key] ?? ''} placeholder={c.label} aria-label={`${i + 1}번째 ${c.label}`}
              style={{ flex: c.key === 'email' ? '2 1 200px' : '1 1 120px' }}
              onChange={(ev) => set(i, c.key, ev.target.value)} />
          ))}
          <Button onClick={() => onChange?.(rows.filter((_, j) => j !== i))}>빼기</Button>
        </div>
      ))}
      <Button type="dashed" onClick={() => onChange?.([...rows, Object.fromEntries(cols.map((c) => [c.key, '']))])}>
        + {e.label} 추가
      </Button>
    </div>
  )
}

/** groups에 든 예/아니오 칸은 처음 나온 자리에 한 칸으로 모은다. rows 칸은 한 줄 전체를 쓴다. */
export function groupProps<T extends { key: string; label: string; required?: boolean; type?: string }>(
  items: T[], groups: Group[], one: (x: T) => ReactNode, many: (xs: T[]) => ReactNode, wide: (x: T) => boolean,
  empty: (xs: T[]) => boolean = () => false,
) {
  const out: PropItem[] = []
  for (const x of items) {
    const g = groups.find((g) => g.keys.includes(x.key))
    if (!g) out.push({ label: x.label, node: one(x), wide: wide(x), required: x.required && x.type !== 'bool', empty: empty([x]) })
    else if (g.keys.find((k) => items.some((y) => y.key === k)) === x.key) {
      const xs = items.filter((y) => g.keys.includes(y.key))
      out.push({ label: g.label, node: many(xs), empty: empty(xs) })
    }
  }
  return out
}

/** 기한 꼬리표: 지남(빨강) · 7일 안(주황) · 그 밖(회색) */
function Due({ days }: { days: number }) {
  const cls = days < 0 ? 'due due-late' : days <= 7 ? 'due due-soon' : 'due'
  return <span className={cls}>{days < 0 ? `${-days}일 지남` : days === 0 ? '오늘' : `D-${days}`}</span>
}

/** 문서 본문: 고칠 때는 큰 입력 칸, 볼 때는 줄바꿈 그대로 + 직전 개정과 비교 */
function BodySection({ body, editing }: { body: NonNullable<Detail['body']>; editing: boolean }) {
  const [compare, setCompare] = useState(false)
  return (
    <section style={{ marginBottom: 24 }}>
      <h3>
        {body.label}
        {body.prev && !editing && (
          <Checkbox style={{ marginLeft: 12, fontWeight: 'normal' }} checked={compare} onChange={(e) => setCompare(e.target.checked)}>
            이전 개정({body.prev})과 비교
          </Checkbox>
        )}
      </h3>
      {editing ? (
        <Form.Item name="body" style={{ margin: 0 }}>
          <Input.TextArea autoSize={{ minRows: 16 }} />
        </Form.Item>
      ) : compare && body.diff ? (
        body.diff.some(([s]) => s !== ' ') ? (
          <div className="doc-body doc-diff">
            {body.diff.map(([s, t], i) => (
              <div key={i} className={s === '+' ? 'diff-added' : s === '-' ? 'diff-removed' : undefined}>{s === ' ' ? ' ' : s} {t}</div>
            ))}
          </div>
        ) : <Typography.Text type="secondary">이전 개정과 본문이 같습니다.</Typography.Text>
      ) : (
        <div className="doc-body">{body.value || '—'}</div>
      )}
    </section>
  )
}

/** 묶음 체크 상자 입력: 칸마다 Form.Item, 이름은 상자 옆 글자로 */
export function CheckGroup({ edits }: { edits: Edit[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px' }}>
      {edits.map((e) => (
        <Form.Item key={e.key} name={e.key} valuePropName="checked" noStyle>
          <Checkbox>{e.label}</Checkbox>
        </Form.Item>
      ))}
    </div>
  )
}

// Form.Item이 넣어 주는 value·checked·onChange·id를 입력 칸에 그대로 넘긴다
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function Editor({ e, ...rest }: { e: Edit; [k: string]: any }) {
  if (e.type === 'rows') return <RowsEditor e={e} {...rest} />
  if (e.type === 'bool') return <Checkbox {...rest} />
  if (e.type === 'int') return <InputNumber style={{ width: '100%' }} {...rest} />
  if (e.type === 'date') return <Input type="date" {...rest} />
  if (e.type === 'datetime') return <Input type="datetime-local" {...rest} />
  if (e.type === 'text') return <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} {...rest} />
  if (e.type === 'json') return (
    <>
      <Input.TextArea autoSize={{ minRows: 4, maxRows: 16 }} spellCheck={false} style={{ fontFamily: 'Consolas, monospace' }} {...rest} />
      {e.help && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{e.help}</Typography.Text>}
    </>
  )
  if (e.type === 'file') return (  // 값은 antd UploadFile 하나: createRecord가 multipart로 보낸다
    <>
      <Upload maxCount={1} beforeUpload={() => false} fileList={rest.value ? [rest.value] : []}
        onChange={({ fileList }) => rest.onChange?.(fileList[0] ?? null)}>
        <Button id={rest.id}>파일 고르기</Button>
      </Upload>
      {e.help && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{e.help}</Typography.Text>}
    </>
  )
  if (e.type === 'tags') return <Select mode="tags" open={false} tokenSeparators={[',']} suffixIcon={null} placeholder="입력하고 Enter (쉼표로 여러 개)" {...rest} />
  if (e.type === 'choice') return <Select options={e.choices ?? []} showSearch optionFilterProp="label" allowClear={!e.required} {...rest} />
  return <Input {...rest} />
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
  const [deleting, setDeleting] = useState(false)
  const navigate = useNavigate()
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: Infinity }).data
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
    // 지운 칸(undefined)은 JSON에서 빠지므로 null로 보내 비운다
    const values = Object.fromEntries(Object.entries(await form.validateFields()).map(([k, v]) => [k, v ?? null]))
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
  // 종결(core.rules.close_record): 8D 전 단계·SCAR 회신·CAPA 유효 규칙 문구는 서버 그대로 보인다
  const close = () => Modal.confirm({
    title: '종결할까요?', content: '종결 일시는 지금으로 기록됩니다.', okText: '종결', cancelText: '취소',
    onOk: async () => {
      try {
        fresh(await api<Detail>(base + 'close/', { method: 'POST', body: '{}' }))
        message.success('종결했습니다.')
      } catch (e) {
        message.error(e instanceof Error ? e.message : '종결하지 못했습니다.')
      }
    },
  })
  // 열람 확인(4단계 #9): 승인된 개정을 읽었다는 본인 기록. 두 번 눌러도 한 줄
  const ack = async () => {
    fresh(await api<Detail>(base + 'ack/', { method: 'POST', body: '{}' }))
    message.success('열람 확인을 남겼습니다.')
  }
  const requestEdit = async (v: { reason: string; password: string }) => {
    const r = await api<{ error: string | null; decide_url: string | null }>(base + 'request/',
      { method: 'POST', body: JSON.stringify({ kind: 'EDIT', ...v }) })
    if (r.decide_url) {
      navigate(r.decide_url.slice(4))
      return
    }
    await q.refetch()
    message.success('요청했습니다. 시스템 관리자가 승인하면 수정할 수 있습니다.')
  }
  const requestDelete = async (v: { reason: string; password: string }) => {
    const r = await api<{ deleted: boolean; decide_url: string | null }>(base + 'request/',
      { method: 'POST', body: JSON.stringify({ kind: 'DELETE', ...v }) })
    if (r.decide_url) {
      navigate(r.decide_url.slice(4)) // 막는 기록 안내는 요청 처리 화면에서
      return
    }
    if (r.deleted) {
      message.success(`${d.title} 삭제 완료`)
      navigate(`/r/${app}/${model}`)
      return
    }
    message.success('삭제를 요청했습니다. 시스템 관리자가 승인하면 삭제됩니다.')
  }

  const editable = new Map(d.edit.map((e) => [e.key, e]))
  const SIDE: Record<string, { label: string; node: ReactNode }> = {
    relations: { label: '관련 기록', node: <RelationsPanel ct={d.ct} id={d.id} /> },
    memo: { label: '메모', node: <MemoPanel ct={d.ct} id={d.id} /> },
    files: { label: '첨부', node: <AttachmentPanel ct={d.ct} id={d.id} /> },
    history: { label: '변경 이력', node: <History label={label} id={d.id} /> },
  }
  // 다음 행동 띠: 처분 > 승인 > 열람 확인 > 지난 기한. 띠에 올린 버튼은 위 버튼 줄에서 뺀다
  const late = d.fields.find((f) => f.due !== undefined && f.due < 0)
  const next = editing ? null
    : d.can_dispose ? { key: 'dispose', tone: 'warning' as const, text: '처분 대기: MRB 처분을 정하세요. 처분 전까지 LOT 보류가 유지됩니다.',
        button: <Button type="primary" onClick={() => setDisposing(true)}>처분</Button> }
    : d.can_approve ? { key: 'approve', text: '승인 대기: 내용을 확인하고 승인 서명하세요. 승인하면 잠깁니다.',
        button: <Button type="primary" onClick={() => setSigning(true)}>승인</Button> }
    : d.can_ack ? { key: 'ack', text: '새로 승인된 개정입니다. 읽고 열람 확인을 남기세요.',
        button: <Button type="primary" onClick={ack}>읽었음 (열람 확인)</Button> }
    : late ? { key: 'late', tone: 'warning' as const, text: `${late.label}이(가) ${-late.due!}일 지났습니다.` }
    : null
  const toProps = (fields: Field[]) => groupProps(fields, d.groups ?? [],
          (f) => {
            const e = editable.get(f.key)
            if (!editing || !e) return <><Go url={f.url}>{f.value || '—'}</Go>{f.due !== undefined && <Due days={f.due} />}</>
            return (
              <Form.Item name={e.key} valuePropName={e.type === 'bool' ? 'checked' : 'value'} style={{ margin: 0 }}
                rules={e.required && e.type !== 'bool' ? [{ required: true, message: `${e.label}을(를) 입력하세요.` }] : []}>
                <Editor e={e} />
              </Form.Item>
            )
          },
          (fs) => {
            const es = fs.map((f) => editable.get(f.key)).filter((e): e is Edit => !!e)
            if (editing && es.length) return <CheckGroup edits={es} />
            return fs.filter((f) => f.value === '예').map((f) => f.label).join(', ') || '—'
          },
          // 표·긴 글·여러 줄 값(단계별 기한, 열 매핑)은 한 줄 전체를 쓴다
          (f) => {
            const t = editable.get(f.key)?.type
            return t === 'rows' || (editing && (t === 'text' || t === 'json')) || f.value.includes('\n') || f.value.length > 60
          },
    // 볼 때 빈 칸(예/아니오 묶음은 「예」가 하나도 없을 때)은 「빈 항목 N개」로 접는다
    (fs) => !editing && fs.every((f) => !f.value || (fs.length > 1 && f.value !== '예')))

  return (
    <Form form={form} component={false}>
      <SignModal open={signing} onClose={() => setSigning(false)} title="승인 서명" onSubmit={approve} />
      <EditRequestModal open={asking} title="수정 요청" onClose={() => setAsking(false)} onSubmit={requestEdit} />
      <EditRequestModal open={deleting} title={me?.is_superuser ? '삭제' : '삭제 요청'} onClose={() => setDeleting(false)} onSubmit={requestDelete} />
      {d.dispose && <DisposeModal open={disposing} fields={d.dispose} onClose={() => setDisposing(false)} onSubmit={dispose} />}
      {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
      {d.notices.map((n) => (
        <Alert key={n.message} style={{ marginBottom: 12 }} type="warning" showIcon message={n.message}
          action={n.url ? <a href={n.url}><Button size="small" type="primary">{n.label}</Button></a> : undefined} />
      ))}
      <RecordPage
        title={d.title}
        status={d.status ?? undefined}
        record={{ ct: d.ct, id: d.id }}
        onDelete={() => setDeleting(true)}
        actions={
          editing ? (
            <>
              <Button onClick={() => setEditing(false)}>취소</Button>
              <Button type="primary" loading={saving} onClick={save}>저장</Button>
            </>
          ) : (
            <>
              <Link to={d.list_url.slice(4)}><Button>{d.kind} 목록</Button></Link>
              <Link to={`/r/${app}/${model}/${id}/print`}>{label === 'core.shipment' ? <Button type="primary">출하성적서</Button> : <Button>양식지 · 인쇄</Button>}</Link>
              {d.requests.edit && !d.can_change && <Button onClick={() => setAsking(true)}>수정 요청</Button>}
              {d.can_approve && next?.key !== 'approve' && <Button onClick={() => setSigning(true)}>승인</Button>}
              {d.can_dispose && next?.key !== 'dispose' && <Button onClick={() => setDisposing(true)}>처분</Button>}
              {d.can_close && <Button onClick={close}>종결</Button>}
              {d.can_ack && next?.key !== 'ack' && <Button type="primary" onClick={ack}>읽었음 (열람 확인)</Button>}
              {d.can_change && <Button type="primary" onClick={startEdit}>수정</Button>}
            </>
          )
        }
        menu={[
          ...d.links.map((l) => ({ key: l.url, label: <a href={l.url}>{l.label}</a> })),
          ...(d.admin_url ? [{ key: 'admin', label: <a href={d.admin_url}>관리 화면에서 열기</a> }] : []),
        ]}
        props={[]}
        next={next}
        intro={label === 'core.shipment' && id ? <ShipmentTrace id={id} /> : undefined}
        sections={(d.sections ?? [{ label: '', keys: d.fields.map((f) => f.key) }]).map((sec) => ({
          label: sec.label,
          items: toProps(d.fields.filter((f) => sec.keys.includes(f.key))),
        }))}
        side={d.side.filter((k) => SIDE[k]).map((k) => ({ key: k, ...SIDE[k] }))}
      >
        {d.body && <BodySection body={d.body} editing={editing && editable.has('body')} />}
        {d.children.map((c) => (
          <section key={c.key} style={{ marginBottom: 24 }}>
            <h3>
              {c.label}
              {c.add_url && (
                <Link to={c.add_url.slice(4)} style={{ marginLeft: 12, fontSize: 14, fontWeight: 'normal' }}>
                  추가
                </Link>
              )}
            </h3>
            <Table<Row>
              className="child-table"
              size="small"
              pagination={false}
              rowKey="id"
              dataSource={c.rows}
              columns={[
                ...c.columns.map((col, i) => ({
                  title: col.label,
                  key: col.key,
                  render: (_: unknown, r: Row) => (i === 0 ? <Go url={r.url}>{r.cells[col.key] || '—'}</Go> : r.cells[col.key]),
                })),
                ...(c.rows.some((r) => r.sheets?.length)
                  ? [{
                      title: '양식지',
                      key: 'sheets',
                      render: (_: unknown, r: Row) => (
                        <Space size={12} style={{ whiteSpace: 'nowrap' }}>
                          {r.sheets?.map((s) => (
                            <a key={s.url} href={s.url} target="_blank" rel="noreferrer">{s.label.replace(' 양식지', '')}</a>
                          ))}
                        </Space>
                      ),
                    }]
                  : []),
              ]}
            />
          </section>
        ))}
      </RecordPage>
    </Form>
  )
}
