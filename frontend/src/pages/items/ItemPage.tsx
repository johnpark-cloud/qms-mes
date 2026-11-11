import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Input, Select, Typography, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import type { ItemDetail } from '../../api/master'
import EditGrid, { isBlank, withTail, type GridColumn, type GridRow } from '../../components/EditGrid'
import MemoPanel from '../../components/MemoPanel'
import RecordPage from '../../components/RecordPage'
import SaveBar from '../../components/SaveBar'
import { addRecent } from '../../lib/recent'

const BOM_FIELDS = ['component', 'qty']
const ROUTING_FIELDS = ['seq', 'process']
const norm = (v: unknown) => String(v ?? '')
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)

const bomColumns = (d: ItemDetail): GridColumn[] => [
  { key: 'component', label: '자품번', kind: 'select', options: d.item_options },
  { key: 'qty', label: '소요량', kind: 'number', width: 140 },
]
const routingColumns = (d: ItemDetail): GridColumn[] => [
  { key: 'seq', label: '순서', kind: 'number', width: 100 },
  { key: 'process', label: '공정', kind: 'select', options: d.process_options },
]
const bomRows = (d: ItemDetail): GridRow[] => d.bom.map((b) => ({ _key: `b${b.id}`, id: b.id, component: b.component, qty: b.qty }))
const routingRows = (d: ItemDetail): GridRow[] => d.routing.map((r) => ({ _key: `r${r.id}`, id: r.id, seq: r.seq, process: r.process }))

// 줄을 고르는 방식이 SpecPage 와 같다: 바뀐 줄만 보내고, 오류 키의 줄 번호(보낸 배열 기준)를 화면 줄 번호로 되돌린다.
function useTable(columns: GridColumn[], fields: string[], base: Map<number, Record<string, unknown>>) {
  const touched = (r: GridRow) => {
    if (r.id === null) return !isBlank(r, columns) && !r.delete
    return !!r.delete || fields.some((f) => norm(r[f]) !== norm(base.get(r.id!)?.[f]))
  }
  const build = (rows: GridRow[]) => {
    const sent: number[] = []
    const payload = rows.flatMap((r, i) => {
      if (!touched(r)) return []
      sent.push(i)
      return [{ id: r.id, delete: r.delete || undefined, ...Object.fromEntries(fields.map((f) => [f, r[f] ?? ''])) }]
    })
    return { sent, payload }
  }
  return { touched, build }
}

export default function ItemPage() {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['item', id], queryFn: () => api<ItemDetail>(`/api/core/items/${id}/`) })
  const d = q.data

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [type, setType] = useState('')
  const [bom, setBom] = useState<GridRow[]>([])
  const [routing, setRouting] = useState<GridRow[]>([])
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [saveErr, setSaveErr] = useState('')
  const [conflict, setConflict] = useState('')

  const bc = useMemo(() => (d ? bomColumns(d) : []), [d])
  const rc = useMemo(() => (d ? routingColumns(d) : []), [d])

  const reset = (x: ItemDetail) => {
    setCode(x.code)
    setName(x.name)
    setType(x.item_type)
    setBom(withTail(bomRows(x), bomColumns(x), !x.editable))
    setRouting(withTail(routingRows(x), routingColumns(x), !x.editable))
    setErrors({})
    setSaveErr('')
    setConflict('')
  }
  useEffect(() => {
    if (d) {
      reset(d)
      addRecent({ label: d.title, href: '/app/items/' + d.id })
    }
  }, [d]) // eslint-disable-line react-hooks/exhaustive-deps

  const bomBase = useMemo(() => new Map((d?.bom ?? []).map((b) => [b.id, b as unknown as Record<string, unknown>])), [d])
  const routingBase = useMemo(() => new Map((d?.routing ?? []).map((r) => [r.id, r as unknown as Record<string, unknown>])), [d])
  const bt = useTable(bc, BOM_FIELDS, bomBase)
  const rt = useTable(rc, ROUTING_FIELDS, routingBase)
  const propsChanged = d ? [code !== d.code, name !== d.name, type !== d.item_type].filter(Boolean).length : 0
  const count = bom.filter(bt.touched).length + routing.filter(rt.touched).length + propsChanged

  const save = useMutation({
    mutationFn: async () => {
      const b = bt.build(bom)
      const r = rt.build(routing)
      try {
        return await api<ItemDetail>(`/api/core/items/${id}/`, {
          method: 'PUT',
          body: JSON.stringify({ code, name, item_type: type, bom: b.payload, routing: r.payload, version: d!.version }),
        })
      } catch (e) {
        if (e instanceof ApiError && e.status === 400) {
          const mapped: Record<string, string[]> = {}
          for (const [k, v] of Object.entries(e.fields)) {
            const m = k.match(/^(bom|routing)\.(\d+)\.(.+)$/)
            mapped[m ? `${m[1]}.${(m[1] === 'bom' ? b : r).sent[Number(m[2])]}.${m[3]}` : k] = v
          }
          setErrors(mapped)
        }
        throw e
      }
    },
    onSuccess: (x) => {
      message.success('저장했습니다')
      qc.setQueryData(['item', id], x)
      reset(x)
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) setConflict(e.detail)
      else setSaveErr(errText(e, '저장하지 못했습니다.'))
    },
  })

  const reload = async () => {
    const x = await api<ItemDetail>(`/api/core/items/${id}/`)
    qc.setQueryData(['item', id], x)
    reset(x)
  }

  if (!d) return q.error ? <Alert type="error" message={errText(q.error, '불러오지 못했습니다.')} /> : <p>불러오는 중</p>

  const readOnly = !d.editable
  const isCell = (k: string) => /^(bom|routing)\.\d+\./.test(k)
  const cellErrors = Object.keys(errors).some(isCell)
  const otherErrors = Object.entries(errors).filter(([k]) => !isCell(k))

  const props = [
    {
      label: '품번',
      node: (
        <div>
          <Input aria-label="품번" status={errors.code ? 'error' : undefined} value={code} readOnly={readOnly} onChange={(e) => setCode(e.target.value)} />
          {d.code_parts && <Typography.Text type="secondary" data-testid="code-parts">{d.code_parts}</Typography.Text>}
        </div>
      ),
    },
    { label: '품명', node: <Input aria-label="품명" status={errors.name ? 'error' : undefined} value={name} readOnly={readOnly} onChange={(e) => setName(e.target.value)} /> },
    { label: '구분', node: <Select aria-label="구분" style={{ width: 160 }} status={errors.item_type ? 'error' : undefined} disabled={readOnly} options={d.type_options} value={type} onChange={setType} /> },
  ]

  return (
    <>
      <RecordPage title={d.title} actions={null} props={props} side={[{ key: 'memo', label: '메모', node: <MemoPanel ct="core.item" id={id} /> }]}>
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
        <h3>BOM</h3>
        <EditGrid columns={bc} rows={bom} onChange={setBom} readOnly={readOnly} errors={errors} errorPrefix="bom" canDelete={d.can_delete_rows.bom} />
        <h3 style={{ marginTop: 24 }}>라우팅</h3>
        <EditGrid columns={rc} rows={routing} onChange={setRouting} readOnly={readOnly} errors={errors} errorPrefix="routing" canDelete={d.can_delete_rows.routing} />
      </RecordPage>
      {!readOnly && (
        <SaveBar count={count} saving={save.isPending} conflict={conflict} onSave={() => save.mutate()} onCancel={() => reset(d)} onReload={() => reload().catch((e) => setSaveErr(errText(e, '다시 불러오지 못했습니다.')))} />
      )}
    </>
  )
}
