import { Alert, Button, Input, Select, Space, Table, Tag } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { checkValues, fetchForm, submitInspection, type SubmitResult } from '../../api/inspect'

type Row = { id: number; name: string; spec_text: string; unit: string; is_variable: boolean; special: string }

function Verdict({ r }: { r: boolean | null | undefined }) {
  if (r === true) return <span style={{ color: 'var(--sapPositiveColor, #107e3e)' }}>합격</span>
  if (r === false) return <span style={{ color: 'var(--sapNegativeColor, #bb0000)' }}>규격 이탈</span>
  if (r === null) return <span style={{ color: 'var(--sapNegativeColor, #bb0000)' }}>숫자가 아닙니다</span>
  return null
}

export default function MeasurePage() {
  const { lotId, specId } = useParams()
  const nav = useNavigate()
  const lot = Number(lotId)
  const spec = Number(specId)
  const form = useQuery({ queryKey: ['inspect-form', lot, spec], queryFn: () => fetchForm(lot, spec), enabled: !!lot && !!spec })

  const [values, setValues] = useState<Record<string, string>>({})
  const [results, setResults] = useState<Record<string, boolean | null>>({})
  const [gauge, setGauge] = useState<number | null>(null)
  const [defectType, setDefectType] = useState<string | undefined>()
  const [defectQty, setDefectQty] = useState('1')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [done, setDone] = useState<SubmitResult | null>(null)
  const busy = useRef(false)
  const dirty = useRef<Set<string>>(new Set())
  const seq = useRef(0)
  const last = useRef<Record<string, number>>({}) // 칸별로 가장 최근에 보낸 요청 번호
  const judge = useRef<HTMLButtonElement>(null)
  const inputs = useRef<Record<number, HTMLElement | null>>({})

  // 입력이 300ms 멈추면 바뀐 칸만 모아 한 번 확인한다. 판정은 서버 응답만 쓴다.
  useEffect(() => {
    if (!dirty.current.size) return
    const t = setTimeout(async () => {
      const ids = [...dirty.current]
      dirty.current = new Set()
      const send: Record<string, string> = {}
      ids.forEach((k) => {
        if ((values[k] ?? '').trim()) send[k] = values[k]
      })
      if (!Object.keys(send).length) return
      const mine = ++seq.current
      Object.keys(send).forEach((k) => (last.current[k] = mine))
      try {
        const r = await checkValues(spec, send)
        // 칸마다 가장 최근에 보낸 요청의 응답만 쓴다.
        const fresh = Object.fromEntries(Object.entries(r.results).filter(([k]) => last.current[k] === mine))
        setResults((p) => ({ ...p, ...fresh }))
      } catch {
        /* 즉시 색은 참고용이다. 판정 때 서버가 다시 검사한다. */
      }
    }, 300)
    return () => clearTimeout(t)
  }, [values, spec])

  if (form.isPending) return <p>불러오는 중…</p>
  if (form.isError) return <Alert type="error" message={form.error instanceof ApiError ? form.error.detail : '검사 화면을 불러오지 못했습니다.'} />
  const f = form.data

  if (done)
    return (
      <div>
        <h1 className="page-title">{f.lot.number} 판정 결과</h1>
        <p style={{ fontSize: 40, fontWeight: 700, color: done.result === 'PASS' ? 'var(--sapPositiveColor, #107e3e)' : 'var(--sapNegativeColor, #bb0000)' }}>
          {done.result_display}
        </p>
        {done.nonconformance && <Alert type="error" style={{ marginBottom: 16 }} message={`부적합 ${done.nonconformance.number} 등록 — LOT이 보류되었습니다.`} />}
        <Space>
          <Button onClick={() => nav(`/inspections/${done.id}/print`)}>성적서 인쇄</Button>
          <Button type="primary" onClick={() => nav('/inspect')}>다음 LOT 스캔</Button>
        </Space>
      </div>
    )

  const set = (id: number, v: string) => {
    dirty.current.add(String(id))
    setValues((p) => ({ ...p, [id]: v }))
    if (!v.trim()) {
      last.current[String(id)] = ++seq.current // 날아가는 응답이 빈 칸에 판정을 되살리지 못하게 한다
      setResults((p) => { const n = { ...p }; delete n[id]; return n })
    }
  }
  const next = (i: number) => {
    const n = f.characteristics.slice(i + 1).find((c) => c.is_variable)
    ;(n ? inputs.current[n.id] : judge.current)?.focus()
  }
  const hasVariable = f.characteristics.some((c) => c.is_variable)
  const failed = Object.values(results).some((v) => v === false)

  const submit = async () => {
    if (busy.current) return
    busy.current = true
    setSaving(true)
    setErr('')
    try {
      setDone(
        await submitInspection({
          lot,
          spec,
          gauge,
          values,
          defect_type: defectType,
          defect_qty: defectQty.trim(),
        }),
      )
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '판정하지 못했습니다.')
    } finally {
      busy.current = false
      setSaving(false)
    }
  }

  return (
    <div>
      <h1 className="page-title">측정 입력</h1>
      <p>
        <b>{f.lot.number}</b> · {f.lot.item_code} {f.lot.item_name} · {f.spec.title} · 샘플링 {f.spec.sampling}
        {f.lot.on_hold && <Tag color="red" style={{ marginLeft: 8 }}>보류</Tag>}
      </p>
      {hasVariable && (
        <div style={{ margin: '12px 0', maxWidth: 360 }}>
          <Select
            style={{ width: '100%' }}
            allowClear
            placeholder="계측기"
            value={gauge ?? undefined}
            onChange={(v) => setGauge(v ?? null)}
            options={f.gauges}
            notFoundContent="쓸 수 있는 계측기가 없습니다(교정 기한 확인)."
          />
          {!f.gauges.length && <Alert style={{ marginTop: 8 }} type="warning" message="쓸 수 있는 계측기가 없습니다(교정 기한 확인)." />}
        </div>
      )}
      <Table<Row>
        size="small"
        pagination={false}
        rowKey="id"
        dataSource={f.characteristics}
        columns={[
          { title: '항목', dataIndex: 'name', render: (v: string, c) => <>{v}{c.special && <Tag style={{ marginLeft: 6 }}>{c.special}</Tag>}</> },
          { title: '규격', dataIndex: 'spec_text' },
          {
            title: '입력',
            render: (_, c, i) =>
              c.is_variable ? (
                <Input
                  ref={(el) => { inputs.current[c.id] = el?.input ?? null }}
                  style={{ width: 140 }}
                  inputMode="decimal"
                  value={values[c.id] ?? ''}
                  suffix={c.unit}
                  onChange={(e) => set(c.id, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter' || e.nativeEvent.isComposing) return
                    e.preventDefault()
                    next(i)
                  }}
                />
              ) : (
                <Space.Compact>
                  {['OK', 'NG'].map((o) => (
                    <Button
                      key={o}
                      type={values[c.id] === o ? 'primary' : 'default'}
                      danger={o === 'NG' && values[c.id] === 'NG'}
                      onClick={() => set(c.id, o)}
                    >
                      {o}
                    </Button>
                  ))}
                </Space.Compact>
              ),
          },
          { title: '결과', render: (_, c) => <Verdict r={results[String(c.id)]} /> },
        ]}
      />
      {failed && (
        <Space style={{ marginTop: 16 }} wrap>
          <Select style={{ width: 200 }} placeholder="불량유형" value={defectType} onChange={setDefectType} options={f.defect_types.map((d) => ({ value: d, label: d }))} />
          <Input style={{ width: 100 }} inputMode="decimal" addonBefore="수량" value={defectQty} onChange={(e) => setDefectQty(e.target.value)} />
        </Space>
      )}
      {err && <Alert style={{ marginTop: 16 }} type="error" message={err} role="alert" />}
      <div style={{ marginTop: 16 }}>
        <Button ref={judge} type="primary" loading={saving} onClick={() => void submit()}>
          판정
        </Button>
      </div>
    </div>
  )
}
