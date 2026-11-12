import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Dropdown, Form, Input, Modal, Select, Space, Tooltip, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { fetchMe } from '../../api/auth'
import { ApiError, api } from '../../api/client'
import type { PlanDetail, PlanLine } from '../../api/plans'
import type { RevLog } from '../../api/specs'
import EditGrid, { isBlank, withTail, type GridColumn, type GridRow } from '../../components/EditGrid'
import AttachmentPanel from '../../components/AttachmentPanel'
import RelationsPanel from '../../components/RelationsPanel'
import RecordPage from '../../components/RecordPage'
import SaveBar from '../../components/SaveBar'
import SignModal from '../../components/SignModal'
import { addRecent } from '../../lib/recent'
import { SAMPLING } from '../../lib/sampling'

const FIELDS = ['process', 'characteristic', 'special', 'lsl', 'usl', 'unit', 'method', 'sampling', 'inspection_type', 'reaction', 'failure_mode', 'severity', 'occurrence', 'detection'] as const
const norm = (v: unknown) => String(v ?? '')
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

const makeColumns = (d: PlanDetail): GridColumn[] => [
  { key: 'process', label: '공정', kind: 'select', options: d.process_options, width: 160 },
  { key: 'characteristic', label: '특성', kind: 'text', width: 140 },
  { key: 'special', label: '특별특성', kind: 'select', options: d.special_options, width: 110 },
  { key: 'lsl', label: '하한', kind: 'number', width: 80 },
  { key: 'usl', label: '상한', kind: 'number', width: 80 },
  { key: 'unit', label: '단위', kind: 'text', width: 70 },
  { key: 'method', label: '측정방법', kind: 'text', width: 120 },
  { key: 'sampling', label: '샘플링', kind: 'text', options: SAMPLING, width: 100 },
  { key: 'inspection_type', label: '검사 구분', kind: 'select', options: d.type_options, width: 110 },
  { key: 'reaction', label: '이상 시 조치', kind: 'text', width: 140 },
  { key: 'failure_mode', label: '잠재 고장모드', kind: 'text', width: 140 },
  { key: 'severity', label: 'S', kind: 'number', width: 50 },
  { key: 'occurrence', label: 'O', kind: 'number', width: 50 },
  { key: 'detection', label: 'D', kind: 'number', width: 50 },
]

const toRows = (d: PlanDetail): GridRow[] => d.lines.map((c) => ({ _key: `c${c.id}`, ...c }))

interface LogData {
  results: RevLog[]
  prefill: { label: string; changes: string }
}

