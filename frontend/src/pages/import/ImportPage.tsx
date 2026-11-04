import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Select, Space, Table } from 'antd'
import { useState } from 'react'
import { api } from '../../api/client'

interface Profile {
  id: number
  name: string
  target: string
  target_display: string
  header_row: number
  mapping: Record<string, string>
}
interface Preview {
  count: number
  errors: string[]
  rows: { line: number; values: Record<string, string> }[]
}

const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

export default function ImportPage() {
  const profiles = useQuery({ queryKey: ['import-profiles'], queryFn: () => api<Profile[]>('/api/core/import/profiles/') })
  const [profileId, setProfileId] = useState<number>()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [done, setDone] = useState<number | null>(null)
  const [commitErrors, setCommitErrors] = useState<string[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const profile = profiles.data?.find((p) => p.id === profileId)

  const run = async (commit: '0' | '1') => {
    setErr('')
    setBusy(true)
    try {
      // FormData 본문은 api()가 Content-Type 을 건드리지 않으므로 브라우저가 경계값을 붙인다.
      const body = new FormData()
      body.append('profile', String(profileId))
      body.append('file', file!)
      body.append('commit', commit)
      const r = await api<Preview>('/api/core/import/', { method: 'POST', body })
      if (commit === '0') {
        setPreview(r)
        setDone(null)
        setCommitErrors([])
      } else if (r.errors.length) {
        setCommitErrors(r.errors) // 한 줄이라도 틀리면 서버가 전체를 되돌렸다
      } else {
        setDone(r.count)
        setPreview(null)
        setCommitErrors([])
      }
    } catch (e) {
      setErr(errText(e, '처리하지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  // 설정이나 파일이 바뀌면 지난 미리보기는 더 이상 이 입력의 결과가 아니다.
  const stale = () => {
    setPreview(null)
    setDone(null)
    setCommitErrors([])
    setErr('')
  }

  const fields = profile ? Object.keys(profile.mapping) : []
  const columns = [
    { title: '행', dataIndex: 'line', width: 70 },
    ...fields.map((f) => ({ title: `${f} (${profile!.mapping[f]})`, render: (_: unknown, r: Preview['rows'][number]) => r.values[f] })),
  ]
  const canCommit = !!preview && preview.errors.length === 0 && preview.rows.length > 0

  return (
    <div>
      <h1 className="page-title">엑셀 일괄 등록</h1>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          aria-label="가져오기 설정"
          style={{ minWidth: 240 }}
          placeholder="가져오기 설정 선택"
          loading={profiles.isLoading}
          options={(profiles.data ?? []).map((p) => ({ value: p.id, label: `${p.name} · ${p.target_display}` }))}
          value={profileId}
          onChange={(v) => {
            setProfileId(v)
            stale()
          }}
        />
        <input
          aria-label="파일 선택"
          type="file"
          accept=".xlsx,.csv"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            stale()
          }}
        />
        <Button type="primary" disabled={!profileId || !file} loading={busy} onClick={() => run('0')}>
          미리보기
        </Button>
        <Button disabled={!canCommit || busy} onClick={() => run('1')}>
          확정
        </Button>
      </Space>
      {profiles.error && <Alert style={{ marginBottom: 12 }} type="error" message={errText(profiles.error, '가져오기 설정을 불러오지 못했습니다.')} />}
      {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
      {done !== null && <Alert style={{ marginBottom: 12 }} type="success" message={`${done}건 등록했습니다.`} />}
      {commitErrors.length > 0 && (
        <Alert style={{ marginBottom: 12 }} type="error" message="오류가 있어 하나도 등록하지 않았습니다." description={commitErrors.map((m, i) => <div key={i}>{m}</div>)} />
      )}
      {preview && (
        <>
          {preview.errors.length > 0 && (
            <Alert style={{ marginBottom: 12 }} type="error" message="오류를 고친 뒤 다시 미리보기 하세요." description={preview.errors.map((m, i) => <div key={i}>{m}</div>)} />
          )}
          {preview.errors.length === 0 && preview.rows.length === 0 && <Alert style={{ marginBottom: 12 }} type="warning" message="등록할 줄이 없습니다." />}
          <Table size="small" rowKey="line" columns={columns} dataSource={preview.rows} pagination={{ pageSize: 50, hideOnSinglePage: true }} scroll={{ x: 'max-content' }} />
        </>
      )}
    </div>
  )
}
