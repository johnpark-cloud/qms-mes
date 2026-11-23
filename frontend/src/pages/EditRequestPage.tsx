import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Input, Space, Spin, Tag, message } from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Go } from './records/RecordView'

// core/api/records.py EditRequestView 응답
interface Req {
  id: number; kind: string; status: string; status_label: string; object_repr: string; model: string
  target_url: string | null; reason: string; requested_by: string; requested_at: string
  decided_by: string | null; decided_at: string | null; reject_reason: string
  rows: { label: string; value: string }[]; blockers: string[]
}

const TONE: Record<string, string> = { PENDING: 'orange', APPROVED: 'green', USED: 'default', REJECTED: 'red' }
const at = (s: string | null) => (s ? s.slice(0, 16).replace('T', ' ') : '')

/** 수정·삭제 요청 처리(시스템 관리자): 대상 기록 내용·막는 기록을 보고 승인하거나 사유를 적어 거절한다. */
export default function EditRequestPage() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['edit-request', id], queryFn: () => api<Req>(`/api/edit-requests/${id}/`) })
  const [reject, setReject] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (q.isLoading) return <Spin />
  const r = q.data
  if (q.error || !r) return <Alert type="error" message={(q.error as Error)?.message ?? '요청을 열 수 없습니다.'} />

  const decide = async (approve: boolean) => {
    setBusy(true)
    setErr('')
    try {
      const d = await api<Req>(`/api/edit-requests/${id}/decide/`, { method: 'POST', body: JSON.stringify({ approve, reject_reason: reject }) })
      message.success(`${r.kind} 요청 → ${d.status_label}`)
      await qc.invalidateQueries()
      navigate('/todo')
    } catch (e) {
      setErr(e instanceof Error ? e.message : '처리하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }
  const pending = r.status === 'PENDING'
  return (
    <div style={{ maxWidth: 960 }}>
      <div className="record-head">
        <h1 className="page-title">{r.kind} 요청 처리</h1>
        <Tag color={TONE[r.status] ?? 'default'}>{r.status_label}</Tag>
      </div>
      <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="대상" span={2}>
          {r.model} · <Go url={r.target_url}>{r.object_repr}</Go>
          {!r.target_url && ' (지워짐)'}
        </Descriptions.Item>
        <Descriptions.Item label="요청자">{r.requested_by}</Descriptions.Item>
        <Descriptions.Item label="요청 일시">{at(r.requested_at)}</Descriptions.Item>
        <Descriptions.Item label="사유" span={2}><span style={{ whiteSpace: 'pre-wrap' }}>{r.reason}</span></Descriptions.Item>
        {r.decided_by && <Descriptions.Item label="처리자">{r.decided_by}</Descriptions.Item>}
        {r.decided_by && <Descriptions.Item label="처리 일시">{at(r.decided_at)}</Descriptions.Item>}
        {r.reject_reason && <Descriptions.Item label="거절 사유" span={2}>{r.reject_reason}</Descriptions.Item>}
      </Descriptions>
      {r.blockers.length > 0 && (
        <Alert style={{ marginBottom: 16 }} type="warning" showIcon message="먼저 지워야 할 기록이 있어 승인해도 삭제되지 않습니다."
          description={<ul style={{ margin: 0, paddingLeft: 18 }}>{r.blockers.map((b) => <li key={b}>{b}</li>)}</ul>} />
      )}
      {pending && (
        <div style={{ marginBottom: 24 }}>
          <Input.TextArea aria-label="거절 사유" placeholder="거절 사유 (거절할 때 필수)" autoSize={{ minRows: 2, maxRows: 5 }}
            value={reject} onChange={(e) => setReject(e.target.value)} style={{ marginBottom: 8 }} />
          {err && <Alert style={{ marginBottom: 8 }} type="error" message={err} />}
          <Space>
            <Button type="primary" danger={r.kind === '삭제'} loading={busy} onClick={() => decide(true)}>승인{r.kind === '삭제' ? '(삭제 실행)' : ''}</Button>
            <Button loading={busy} onClick={() => decide(false)}>거절</Button>
          </Space>
        </div>
      )}
      {r.rows.length > 0 && (
        <Descriptions title="대상 기록 내용" bordered size="small" column={2}
          items={r.rows.map((x, i) => ({ key: i, label: x.label, children: x.value || '—' }))} />
      )}
    </div>
  )
}
