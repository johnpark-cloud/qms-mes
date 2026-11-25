import { Alert, Button, Card, Input, Popconfirm, Segmented, Select, Space, Table, Tag, Typography } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import {
  checkValues, fetchForm, ledgerQuery, lookupLot, submitInspection,
  type FormData, type LedgerData, type LedgerRow, type SubmitResult,
} from '../../api/inspect'

// 화면 표기만 IQC·LQC·OQC. 서버 코드는 INCOMING·PROCESS·OUTGOING 그대로.
const TYPES = [
  { value: 'INCOMING', label: '수입검사(IQC)' },
  { value: 'PROCESS', label: '공정검사(LQC)' },
  { value: 'OUTGOING', label: '출하검사(OQC)' },
]
const NG = 'var(--sapNegativeColor, #bb0000)'
const OK = 'var(--sapPositiveColor, #107e3e)'

// 맨 위 「새 줄」: LOT 스캔 → 이 구분의 승인 기준 자동 선택 → 칸에 측정값 → 판정.
// 판정 규칙(승인 기준·잠금·불합격→부적합·검사원 자격·교정 기한)은 모두 서버 submit_inspection이 강제한다.
function NewRow({ kind, onLot, onSaved }: { kind: string; onLot: (item: number) => void; onSaved: (r: SubmitResult, lot: string) => void }) {
  const [text, setText] = useState('')
  const [f, setF] = useState<FormData | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [results, setResults] = useState<Record<string, boolean | null>>({})
  const [gauge, setGauge] = useState<number | null>(null)
  const [defectType, setDefectType] = useState<string | undefined>()
  const [defectQty, setDefectQty] = useState('1')
  const [err, setErr] = useState<React.ReactNode>('')
  const [busy, setBusy] = useState(false)
  const lotInput = useRef<{ focus: () => void } | null>(null)
  const inputs = useRef<Record<number, HTMLElement | null>>({})
  const last = useRef<Record<string, number>>({})
  const seq = useRef(0)
  const label = TYPES.find((t) => t.value === kind)?.label ?? ''

  const reset = () => {
    setF(null)
    setValues({})
    setResults({})
    setGauge(null)
    setDefectType(undefined)
    setDefectQty('1')
    setText('')
    setTimeout(() => lotInput.current?.focus())
  }

  const scan = async () => {
    const number = text.trim()
    if (!number || busy) return
    setErr('')
    setBusy(true)
    try {
      const r = await lookupLot(number)
      const specs = r.specs.filter((s) => s.inspection_type === kind)
      const spec = specs.find((s) => !s.done) ?? specs[0]
      if (!spec) {
        setErr(`${r.lot.number}(${r.lot.item_code})에 승인된 ${label} 기준이 없습니다.`)
        return
      }
      const form = await fetchForm(r.lot.id, spec.id)
      setF(form)
      setValues({})
      setResults({})
      onLot(r.lot.item_id)
      const first = form.characteristics.find((c) => c.is_variable)
      setTimeout(() => first && inputs.current[first.id]?.focus())
    } catch (e) {
      if (e instanceof ApiError && e.status === 404)
        setErr(<>없는 LOT입니다. 수입 LOT은 <Link to="/inspect">검사 입력</Link>에서 입고 등록하세요.</>)
      else setErr(e instanceof ApiError ? e.detail : 'LOT을 찾지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const check = async (id: string, v: string) => {
    if (!f) return
    const mine = ++seq.current
    last.current[id] = mine
    if (!v.trim()) {
      setResults((p) => { const n = { ...p }; delete n[id]; return n })
      return
    }
    try {
      const r = await checkValues(f.spec.id, { [id]: v })
      if (last.current[id] === mine) setResults((p) => ({ ...p, ...r.results }))
    } catch {
      /* 색은 참고용. 판정 때 서버가 다시 검사한다. */
    }
  }
  const set = (id: number, v: string, now = false) => {
    setValues((p) => ({ ...p, [id]: v }))
    if (now) void check(String(id), v)
  }

  const submit = async () => {
    if (!f || busy) return
    setBusy(true)
    setErr('')
    try {
      const filled = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()))
      const r = Object.keys(filled).length ? await checkValues(f.spec.id, filled).catch(() => null) : null
      if (r) setResults((p) => ({ ...p, ...r.results }))
      if (r && Object.values(r.results).some((v) => v === false) && !defectType) {
        setErr('불합격 항목이 있습니다. 부적합 유형을 고른 뒤 다시 판정하세요.')
        return
      }
      const gauges = Object.fromEntries(f.characteristics.filter((c) => c.gauge != null).map((c) => [String(c.id), c.gauge as number]))
      const done = await submitInspection({ lot: f.lot.id, spec: f.spec.id, gauge, gauges, values, defect_type: defectType, defect_qty: defectQty.trim() })
      onSaved(done, f.lot.number)
      reset()
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '판정하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const failed = Object.values(results).some((v) => v === false)
  const noGauge = f?.characteristics.some((c) => c.is_variable && c.gauge == null)
  const judge = (
    <Button type="primary" loading={busy} disabled={!f} onClick={f?.done ? undefined : () => void submit()} data-testid="ledger-judge">
      판정
    </Button>
  )
  return (
    <Card size="small" title="새 줄 입력" style={{ marginBottom: 16 }}>
      <Space wrap align="end">
        <div>
          <div className="ledger-label">LOT</div>
          <Input
            ref={(el) => { lotInput.current = el }}
            style={{ width: 200 }}
            placeholder="LOT 번호 스캔 후 Enter"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onPressEnter={(e) => { if (!e.nativeEvent.isComposing) void scan() }}
            disabled={!!f}
            autoFocus
            aria-label="LOT 번호"
          />
        </div>
        {f?.characteristics.map((c, i) => {
          const r = results[String(c.id)]
          return (
            <div key={c.id}>
              <div className="ledger-label" title={c.spec_text}>{c.name} <span className="ledger-spec">{c.spec_text}</span></div>
              {c.is_variable ? (
                <Input
                  ref={(el) => { inputs.current[c.id] = el?.input ?? null }}
                  style={{ width: 130, color: r === true ? OK : undefined }}
                  status={r === false || r === null ? 'error' : undefined}
                  inputMode="decimal"
                  suffix={c.unit}
                  value={values[c.id] ?? ''}
                  onChange={(e) => set(c.id, e.target.value)}
                  onBlur={(e) => void check(String(c.id), e.target.value)}
                  onPressEnter={(e) => {
                    if (e.nativeEvent.isComposing) return
                    void check(String(c.id), e.currentTarget.value)
                    const n = f.characteristics.slice(i + 1).find((x) => x.is_variable)
                    if (n) inputs.current[n.id]?.focus()
                  }}
                  aria-label={c.name}
                />
              ) : (
                <Select
                  style={{ width: 90 }}
                  status={r === false ? 'error' : undefined}
                  value={values[c.id]}
                  onChange={(v) => set(c.id, v, true)}
                  options={[{ value: 'OK', label: 'OK' }, { value: 'NG', label: 'NG' }]}
                  aria-label={c.name}
                />
              )}
            </div>
          )
        })}
        {f && noGauge && (
          <div>
            <div className="ledger-label">계측기</div>
            <Select style={{ width: 180 }} allowClear placeholder="계측기" aria-label="계측기" value={gauge ?? undefined} onChange={(v) => setGauge(v ?? null)}
              options={f.gauges} notFoundContent="쓸 수 있는 계측기가 없습니다(교정 기한 확인)." />
          </div>
        )}
        {failed && (
          <>
            <div>
              <div className="ledger-label">부적합 유형</div>
              <Select style={{ width: 160 }} placeholder="고르세요" value={defectType} onChange={setDefectType}
                options={f?.defect_types.map((d) => ({ value: d, label: d }))} aria-label="부적합 유형" />
            </div>
            <div>
              <div className="ledger-label">수량</div>
              <Input style={{ width: 80 }} inputMode="decimal" value={defectQty} onChange={(e) => setDefectQty(e.target.value)} />
            </div>
          </>
        )}
        {f?.done ? (
          <Popconfirm title="재검사로 판정할까요?" okText="판정" cancelText="취소" onConfirm={() => void submit()}>{judge}</Popconfirm>
        ) : judge}
        {f && <Button onClick={reset}>취소</Button>}
      </Space>
      {f && (
        <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0' }}>
          {f.lot.number} · {f.lot.item_code} {f.lot.item_name} · {f.spec.title} · 샘플링 {f.spec.sampling}
          {f.lot.on_hold && <Tag color="red" style={{ marginInlineStart: 8 }}>보류</Tag>}
        </Typography.Paragraph>
      )}
      {f?.watch && <Alert type="warning" showIcon style={{ marginTop: 8 }} message={f.watch} />}
      {err && <Alert type="error" style={{ marginTop: 8 }} message={err} role="alert" />}
    </Card>
  )
}

export default function LedgerPage() {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const kind = TYPES.some((t) => t.value === sp.get('type')) ? (sp.get('type') as string) : TYPES[0].value
  const item = Number(sp.get('item')) || null
  const [q, setQ] = useState('')
  const [saved, setSaved] = useState<{ r: SubmitResult; lot: string } | null>(null)
  const setParam = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v)
    else n.delete(k)
    if (k === 'type') n.delete('item') // 품목 목록이 구분마다 다르다
    setSp(n, { replace: true })
  }
  const data = useInfiniteQuery({
    queryKey: ['ledger', kind, item, q],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => api<LedgerData>(`${ledgerQuery(kind, item, q)}&page=${pageParam}`),
    getNextPageParam: (last) => (last.has_more ? last.page + 1 : undefined),
  })
  const head = data.data?.pages[0]
  const rows = [...new Map((data.data?.pages.flatMap((p) => p.rows) ?? []).map((r) => [r.id, r])).values()]
  const cols = head?.columns ?? []
  return (
    <div>
      <h1 className="page-title">검사 관리대장</h1>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented value={kind} options={TYPES} onChange={(v) => { setSaved(null); setParam('type', String(v)) }} />
        <Select
          style={{ width: 260 }}
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="품목을 고르면 검사항목이 열로 붙습니다"
          value={item ?? undefined}
          onChange={(v) => setParam('item', v ? String(v) : null)}
          options={head?.items}
          aria-label="품목"
        />
        <Input.Search style={{ width: 220 }} allowClear placeholder={kind === 'INCOMING' ? 'LOT·공급자' : 'LOT·작업지시'} onSearch={setQ} />
        <Button href={`${ledgerQuery(kind, item, q)}&export=xlsx`}>엑셀로 받기</Button>
      </Space>
      <NewRow
        kind={kind}
        onLot={(id) => { if (id !== item) setParam('item', String(id)) }}
        onSaved={(r, lot) => { setSaved({ r, lot }); void data.refetch() }}
      />
      {saved && (
        <Alert
          style={{ marginBottom: 12 }}
          closable
          onClose={() => setSaved(null)}
          type={saved.r.result === 'PASS' ? 'success' : 'error'}
          role="status"
          message={
            <>
              {saved.lot} {saved.r.result_display}
              {saved.r.nonconformance && <> — 부적합 <Link to={`/r/core/nonconformance/${saved.r.nonconformance.id}`}>{saved.r.nonconformance.number}</Link> 등록, LOT 보류</>}
              {' · '}<Link to={`/inspections/${saved.r.id}/print`}>성적서</Link>
            </>
          }
        />
      )}
      {data.error && <Alert type="error" style={{ marginBottom: 12 }} message={data.error instanceof ApiError ? data.error.detail : '불러오지 못했습니다.'} />}
      <Typography.Text type="secondary">
        {head ? `${head.count}건` : '불러오는 중'}{!item && head?.items.length ? ' · 품목을 고르면 측정값이 열로 보입니다.' : ''}
      </Typography.Text>
      <Table<LedgerRow>
        size="small"
        style={{ marginTop: 8 }}
        rowKey="id"
        loading={data.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        rowClassName={(r) => (r.result === 'FAIL' ? 'row-ng' : '')}
        onRow={(r) => ({ onClick: () => nav(`/inspections/${r.id}`), style: { cursor: 'pointer' } })}
        columns={[
          { title: '검사 일시', dataIndex: 'inspected_at', render: (v: string) => v.slice(0, 16).replace('T', ' ') },
          { title: 'LOT', dataIndex: 'lot_number' },
          { title: '품번', dataIndex: 'item_code' },
          { title: '품명', dataIndex: 'item_name' },
          { title: kind === 'INCOMING' ? '공급자' : '작업지시', dataIndex: 'source', render: (v: string) => v || '—' },
          { title: '검사자', dataIndex: 'inspector' },
          ...cols.map((c) => ({
            key: `c:${c.name}`,
            title: <span title={c.spec_text}>{c.name}<div className="ledger-spec">{c.spec_text}</div></span>,
            align: 'right' as const,
            render: (_: unknown, r: LedgerRow) => {
              const m = r.values[c.name]
              if (!m || m.value == null) return '—'
              return <span style={m.passed === false ? { color: NG, fontWeight: 600 } : undefined}>{m.value}</span>
            },
          })),
          {
            title: '판정', dataIndex: 'result_display', align: 'center',
            render: (v: string) => <Tag color={v === '합격' ? 'green' : v === '불합격' ? 'red' : undefined} style={{ marginInlineEnd: 0 }}>{v}</Tag>,
          },
          {
            title: '부적합', dataIndex: 'nc_number',
            render: (v: string, r) => (v ? <a href={r.nc_url} onClick={(e) => { e.preventDefault(); e.stopPropagation(); nav(r.nc_url.replace(/^\/app/, '')) }}>{v}</a> : '—'),
          },
        ]}
      />
      {data.hasNextPage && (
        <Button style={{ marginTop: 12 }} loading={data.isFetchingNextPage} onClick={() => void data.fetchNextPage()}>더 보기</Button>
      )}
    </div>
  )
}
