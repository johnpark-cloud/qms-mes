import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, AutoComplete, Button, Dropdown, Form, Input, Modal, Space, Tooltip, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { fetchMe } from '../../api/auth'
import { ApiError, api } from '../../api/client'
import type { RevLog, SpecDetail } from '../../api/specs'
import EditGrid, { isBlank, withTail, type GridColumn, type GridRow } from '../../components/EditGrid'
import RecordPage from '../../components/RecordPage'
import SaveBar from '../../components/SaveBar'
import SignModal from '../../components/SignModal'
import { addRecent } from '../../lib/recent'
import { SAMPLING } from '../../lib/sampling'

const FIELDS = ['name', 'lsl', 'usl', 'unit', 'special', 'plan_line'] as const
const norm = (v: unknown) => String(v ?? '')
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

const makeColumns = (d: SpecDetail): GridColumn[] => [
  { key: 'name', label: '항목명', kind: 'text' },
  { key: 'lsl', label: '하한', kind: 'number', width: 100 },
  { key: 'usl', label: '상한', kind: 'number', width: 100 },
  { key: 'unit', label: '단위', kind: 'text', width: 80 },
  { key: 'special', label: '특별특성', kind: 'select', options: d.special_options, width: 130 },
  { key: 'plan_line', label: '관리계획서 항목', kind: 'select', options: d.plan_line_options, width: 200 },
  { key: 'spc_url', label: 'SPC 관리도', kind: 'link', width: 90 },
]

const toRows = (d: SpecDetail): GridRow[] =>
  d.characteristics.map((c) => ({ _key: `c${c.id}`, id: c.id, name: c.name, lsl: c.lsl, usl: c.usl, unit: c.unit, special: c.special, plan_line: c.plan_line, spc_url: c.spc_url }))

interface LogData {
  results: RevLog[]
  prefill: { label: string; changes: string }
}

