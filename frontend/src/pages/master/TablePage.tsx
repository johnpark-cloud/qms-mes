import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../../api/client'
import type { TableData } from '../../api/master'
import EditGrid, { isBlank, withTail, type GridColumn, type GridRow } from '../../components/EditGrid'
import SaveBar from '../../components/SaveBar'

interface Props {
  title: string
  endpoint: string
  columns: GridColumn[]
  exportName: string
}

const norm = (v: unknown) => String(v ?? '')
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

// 공정·고객사별 8D 기한처럼 모델 전체를 한 표로 고치는 화면.
export default function TablePage({ title, endpoint, columns, exportName }: Props) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['table', endpoint], queryFn: () => api<TableData>(endpoint) })
  const d = q.data
  const [rows, setRows] = useState<GridRow[]>([])
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [saveErr, setSaveErr] = useState('')
  const [conflict, setConflict] = useState('')

  const keys = useMemo(() => columns.map((c) => c.key), [columns])
  const reset = (x: TableData) => {
    setRows(withTail(x.rows.map((r) => ({ ...r, _key: `r${r.id}` })), columns, !x.editable))
    setErrors({})
    setSaveErr('')
    setConflict('')
  }
  useEffect(() => {
    if (d) reset(d)
  }, [d]) // eslint-disable-line react-hooks/exhaustive-deps

  const base = useMemo(() => new Map((d?.rows ?? []).map((r) => [r.id, r as Record<string, unknown>])), [d])
  const touched = (r: GridRow) => {
    if (r.id === null) return !isBlank(r, columns) && !r.delete
    return !!r.delete || keys.some((f) => norm(r[f]) !== norm(base.get(r.id!)?.[f]))
  }
  const count = rows.filter(touched).length

  const save = useMutation({
    mutationFn: async () => {
      // 바뀐 줄만 보낸다. 오류 키의 줄 번호는 보낸 배열 기준이라 화면 줄 번호로 되돌릴 표를 함께 만든다.
      const sent: number[] = []
      const payload = rows.flatMap((r, i) => {
        if (!touched(r)) return []
        sent.push(i)
        return [{ id: r.id, delete: r.delete || undefined, ...Object.fromEntries(keys.map((k) => [k, r[k] ?? ''])) }]
      })
      try {
        return await api<TableData>(endpoint, { method: 'PUT', body: JSON.stringify({ rows: payload, version: d!.version }) })
      } catch (e) {
        if (e instanceof ApiError && e.status === 400) {
          const mapped: Record<string, string[]> = {}
          for (const [k, v] of Object.entries(e.fields)) {
            const m = k.match(/^rows\.(\d+)\.(.+)$/)
            mapped[m ? `rows.${sent[Number(m[1])]}.${m[2]}` : k] = v
          }
          setErrors(mapped)
        }
        throw e
      }
    },
    onSuccess: (x) => {
      message.success('저장했습니다')
      qc.setQueryData(['table', endpoint], x)
      reset(x)
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) setConflict(e.detail)
      else setSaveErr(errText(e, '저장하지 못했습니다.'))
    },
  })

  const reload = async () => {
    const x = await api<TableData>(endpoint)
    qc.setQueryData(['table', endpoint], x)
    reset(x)
  }

  if (!d) return q.error ? <Alert type="error" message={errText(q.error, '불러오지 못했습니다.')} /> : <p>불러오는 중</p>

  const cellErrors = Object.keys(errors).some((k) => k.startsWith('rows.'))
  const otherErrors = Object.entries(errors).filter(([k]) => !k.startsWith('rows.'))

  return (
    <div style={{ paddingBottom: 72 }}>
      <h1 className="page-title">{title}</h1>
      <p>
        <a href={`${endpoint}?export=xlsx`} download={`${exportName}.xlsx`}>
          엑셀로
        </a>
      </p>
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
      <EditGrid columns={columns} rows={rows} onChange={setRows} readOnly={!d.editable} errors={errors} errorPrefix="rows" canDelete={d.can_delete} />
      {d.editable && (
        <SaveBar count={count} saving={save.isPending} conflict={conflict} onSave={() => save.mutate()} onCancel={() => reset(d)} onReload={() => reload().catch((e) => setSaveErr(errText(e, '다시 불러오지 못했습니다.')))} />
      )}
    </div>
  )
}
