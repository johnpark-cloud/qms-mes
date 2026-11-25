import { useQuery } from '@tanstack/react-query'
import { Collapse, Empty, Spin, Table, Tag } from 'antd'
import { Fragment } from 'react'
import { api } from '../api/client'
import { Go } from '../pages/records/RecordView'

type Step = { label: string; at: string | null; text: string; url: string | null; bad: boolean }
type Insp = { type: string; result: string; bad: boolean; at: string; inspector: string; url: string; rows: (string | number)[][] }
type Input = { lot: string; url: string; item: string; supplier: string; iqc: string; iqc_url: string | null; bad: boolean }
type Nc = { number: string; url: string; lot: string; open: boolean; text: string; at: string }
type Change = { number: string; url: string; text: string; first_article: boolean }
type Ev = { at: string; kind: string; label: string; url: string | null; bad: boolean }
type Trace = { steps: Step[]; inspections: Insp[]; inputs: Input[]; ncs: Nc[]; changes: Change[]; on_hold: boolean; timeline: Ev[] }

const when = (at: string | null) => (at ? at.slice(0, 16).replace('T', ' ') : '')

/** 출하 이력서(P2): LOT 생성부터 출하까지의 여정과 품질 근거. 출하 기록 화면 맨 위에 붙는다. */
export default function ShipmentTrace({ id }: { id: string }) {
  const { data: d } = useQuery({ queryKey: ['trace', id], queryFn: () => api<Trace>(`/api/records/core.shipment/${id}/trace/`) })
  if (!d) return <Spin />
  return (
    <>
      <section style={{ marginBottom: 24 }}>
        <h3>출하 여정</h3>
        <div className="flow">
          {d.steps.map((s, i) => (
            <Fragment key={s.label}>
              {i > 0 && <span className="flow-arrow">→</span>}
              <Go url={s.url}>
                <div className={`flow-box${s.bad ? ' flow-bad' : ''}${!s.at ? ' flow-empty' : ''}`}>
                  <strong>{s.label}</strong>
                  {s.text && <span>{s.text}</span>}
                  <span className="flow-sub">{when(s.at) || '—'}</span>
                </div>
              </Go>
            </Fragment>
          ))}
        </div>
        {d.on_hold && <Tag color="error" style={{ marginTop: 8 }}>이 LOT은 지금 보류 중</Tag>}
      </section>
      <section style={{ marginBottom: 24 }}>
        <h3>검사 근거</h3>
        {d.inspections.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="이 LOT의 검사 기록이 없습니다" />}
        {d.inspections.map((x) => (
          <div key={x.url} style={{ marginBottom: 12 }}>
            <p>
              <Go url={x.url}><strong>{x.type}</strong></Go>{' '}
              <Tag color={x.bad ? 'error' : x.result === '합격' ? 'success' : 'default'}>{x.result}</Tag>
              <span className="flow-sub">{when(x.at)} {x.inspector}</span>
            </p>
            <Table size="small" pagination={false} rowKey={(r) => String(r[0])} dataSource={x.rows}
              columns={['검사항목', '규격', 'n', '최소', '최대', '판정'].map((t, i) => ({
                title: t, key: t, render: (_: unknown, r: (string | number)[]) => (i === 5 && r[5] !== '합격' ? <Tag color="error">{r[5]}</Tag> : r[i]),
              }))} />
          </div>
        ))}
      </section>
      <section style={{ marginBottom: 24 }}>
        <h3>투입 LOT · 수입검사</h3>
        {d.inputs.length === 0 ? <p className="flow-sub">이어진 투입 LOT이 없습니다</p> : (
          <Table size="small" pagination={false} rowKey="lot" dataSource={d.inputs} columns={[
            { title: 'LOT', key: 'lot', render: (_, r: Input) => <Go url={r.url}>{r.lot}</Go> },
            { title: '품목', dataIndex: 'item' },
            { title: '공급자', dataIndex: 'supplier' },
            { title: '수입검사', key: 'iqc', render: (_, r: Input) => <Go url={r.iqc_url}><Tag color={r.bad ? 'error' : r.iqc === '합격' ? 'success' : 'default'}>{r.iqc}</Tag></Go> },
          ]} />
        )}
      </section>
      {(d.ncs.length > 0 || d.changes.length > 0) && (
        <section style={{ marginBottom: 24 }}>
          <h3>부적합 · 변경점</h3>
          {d.ncs.map((n) => (
            <p key={n.url}>
              <Go url={n.url}>{n.number}</Go> <span className="flow-sub">{n.lot} · {when(n.at)}</span>{' '}
              <Tag color={n.open ? 'error' : 'default'}>{n.open ? `미종결 · ${n.text}` : n.text}</Tag>
            </p>
          ))}
          {d.changes.map((c) => (
            <p key={c.url}>
              <Go url={c.url}>{c.number}</Go> <span className="flow-sub">4M {c.text}</span>{' '}
              <Tag color={c.first_article ? 'success' : 'error'}>{c.first_article ? '초품 합격' : '초품 미확인'}</Tag>
            </p>
          ))}
        </section>
      )}
      <Collapse style={{ marginBottom: 24 }} items={[{
        key: 't', label: `LOT 전체 이력 ${d.timeline.length}건`,
        children: d.timeline.map((e, i) => (
          <p key={i} style={{ margin: '4px 0', color: e.bad ? 'var(--app-error)' : undefined }}>
            <span className="flow-sub">{when(e.at)}</span> <Go url={e.url}>{e.label}</Go>
          </p>
        )),
      }]} />
    </>
  )
}