export default function SpecPage() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  const spec = useQuery({ queryKey: ['spec', id], queryFn: () => api<SpecDetail>(`/api/qms/specs/${id}/`) })
  const logs = useQuery({ queryKey: ['spec-log', id], queryFn: () => api<LogData>(`/api/qms/specs/${id}/revision-log/`) })
  const d = spec.data

  const [rows, setRows] = useState<GridRow[]>([])
  const [sampling, setSampling] = useState('')
  const [note, setNote] = useState('')
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [saveErr, setSaveErr] = useState('')
  const [conflict, setConflict] = useState('')
  const [compare, setCompare] = useState(false)
  const [signOpen, setSignOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [confirmLog, setConfirmLog] = useState<number | null>(null)

  const columns = useMemo(() => (d ? makeColumns(d) : []), [d])

  const reset = (x: SpecDetail) => {
    setRows(withTail(toRows(x), makeColumns(x), !x.editable))
    setSampling(x.sampling)
    setNote(x.note)
    setErrors({})
    setSaveErr('')
    setConflict('')
  }
  useEffect(() => {
    if (d) {
      reset(d)
      addRecent({ label: d.title, href: '/app/specs/' + d.id })
    }
  }, [d]) // eslint-disable-line react-hooks/exhaustive-deps

  const base = useMemo(() => new Map((d?.characteristics ?? []).map((c) => [c.id, c as unknown as Record<string, unknown>])), [d])
  const touched = (r: GridRow) => {
    const rid = r.id
    if (rid === null) return !isBlank(r, columns) && !r.delete
    return !!r.delete || FIELDS.some((f) => norm(r[f]) !== norm(base.get(rid)?.[f]))
  }
  const count = rows.filter(touched).length + (d && sampling !== d.sampling ? 1 : 0) + (d && note !== d.note ? 1 : 0)

  const save = useMutation({
    mutationFn: async () => {
      // 바뀐 줄만 보낸다. 오류 키의 줄 번호는 보낸 배열 기준이라 화면 줄 번호로 되돌릴 표를 함께 만든다.
      const sent: number[] = []
      const payload = rows.flatMap((r, i) => {
        if (!touched(r)) return []
        sent.push(i)
        return [{ id: r.id, delete: r.delete || undefined, name: r.name ?? '', lsl: r.lsl ?? '', usl: r.usl ?? '', unit: r.unit ?? '', special: r.special ?? '', plan_line: r.plan_line ?? null }]
      })
      try {
        return await api<SpecDetail>(`/api/qms/specs/${id}/`, { method: 'PUT', body: JSON.stringify({ sampling, note, characteristics: payload, version: d!.version }) })
      } catch (e) {
        if (e instanceof ApiError && e.status === 400) {
          const mapped: Record<string, string[]> = {}
          for (const [k, v] of Object.entries(e.fields)) {
            const m = k.match(/^characteristics\.(\d+)\.(.+)$/)
            mapped[m ? `characteristics.${sent[Number(m[1])]}.${m[2]}` : k] = v
          }
          setErrors(mapped)
        }
        throw e
      }
    },
    onSuccess: (x) => {
      message.success('저장했습니다')
      qc.setQueryData(['spec', id], x)
      qc.invalidateQueries({ queryKey: ['spec-log', id] })
      reset(x)
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) setConflict(e.detail)
      else setSaveErr(errText(e, '저장하지 못했습니다.'))
    },
  })

  const reload = async () => {
    const x = await api<SpecDetail>(`/api/qms/specs/${id}/`)
    qc.setQueryData(['spec', id], x)
    qc.invalidateQueries({ queryKey: ['spec-log', id] })
    reset(x)
  }

  const newRev = useMutation({
    mutationFn: () => api<{ id: number; created: boolean }>(`/api/qms/specs/${id}/new-revision/`, { method: 'POST' }),
    onSuccess: (r) => nav(`/specs/${r.id}`),
    onError: (e) => message.error(errText(e, '새 개정을 만들지 못했습니다.')),
  })

  const approve = async (password: string, log?: { changes: string; reason: string }) => {
    const x = await api<SpecDetail>(`/api/qms/specs/${id}/approve/`, { method: 'POST', body: JSON.stringify({ password, log, version: d?.version }) })
    qc.setQueryData(['spec', id], x)
    qc.invalidateQueries({ queryKey: ['spec-log', id] })
  }

  const confirm = async (password: string) => {
    await api<RevLog>(`/api/revision-log/${confirmLog}/approve/`, { method: 'POST', body: JSON.stringify({ password }) })
    qc.invalidateQueries({ queryKey: ['spec-log', id] })
  }

  if (!d) {
    return spec.error ? <Alert type="error" message={errText(spec.error, '불러오지 못했습니다.')} /> : <p>불러오는 중</p>
  }

  const locked = d.status === '승인됨' && !d.editable
  const readOnly = !d.editable
  const approved = d.status === '승인됨'
  const cellErrors = Object.keys(errors).some((k) => k.startsWith('characteristics.'))
  const otherErrors = Object.entries(errors).filter(([k]) => !k.startsWith('characteristics.'))

  const actions = (
    <>
      {approved && (
        <Button loading={newRev.isPending} onClick={() => newRev.mutate()}>
          새 개정
        </Button>
      )}
      {d.can_approve && (
        <Tooltip title={count > 0 ? '저장한 뒤에 승인하세요.' : ''}>
          <Button type="primary" disabled={count > 0} onClick={() => setSignOpen(true)}>
            승인 서명
          </Button>
        </Tooltip>
      )}
      {!approved && (
        <Button disabled={count > 0} onClick={() => setLogOpen(true)}>
          이력 남기기
        </Button>
      )}
      {d.prev_id !== null && (
        <Button type={compare ? 'primary' : 'default'} onClick={() => setCompare(!compare)}>
          이전 개정과 비교
        </Button>
      )}
      <Dropdown
        menu={{
          items: [
            { key: 'xlsx', label: <a href={`/api/qms/specs/${id}/document/?export=xlsx`} download>.xlsx</a> },
            { key: 'pdf', label: <Link to={`/specs/${id}/print`}>PDF</Link> },
            ...d.templates.map((t) => ({ key: `t${t.id}`, label: <a href={t.url} download>{t.name}</a> })),
          ],
        }}
      >
        <Button>내보내기 ▾</Button>
      </Dropdown>
      {locked && <Button href={d.edit_request_url}>수정 요청</Button>}
    </>
  )

  const props = [
    { label: '품번', node: `${d.item.code} · ${d.item.name}` },
    { label: '검사 구분', node: d.inspection_type_display },
    { label: '개정', node: `Rev.${d.revision}` },
    { label: '승인', node: approved ? `승인됨 · ${d.approved_by} · ${(d.approved_at ?? '').slice(0, 10)}` : '초안 — 승인 전' },
    { label: '샘플링', node: <AutoComplete aria-label="샘플링" style={{ width: '100%' }} options={SAMPLING} placeholder="고르거나 직접 입력" value={sampling} disabled={readOnly} onChange={setSampling} /> },
    { label: '비고', node: <Input.TextArea aria-label="비고" autoSize={{ minRows: 1, maxRows: 6 }} value={note} readOnly={readOnly} onChange={(e) => setNote(e.target.value)} /> },
  ]

  const history = (
    <div>
      {logs.error && <Alert type="error" message={errText(logs.error, '개정 이력을 불러오지 못했습니다.')} />}
      {logs.data && !logs.data.results.length && <p>신청된 개정 이력이 없습니다</p>}
      {logs.data?.results.map((g) => (
        <div key={g.id} style={{ borderBottom: '1px solid var(--app-border)', padding: '8px 0' }}>
          <strong>{g.label}</strong> · {g.status_display}
          <div style={{ whiteSpace: 'pre-wrap' }}>{g.changes}</div>
          {g.reason && <div className="palette-sub">사유: {g.reason}</div>}
          <div className="palette-sub">
            {g.requested_by} · {(g.requested_at ?? '').slice(0, 10)}
            {g.approved_by && ` → ${g.approved_by} · ${(g.approved_at ?? '').slice(0, 10)}`}
          </div>
          {g.status === 'PENDING' && me.data?.is_approver && (
            <Button size="small" style={{ marginTop: 4 }} onClick={() => setConfirmLog(g.id)}>
              확정
            </Button>
          )}
        </div>
      ))}
    </div>
  )

  return (
    <>
      <RecordPage
        title={d.title}
        status={locked ? '잠김' : (d.status as '초안' | '승인됨')}
        actions={actions}
        props={props}
        side={[
          { key: 'log', label: '개정 이력', node: history },
          { key: 'memo', label: '메모', node: <a href="/app/memos">미분류 메모 열기</a> },
        ]}
      >
        {(saveErr || otherErrors.length > 0) && (
          <Alert
            style={{ marginBottom: 12 }}
            type="error"
            message={saveErr || '저장하지 못했습니다.'}
            description={
              <>
                {otherErrors.map(([k, v]) => (
                  <div key={k}>{v.join(' ')}</div>
                ))}
                {cellErrors && <div>표에서 빨간 칸을 고치세요.</div>}
              </>
            }
          />
        )}
        <EditGrid columns={columns} rows={rows} onChange={setRows} readOnly={readOnly} errors={errors} diff={compare ? d.diff : null} canDelete={d.can_delete_rows} />
      </RecordPage>
      {!readOnly && (
        <SaveBar count={count} saving={save.isPending} conflict={conflict} onSave={() => save.mutate()} onCancel={() => reset(d)} onReload={() => reload().catch((e) => setSaveErr(errText(e, '다시 불러오지 못했습니다.')))} />
      )}
      <SignModal open={signOpen} onClose={() => setSignOpen(false)} title="승인 서명" withLog={{ prefill: logs.data?.prefill.changes ?? '' }} onSubmit={approve} />
      <SignModal open={confirmLog !== null} onClose={() => setConfirmLog(null)} title="개정 이력 확정" onSubmit={confirm} />
      <LogModal open={logOpen} onClose={() => setLogOpen(false)} specId={id} prefill={logs.data?.prefill.changes ?? ''} />
    </>
  )
}

