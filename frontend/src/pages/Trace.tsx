import { useQuery } from '@tanstack/react-query'
import { Alert, AutoComplete, Button, Input, Space, Spin, Tag, Typography } from 'antd'
import { Fragment, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { LotInfo } from '../api/inspect'
import { useLotOptions } from '../components/lotOptions'
import MemoPanel from '../components/MemoPanel'
import { addRecent } from '../lib/recent'

interface TraceLot extends LotInfo {
  lineage_gap: boolean
  shipments: { customer: string; shipped_at: string }[]
}
interface Event {
  at: string
  kind: 'created' | 'inspection' | 'work' | 'nc' | 'disposition' | 'shipment'
  label: string
  url: string | null
  bad: boolean
  thumb: string | null
}
interface TraceData {
  lot: TraceLot & { created_at: string }
  timeline: Event[]
  actions: { label: string; url: string }[]
  ancestors: TraceLot[]
  descendants: TraceLot[]
}

const KIND = { created: '생성', inspection: '검사', work: '공정', nc: '부적합', disposition: '처분', shipment: '출하' }

// React 로 옮긴 화면(/app/...)은 화면 전환 없이, 나머지는 기존 화면으로 연다.
const Go = ({ url, children }: { url: string; children: React.ReactNode }) =>
  url.startsWith('/app/') ? <Link to={url.slice(4)}>{children}</Link> : <a href={url}>{children}</a>

function LotChip({ lot, here }: { lot: TraceLot; here?: boolean }) {
  const body = (
    <>
      <b>{lot.number}</b>
      <div className="flow-sub">{lot.item_code} {lot.item_name}</div>
      <div className="flow-sub">
        수량 {lot.qty}
        {lot.shipments.map((s) => ` · 출하 ${s.customer}`).join('')}
      </div>
      <Space size={4} wrap>
        {lot.on_hold && <Tag color="red" style={{ margin: 0 }}>보류</Tag>}
        {lot.lineage_gap && <Tag color="orange" style={{ margin: 0 }}>계보 미등록</Tag>}
      </Space>
    </>
  )
  const cls = `flow-box${lot.on_hold ? ' flow-bad' : ''}${here ? ' flow-here' : ''}`
  return here ? <div className={cls}>{body}</div> : <Link className={cls} to={`/trace?lot=${encodeURIComponent(lot.number)}`}>{body}</Link>
}

const Column = ({ title, lots }: { title: string; lots: TraceLot[] }) => (
  <div className="flow-col">
    <div className="flow-sub">{title} {lots.length}건</div>
    {lots.length ? lots.map((l) => <LotChip key={l.id} lot={l} />) : <div className="flow-box flow-empty">없음</div>}
  </div>
)

export default function Trace() {
  const [params, setParams] = useSearchParams()
  const number = params.get('lot') ?? ''
  const [text, setText] = useState(number)
  const options = useLotOptions(text)
  const q = useQuery({
    queryKey: ['trace', number],
    queryFn: () => api<TraceData>(`/api/core/trace/?lot=${encodeURIComponent(number)}`),
    enabled: !!number,
  })
  const d = q.data
  useEffect(() => setText(number), [number])
  useEffect(() => {
    if (d) addRecent({ label: `LOT ${d.lot.number}`, href: `/app/trace?lot=${encodeURIComponent(d.lot.number)}` })
  }, [d])
  const open = (v: string) => v.trim() && setParams({ lot: v.trim() })

  return (
    <div>
      <h1 className="page-title">LOT 이력 조회</h1>
      <AutoComplete style={{ width: '100%', maxWidth: 480 }} options={options} value={text} onChange={setText} onSelect={open} defaultActiveFirstOption={false}>
        <Input.Search size="large" placeholder="LOT 번호·품번·품명·협력사로 찾기" enterButton="조회" onSearch={open} />
      </AutoComplete>
      {q.isError && <Alert style={{ marginTop: 12 }} type="error" role="alert" message={q.error instanceof ApiError ? q.error.detail : 'LOT 이력을 불러오지 못했습니다.'} />}
      {number && q.isPending && <Spin style={{ display: 'block', marginTop: 24 }} />}
      {d && (
        <div style={{ display: 'grid', gap: 24, marginTop: 20 }}>
          <Space wrap>
            {d.actions.map((a) => <Button key={a.label} href={a.url}>{a.label}</Button>)}
          </Space>

          <section>
            <Typography.Title level={4}>계보: 어디서 와서 어디로 갔나</Typography.Title>
            <div className="flow" data-flow="lineage">
              <Column title="투입된 LOT(상위)" lots={d.ancestors} />
              <div className="flow-arrow" aria-hidden>→</div>
              <div className="flow-col">
                <div className="flow-sub">이 LOT</div>
                <LotChip lot={d.lot} here />
              </div>
              <div className="flow-arrow" aria-hidden>→</div>
              <Column title="만들어진 LOT(하위)" lots={d.descendants} />
            </div>
          </section>

          <section>
            <Typography.Title level={4}>이력: 무슨 일이 있었나 (시간순)</Typography.Title>
            <div className="flow" data-flow="timeline">
              {d.timeline.map((e, i) => (
                <Fragment key={i}>
                  {i > 0 && <div className="flow-arrow" aria-hidden>→</div>}
                  <div className={`flow-box${e.bad ? ' flow-bad' : ''}`}>
                    <Tag color={e.bad ? 'red' : undefined} style={{ margin: 0 }}>{KIND[e.kind] ?? e.kind}</Tag>
                    <div>{e.url ? <Go url={e.url}>{e.label}</Go> : e.label}</div>
                    <div className="flow-sub">{e.at.slice(0, 16).replace('T', ' ')}</div>
                    {e.thumb && <img src={e.thumb} alt={`${e.label} 사진`} loading="lazy" style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 6 }} />}
                  </div>
                </Fragment>
              ))}
            </div>
          </section>

          <section style={{ maxWidth: 720 }}>
            <Typography.Title level={4}>메모</Typography.Title>
            <MemoPanel ct="core.lot" id={d.lot.id} />
          </section>
        </div>
      )}
    </div>
  )
}
