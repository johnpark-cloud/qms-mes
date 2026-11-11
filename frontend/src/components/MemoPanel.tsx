import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Input, Select, Space, Spin, Tag, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'

interface Memo {
  id: number
  body: string
  speaker_kind: string
  speaker: string
  speaker_name: string
  author: string
  created_at: string
  audit: string
  photos: { id: number; url: string }[]
  can_edit: boolean
  can_link: boolean
}
interface MemoList {
  results: Memo[]
  can_add: boolean
  speakers: { value: string; label: string }[]
  kinds: string[]
}

const errText = (e: unknown) => (e instanceof ApiError ? e.detail : '저장하지 못했습니다.')

// 메모 쓰기·고치기: 내용 한 칸 + 누가 한 말인지 + 사진. 저장하면 바로 목록에 보인다.
function MemoForm({ url, init, speakers, onDone, onCancel }: { url: string; init?: Memo; speakers: MemoList['speakers']; onDone: () => void; onCancel?: () => void }) {
  const [body, setBody] = useState(init?.body ?? '')
  const [kind, setKind] = useState(init?.speaker_kind ?? 'INTERNAL')
  const [name, setName] = useState(init?.speaker_name ?? '')
  const [files, setFiles] = useState<File[]>([])
  const picker = useRef<HTMLInputElement>(null)
  const previews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files])
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews])
  const addFiles = (list: Iterable<File>) => setFiles((cur) => [...cur, ...[...list].filter((f) => f.type.startsWith('image/'))])
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const save = async () => {
    if (!body.trim() || saving) return
    const data = new FormData()
    data.append('body', body)
    data.append('speaker_kind', kind)
    data.append('speaker_name', name)
    files.forEach((f) => data.append('photos', f))
    setSaving(true)
    setErr('')
    try {
      await api(url, { method: 'POST', body: data })
      if (!init) {
        setBody('')
        setFiles([])
      }
      onDone()
    } catch (e) {
      setErr(errText(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <Input.TextArea
        aria-label="메모 내용"
        placeholder="메모를 적고 Ctrl+Enter로 저장 · 사진은 Ctrl+V로 붙여넣어도 됩니다"
        rows={4}
        style={{ resize: 'none' }}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onPaste={(e) => addFiles(e.clipboardData.files)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void save()
        }}
      />
      <Space wrap>
        <Select aria-label="말한 사람" style={{ width: 110 }} options={speakers} value={kind} onChange={setKind} />
        <Input aria-label="이름" placeholder="이름(선택)" style={{ width: 140 }} value={name} onChange={(e) => setName(e.target.value)} />
        <Button onClick={() => picker.current?.click()}>사진 첨부</Button>
        <input
          ref={picker}
          hidden
          type="file"
          accept="image/*"
          multiple
          aria-label="사진"
          onChange={(e) => {
            addFiles(e.target.files ?? [])
            e.target.value = ''
          }}
        />
      </Space>
      {files.length > 0 && (
        <Space wrap>
          {previews.map((u, i) => (
            <div key={u} style={{ position: 'relative' }}>
              <img src={u} alt={`첨부할 사진 ${i + 1}`} style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 6, display: 'block' }} />
              <Button
                size="small"
                shape="circle"
                aria-label={`사진 ${i + 1} 빼기`}
                style={{ position: 'absolute', top: -8, right: -8 }}
                onClick={() => setFiles(files.filter((_, j) => j !== i))}
              >
                ×
              </Button>
            </div>
          ))}
        </Space>
      )}
      {err && <Alert type="error" message={err} role="alert" />}
      <Space>
        <Button type="primary" loading={saving} disabled={!body.trim()} onClick={() => void save()}>
          {init ? '고치기 저장' : '메모 저장'}
        </Button>
        {onCancel && <Button onClick={onCancel} disabled={saving}>취소</Button>}
      </Space>
    </div>
  )
}