// 이력 남기기: 미리 채운 변경 내용과 사유를 받아 개정 이력(대기)으로 신청한다.
function LogModal({ open, onClose, specId, prefill }: { open: boolean; onClose: () => void; specId: number; prefill: string }) {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (v: { changes: string; reason: string }) => {
    setErr('')
    setBusy(true)
    try {
      await api<RevLog>(`/api/qms/specs/${specId}/revision-log/`, { method: 'POST', body: JSON.stringify(v) })
      await qc.invalidateQueries({ queryKey: ['spec-log', specId] })
      message.success('이력을 남겼습니다')
      onClose()
    } catch (e) {
      setErr(errText(e, '이력을 남기지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onCancel={onClose} title="이력 남기기" footer={null} destroyOnHidden>
      <Form key={prefill} layout="vertical" initialValues={{ changes: prefill, reason: '' }} onFinish={submit}>
        <Form.Item label="변경 내용" name="changes">
          <Input.TextArea autoSize={{ minRows: 3, maxRows: 10 }} />
        </Form.Item>
        <Form.Item label="사유" name="reason">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Space>
          <Button type="primary" htmlType="submit" loading={busy}>
            남기기
          </Button>
          <Button onClick={onClose}>취소</Button>
        </Space>
      </Form>
    </Modal>
  )
}