export default function PlanPage() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  const plan = useQuery({ queryKey: ['plan', id], queryFn: () => api<PlanDetail>(`/api/qms/plans/${id}/`) })
  const logs = useQuery({ queryKey: ['plan-log', id], queryFn: () => api<LogData>(`/api/qms/plans/${id}/revision-log/`) })
  const d = plan.data

  const [rows, setRows] = useState<GridRow[]>([])
  const [stage, setStage] = useState('')
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [saveErr, setSaveErr] = useState('')
  const [conflict, setConflict] = useState('')
  const [made, setMade] = useState<{ id: number; title: string }[] | null>(null)
  const [compare, setCompare] = useState(false)
  const [signOpen, setSignOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [confirmLog, setConfirmLog] = useState<number | null>(null)

  const columns = useMemo(() => (d ? makeColumns(d) : []), [d])

  const reset = (x: PlanDetail) => {
    setRows(withTail(toRows(x), makeColumns(x), !x.editable))
    setStage(x.stage)
    setErrors({})
    setSaveErr('')
    setConflict('')
  }
  useEffect(() => {
    if (d) {
      reset(d)
      addRecent({ label: d.title, href: '/app/plans/' + d.id })
    }
  }, [d]) // eslint-disable-line react-hooks/exhaustive-deps

  const base = useMemo(() => new Map((d?.lines ?? []).map((c: PlanLine) => [c.id, c as unknown as Record<string, unknown>])), [d])
  const touched = (r: GridRow) => {
    const rid = r.id
    if (rid === null) return !isBlank(r, columns) && !r.delete
    return !!r.delete || FIELDS.some((f) => norm(r[f]) !== norm(base.get(rid)?.[f]))
  }
  const count = rows.filter(touched).length + (d && stage !== d.stage ? 1 : 0)

  const save = useMutation({
    mutationFn: async () => {
      // 바뀐 줄만 보낸다. 오류 키의 줄 번호는 보낸 배열 기준이라 화면 줄 번호로 되돌릴 표를 함께 만든다.
      const sent: number[] = []
      const payload = rows.flatMap((r, i) => {
        if (!touched(r)) return []
        sent.push(i)
        return [{ id: r.id, delete: r.delete || undefined, ...Object.fromEntries(FIELDS.map((f) => [f, f === 'process' ? (r.process ?? null) : (r[f] ?? '')])) }]
      })
      try {
        return await api<PlanDetail>(`/api/qms/plans/${id}/`, { method: 'PUT', body: JSON.stringify({ stage, lines: payload, version: d!.version }) })
      } catch (e) {
        if (e instanceof ApiError && e.status === 400) {
          const mapped: Record<string, string[]> = {}
          for (const [k, v] of Object.entries(e.fields)) {
            const m = k.match(/^lines\.(\d+)\.(.+)$/)
            mapped[m ? `lines.${sent[Number(m[1])]}.${m[2]}` : k] = v
          }
          setErrors(mapped)
        }
        throw e
      }
    },
    onSuccess: (x) => {
      message.success('저장했습니다')
      qc.setQueryData(['plan', id], x)
      qc.invalidateQueries({ queryKey: ['plan-log', id] })
      reset(x)
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) setConflict(e.detail)
      else setSaveErr(errText(e, '저장하지 못했습니다.'))
    },
  })

  const reload = async () => {
    const x = await api<PlanDetail>(`/api/qms/plans/${id}/`)
    qc.setQueryData(['plan', id], x)
    qc.invalidateQueries({ queryKey: ['plan-log', id] })
    reset(x)
  }

  const newRev = useMutation({
    mutationFn: () => api<{ id: number; created: boolean }>(`/api/qms/plans/${id}/new-revision/`, { method: 'POST' }),
    onSuccess: (r) => nav(`/plans/${r.id}`),
    onError: (e) => message.error(errText(e, '새 개정을 만들지 못했습니다.')),
  })

  const makeSpecs = useMutation({
    mutationFn: () => api<{ made: { id: number; title: string }[] }>(`/api/qms/plans/${id}/make-specs/`, { method: 'POST' }),
    onSuccess: (r) => setMade(r.made),
    onError: (e) => message.error(errText(e, '검사기준을 만들지 못했습니다.')),
  })

  const approve = async (password: string, log?: { changes: string; reason: string }) => {
    const x = await api<PlanDetail>(`/api/qms/plans/${id}/approve/`, { method: 'POST', body: JSON.stringify({ password, log, version: d?.version }) })
    qc.setQueryData(['plan', id], x)
    qc.invalidateQueries({ queryKey: ['plan-log', id] })
  }

  const confirm = async (password: string) => {
    await api<RevLog>(`/api/revision-log/${confirmLog}/approve/`, { method: 'POST', body: JSON.stringify({ password }) })
    qc.invalidateQueries({ queryKey: ['plan-log', id] })
  }

  if (!d) {
    return plan.error ? <Alert type="error" message={errText(plan.error, '불러오지 못했습니다.')} /> : <p>불러오는 중</p>
  }

  const locked = d.status === '승인됨' && !d.editable
  const readOnly = !d.editable
  const approved = d.status === '승인됨'
  const cellErrors = Object.keys(errors).some((k) => k.startsWith('lines.'))
  const otherErrors = Object.entries(errors).filter(([k]) => !k.startsWith('lines.'))

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
            { key: 'xlsx', label: <a href={`/api/qms/plans/${id}/document/?export=xlsx`} download>.xlsx</a> },
            { key: 'pdf', label: <Link to={`/plans/${id}/print`}>PDF</Link> },
          ],
        }}
      >
        <Button>내보내기 ▾</Button>
      </Dropdown>
      {d.can_make_specs && (
        <Button loading={makeSpecs.isPending} onClick={() => makeSpecs.mutate()}>
          검사기준 초안 만들기
        </Button>
      )}
      {locked && <Button href={d.edit_request_url}>수정 요청</Button>}
    </>
  )

  const props = [
    { label: '품번', node: `${d.item.code} · ${d.item.name}` },
    { label: '단계', node: <Select aria-label="단계" style={{ minWidth: 120 }} disabled={readOnly} value={stage} options={d.stage_options} onChange={setStage} /> },
    { label: '개정', node: `Rev.${d.revision}` },
    { label: '승인', node: approved ? `승인됨 · ${d.approved_by} · ${(d.approved_at ?? '').slice(0, 10)}` : '초안 — 승인 전' },
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
          { key: 'relations', label: '연결', node: <RelationsPanel ct="qms.controlplan" id={id} /> },
          { key: 'log', label: '개정 이력', node: history },
          { key: 'memo', label: '메모', node: <a href="/app/memos">미분류 메모 열기</a> },
          { key: 'files', label: '첨부', node: <AttachmentPanel ct="qms.controlplan" id={id} /> },
        ]}
      >
        {made && (
          <Alert
            style={{ marginBottom: 12 }}
            type="success"
            closable
            onClose={() => setMade(null)}
            message={made.length ? `검사기준 초안 ${made.length}건을 만들었습니다.` : '새로 만들 검사기준이 없습니다.'}
            description={made.map((m) => (
              <div key={m.id}>
                <Link to={`/specs/${m.id}`}>{m.title}</Link>
              </div>
            ))}
          />
        )}
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
        <EditGrid columns={columns} rows={rows} onChange={setRows} readOnly={readOnly} errors={errors} errorPrefix="lines" diff={compare ? d.diff : null} canDelete={d.can_delete_rows} />
      </RecordPage>
      {!readOnly && (
        <SaveBar count={count} saving={save.isPending} conflict={conflict} onSave={() => save.mutate()} onCancel={() => reset(d)} onReload={() => reload().catch((e) => setSaveErr(errText(e, '다시 불러오지 못했습니다.')))} />
      )}
      <SignModal open={signOpen} onClose={() => setSignOpen(false)} title="승인 서명" withLog={{ prefill: logs.data?.prefill.changes ?? '' }} onSubmit={approve} />
      <SignModal open={confirmLog !== null} onClose={() => setConfirmLog(null)} title="개정 이력 확정" onSubmit={confirm} />
      <LogModal open={logOpen} onClose={() => setLogOpen(false)} planId={id} prefill={logs.data?.prefill.changes ?? ''} />
    </>
  )
}

// 이력 남기기: 미리 채운 변경 내용과 사유를 받아 개정 이력(대기)으로 신청한다.
function LogModal({ open, onClose, planId, prefill }: { open: boolean; onClose: () => void; planId: number; prefill: string }) {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (v: { changes: string; reason: string }) => {
    setErr('')
    setBusy(true)
    try {
      await api<RevLog>(`/api/qms/plans/${planId}/revision-log/`, { method: 'POST', body: JSON.stringify(v) })
      await qc.invalidateQueries({ queryKey: ['plan-log', planId] })
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