// 미분류 메모를 종류 + 번호로 기록에 붙인다.
function LinkForm({ memo, kinds, onDone }: { memo: Memo; kinds: string[]; onDone: () => void }) {
  const [kind, setKind] = useState(kinds[0])
  const [number, setNumber] = useState('')
  const [err, setErr] = useState('')
  const link = async () => {
    if (!number.trim()) return
    setErr('')
    try {
      await api(`/api/qms/memos/${memo.id}/link/`, { method: 'POST', body: JSON.stringify({ kind, number }) })
      onDone()
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '연결하지 못했습니다.')
    }
  }
  return (
    <div style={{ marginTop: 8 }}>
      <Space.Compact>
        <Select aria-label="연결할 기록 종류" style={{ width: 100 }} options={kinds.map((k) => ({ value: k, label: k }))} value={kind} onChange={setKind} />
        <Input aria-label="연결할 기록 번호" placeholder="번호" style={{ width: 180 }} value={number} onChange={(e) => setNumber(e.target.value)} onPressEnter={() => void link()} />
        <Button onClick={() => void link()}>기록에 연결</Button>
      </Space.Compact>
      {err && <Alert style={{ marginTop: 8 }} type="error" message={err} role="alert" />}
    </div>
  )
}

// 기록에 붙은 메모(ct·id) 또는 미분류 메모(ct 없음): 쓰는 칸이 위, 적힌 메모가 아래(최신부터 서버 순서).
export default function MemoPanel({ ct, id, link = false }: { ct?: string; id?: number; link?: boolean }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<number | null>(null)
  const url = `/api/qms/memos/${ct ? `?ct=${ct}&id=${id}` : ''}`
  const q = useQuery({ queryKey: ['memos', ct ?? '', id ?? 0], queryFn: () => api<MemoList>(url) })
  const refresh = () => {
    setEditing(null)
    void queryClient.invalidateQueries({ queryKey: ['memos'] })
    void queryClient.invalidateQueries({ queryKey: ['todo'] }) // 내 할 일의 '미분류 메모' 건수
  }
  if (q.isError) return <Alert type="error" message={q.error instanceof ApiError ? q.error.detail : '메모를 불러오지 못했습니다.'} />
  if (!q.data) return <Spin />
  const { results, can_add, speakers, kinds } = q.data
  return (
    <div style={{ display: 'grid', gap: 12 }} data-memo-panel>
      {can_add && <MemoForm url={url} speakers={speakers} onDone={refresh} />}
      {!results.length && <Typography.Text type="secondary">적힌 메모가 없습니다.</Typography.Text>}
      {results.map((m) => (
        <div key={m.id} className="memo-item" data-memo={m.id}>
          {editing === m.id ? (
            <MemoForm url={`/api/qms/memos/${m.id}/`} init={m} speakers={speakers} onDone={refresh} onCancel={() => setEditing(null)} />
          ) : (
            <>
              <div className="memo-meta">
                <Tag style={{ margin: 0 }}>{m.speaker}</Tag>
                {m.speaker_name && <b>{m.speaker_name}</b>}
                <span style={{ flex: 1 }}>
                  {m.created_at.slice(0, 16).replace('T', ' ')} · {m.author} 기록{m.audit && ` · ${m.audit}`}
                </span>
                {m.can_edit && <Button size="small" type="link" style={{ padding: 0 }} onClick={() => setEditing(m.id)}>고치기</Button>}
              </div>
              <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{m.body}</div>
              {m.photos.length > 0 && (
                <Space wrap style={{ marginTop: 8 }}>
                  {m.photos.map((p) => (
                    <a key={p.id} href={p.url} target="_blank" rel="noreferrer">
                      <img src={p.url} alt="메모 사진" loading="lazy" style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 6 }} />
                    </a>
                  ))}
                </Space>
              )}
              {link && m.can_link && <LinkForm memo={m} kinds={kinds} onDone={refresh} />}
            </>
          )}
        </div>
      ))}
    </div>
  )
}
