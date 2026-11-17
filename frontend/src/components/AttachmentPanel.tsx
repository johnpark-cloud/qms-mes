import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Popconfirm, Select, Spin, Typography } from 'antd'
import { useRef, useState } from 'react'
import { ApiError, api } from '../api/client'

interface AttachmentRow {
  id: number
  title: string
  kind: string
  kind_label: string
  url: string
  uploaded_by: string
  uploaded_at: string
  size: number | null
  can_delete: boolean
}
interface AttachmentList {
  results: AttachmentRow[]
  can_add: boolean
  kinds: { value: string; label: string }[]
}

// 기록에 붙은 파일(성적서·사진·도면 등). 목록·올리기·지우기(올린 사람·시스템 관리자, 승인된 기록은 서버가 막는다).
export default function AttachmentPanel({ ct, id }: { ct: string; id: number }) {
  const qc = useQueryClient()
  const key = ['attachments', ct, id]
  const q = useQuery({ queryKey: key, queryFn: () => api<AttachmentList>(`/api/attachments/?ct=${ct}&id=${id}`) })
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [kind, setKind] = useState('etc')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const upload = async () => {
    if (!file) return
    setBusy(true)
    setErr('')
    const body = new FormData()
    body.append('ct', ct)
    body.append('id', String(id))
    body.append('kind', kind)
    body.append('file', file)
    try {
      await api('/api/attachments/', { method: 'POST', body })
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '올리지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: key })
    await qc.invalidateQueries({ queryKey: ['relations', ct, id] })
    await qc.invalidateQueries({ queryKey: ['record-history', ct, id] })
  }

  const remove = async (pk: number) => {
    setErr('')
    try {
      await api(`/api/attachments/${pk}/`, { method: 'DELETE' })
      await refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '지우지 못했습니다.')
    }
  }

  if (q.isError) return <Alert type="error" message={q.error instanceof ApiError ? q.error.detail : '첨부를 불러오지 못했습니다.'} />
  if (!q.data) return <Spin />
  const { results, can_add, kinds } = q.data
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {results.length === 0 ? (
        <Typography.Text type="secondary">붙은 파일이 없습니다.</Typography.Text>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
          {results.map((a) => (
            <li key={a.id} data-attachment={a.id} style={{ overflowWrap: 'anywhere' }}>
              <a href={a.url}>{a.title}</a>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {a.kind_label} · {a.uploaded_by || '—'} · {a.uploaded_at.slice(0, 10)}
                  {a.size === null && ' · 파일 없음'}
                </Typography.Text>
                {a.can_delete && (
                  <Popconfirm title="이 파일을 지울까요?" description="파일은 지워지고 이력에 이름만 남습니다." okText="지우기" cancelText="취소"
                    onConfirm={() => remove(a.id)}>
                    <Button type="link" danger size="small">지우기</Button>
                  </Popconfirm>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {can_add && (
        <div style={{ display: 'grid', gap: 8 }}>
          <Select aria-label="첨부 종류" value={kind} onChange={setKind} options={kinds} />
          <input
            ref={fileRef}
            type="file"
            aria-label="첨부 파일"
            hidden
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', minWidth: 0 }}>
            <Button onClick={() => fileRef.current?.click()}>파일 고르기</Button>
            <Typography.Text ellipsis style={{ flex: 1, minWidth: 0 }}>
              {file?.name ?? ''}
            </Typography.Text>
          </div>
          <Button type="primary" disabled={!file} loading={busy} onClick={() => void upload()}>
            올리기
          </Button>
        </div>
      )}
      {err && <Alert type="error" message={err} role="alert" />}
    </div>
  )
}
