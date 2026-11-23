import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Select, Space, Table } from 'antd'
import dayjs from 'dayjs'
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
// 칸마다 무엇을 적을지(서버가 모델 정의에서 만든다). 엑셀 빈 양식의 「작성 안내」 시트와 같은 내용
interface Guide {
  key: string
  label: string
  required: boolean
  hint: string
  example: string
}
interface Target {
  key: string
  label: string
  headers: Record<string, string>
  guide: Guide[]
}
interface Measure {
  label: string
  columns: Record<string, string>
  guide: Guide[]
}
// 확정한 들여오기 한 번(원본 파일 보관). 대상 기록을 볼 수 있는 것만 서버가 준다
interface Log {
  id: number
  created_at: string
  user: string
  label: string
  file_name: string
  count: number
  profile: string
  url: string
}
interface Preview {
  count: number
  errors: string[]
  rows: { line: number; values: Record<string, string> }[]
}

const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

export default function ImportPage() {
  const profiles = useQuery({ queryKey: ['import-profiles'], queryFn: () => api<Profile[]>('/api/core/import/profiles/') })
  const targets = useQuery({ queryKey: ['import-targets'], queryFn: () => api<Target[]>('/api/core/import/targets/') })
  // 검사 권한이 없거나 검사 모듈이 꺼져 있으면 서버가 거부하고 선택지에서 빠진다
  const measure = useQuery({ queryKey: ['import-measure'], queryFn: () => api<Measure>('/api/qms/inspect/upload/'), retry: false })
  const logs = useQuery({ queryKey: ['import-logs'], queryFn: () => api<Log[]>('/api/core/import/logs/') })
  // 'p:3'은 가져오기 설정, 't:qms.gauge'는 빈 양식(표준 열 제목), 'm'은 측정 원자료(검사 판정)
  const [choice, setChoice] = useState<string>()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [done, setDone] = useState<number | null>(null)
  const [commitErrors, setCommitErrors] = useState<string[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const profile = profiles.data?.find((p) => `p:${p.id}` === choice)
  const target = targets.data?.find((t) => `t:${t.key}` === choice)
  const isMeasure = choice === 'm' && !!measure.data
  const mapping = profile?.mapping ?? target?.headers ?? (isMeasure ? measure.data!.columns : {})
  // 가져오기 설정은 회사 열 제목으로 받으므로 칸 이름 옆에 그 열 제목을 보여 준다
  const guideTarget = target ?? targets.data?.find((t) => t.key === profile?.target)
  const guide = isMeasure ? measure.data!.guide : (guideTarget?.guide ?? [])
  const templateUrl = target ? `/api/core/import/template/?target=${encodeURIComponent(target.key)}` : isMeasure ? '/api/qms/inspect/upload/template/?' : ''

  const run = async (commit: '0' | '1') => {
    setErr('')
    setBusy(true)
    try {
      // FormData 본문은 api()가 Content-Type 을 건드리지 않으므로 브라우저가 경계값을 붙인다.
      const body = new FormData()
      if (target) body.append('target', target.key)
      else if (profile) body.append('profile', String(profile.id))
      body.append('file', file!)
      body.append('commit', commit)
      const r = await api<Preview>(isMeasure ? '/api/qms/inspect/upload/' : '/api/core/import/', { method: 'POST', body })
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
        logs.refetch()
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

  const columns = [
    { title: '행', dataIndex: 'line', width: 70 },
    ...Object.keys(mapping).map((f) => ({ title: profile ? `${f} (${mapping[f]})` : mapping[f], render: (_: unknown, r: Preview['rows'][number]) => r.values[f] })),
  ]
  const canCommit = !!preview && preview.errors.length === 0 && preview.rows.length > 0

  return (
    <div>
      <h1 className="page-title">엑셀 일괄 등록</h1>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          aria-label="가져오기 설정"
          style={{ minWidth: 280 }}
          placeholder="종류(빈 양식) 또는 가져오기 설정 선택"
          showSearch
          optionFilterProp="label"
          loading={profiles.isLoading || targets.isLoading}
          // 회사 설정은 몇 개뿐이라 위에, 종류 20여 개는 아래에 둔다(검색으로 찾는다).
          options={[
            { label: '가져오기 설정', options: (profiles.data ?? []).map((p) => ({ value: `p:${p.id}`, label: `${p.name} · ${p.target_display}` })) },
            ...(measure.data ? [{ label: '검사 판정', options: [{ value: 'm', label: measure.data.label }] }] : []),
            { label: '빈 양식(표준 열 제목)', options: (targets.data ?? []).map((t) => ({ value: `t:${t.key}`, label: t.label })) },
          ]}
          value={choice}
          onChange={(v) => {
            setChoice(v)
            stale()
          }}
        />
        {templateUrl && (
          <>
            <Button href={`${templateUrl}&kind=xlsx`}>빈 양식 받기(엑셀)</Button>
            <Button href={templateUrl}>CSV</Button>
          </>
        )}
        <input
          aria-label="파일 선택"
          type="file"
          accept=".xlsx,.csv"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            stale()
          }}
        />
        <Button type="primary" disabled={!(profile || target || isMeasure) || !file} loading={busy} onClick={() => run('0')}>
          미리보기
        </Button>
        <Button disabled={!canCommit || busy} onClick={() => run('1')}>
          확정
        </Button>
      </Space>
      {guide.length > 0 && !preview && done === null && (
        <details open={!file} style={{ marginBottom: 16 }}>
          <summary style={{ cursor: 'pointer', marginBottom: 8 }}>작성 안내 — 칸마다 적을 값 (필수 칸은 꼭 채웁니다)</summary>
          <Table
            size="small"
            rowKey="key"
            pagination={false}
            dataSource={guide.filter((g) => !profile || profile.mapping[g.key])}
            columns={[
              { title: '열 제목', width: 200, render: (_: unknown, g: Guide) => (profile ? `${profile.mapping[g.key]} (${g.label})` : g.label) },
              { title: '필수', width: 60, render: (_: unknown, g: Guide) => (g.required ? '필수' : '') },
              { title: '적는 값', dataIndex: 'hint' },
              { title: '예', dataIndex: 'example', width: 160 },
            ]}
          />
        </details>
      )}
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
      <h2 style={{ marginTop: 24 }}>들여오기 기록</h2>
      <Table
        aria-label="들여오기 기록"
        size="small"
        rowKey="id"
        loading={logs.isLoading}
        dataSource={logs.data ?? []}
        locale={{ emptyText: '확정한 들여오기가 없습니다.' }}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        scroll={{ x: 'max-content' }}
        columns={[
          { title: '들여온 일시', width: 150, render: (_: unknown, l: Log) => dayjs(l.created_at).format('YYYY-MM-DD HH:mm') },
          { title: '올린 사람', dataIndex: 'user', width: 110 },
          { title: '종류', render: (_: unknown, l: Log) => (l.profile ? `${l.label} · ${l.profile}` : l.label) },
          { title: '원본 파일', render: (_: unknown, l: Log) => <a href={l.url}>{l.file_name}</a> },
          { title: '건수', dataIndex: 'count', width: 70, align: 'right' as const },
        ]}
      />
    </div>
  )
}
