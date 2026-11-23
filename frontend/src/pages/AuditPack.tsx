import { useQuery } from '@tanstack/react-query'
import { Alert, Button, DatePicker, Image, Select, Space, Spin, Table, Typography } from 'antd'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'

// qms/api/audit.py AuditPackView
interface Ref { number: string; text: string }
interface Pack {
  items: { id: number; label: string }[]; errors: string[]; from: string; to: string
  item: { id: number; code: string; name: string } | null
  limit?: number; truncated?: boolean; zip_url?: string
  summary?: { label: string; total: number; passed: number; rate: number | null }[]
  ncs?: { number: string; lot: string; detected_at: string; defect_type: string; defect_qty: string; description: string
          photos: string[]; disposition: string; approved: string }[]
  capas?: Ref[] | null; claims?: Ref[] | null; scars?: Ref[] | null
  changes?: { number: string; category: string; effective_at: string; description: string }[] | null
  can_plan?: boolean; plan?: { label: string; revision: string; approved_at: string } | null
  plan_lines?: { characteristic: string; process: string; failure_mode: string; severity: number; occurrence: number
                 detection: number; reaction: string }[]
  memos?: { at: string; author: string; speaker: string; body: string; photos: string[] }[] | null
}

const Empty = ({ children }: { children: string }) => <Typography.Paragraph type="secondary">{children}</Typography.Paragraph>

/** 심사 자료 출력: 품번·기간을 고르면 검사 요약·부적합·처분·CAPA·4M·관리계획서·메모를 한 장에 모아 인쇄하거나 ZIP으로 받는다. */
export default function AuditPack() {
  const [sp, setSp] = useSearchParams()
  const qs = sp.toString()
  const q = useQuery({ queryKey: ['audit-pack', qs], queryFn: () => api<Pack>(`/api/qms/audit-pack/?${qs}`) })
  const d = q.data
  const set = (k: string, v: string | undefined) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v)
    else n.delete(k)
    setSp(n)
  }
  if (q.isLoading) return <Spin />
  if (!d) return <Alert type="error" showIcon title={q.error instanceof ApiError ? q.error.detail : '불러오지 못했습니다.'} />
  const linked = d.capas != null && d.claims != null && d.scars != null
  const refs = (title: string, xs: Ref[]) => (
    <>
      <h3>{title}</h3>
      {xs.length ? <ul>{xs.map((x) => <li key={x.number}><b>{x.number}</b> {x.text}</li>)}</ul> : <Empty>없음</Empty>}
    </>
  )
  return (
    <div style={{ maxWidth: 1100 }}>
      <h1 className="page-title">심사 자료 출력{d.item ? ` · ${d.item.code} ${d.item.name}` : ''}</h1>
      <Space wrap className="print-bar" style={{ marginBottom: 16 }}>
        <Select showSearch optionFilterProp="label" placeholder="품번 선택" style={{ minWidth: 280 }} aria-label="품번"
          value={d.item?.id} options={d.items.map((i) => ({ value: i.id, label: i.label }))} onChange={(v) => set('item', String(v))} />
        <DatePicker.RangePicker aria-label="기간" allowClear={false} value={[dayjs(d.from), dayjs(d.to)]}
          onChange={(r) => {
            const n = new URLSearchParams(sp)
            if (r?.[0] && r[1]) { n.set('from', r[0].format('YYYY-MM-DD')); n.set('to', r[1].format('YYYY-MM-DD')) }
            setSp(n)
          }} />
        {d.item && <Button type="primary" onClick={() => window.print()}>인쇄(PDF)</Button>}
        {d.zip_url && <Button href={d.zip_url}>ZIP 받기 (사진·첨부 포함)</Button>}
      </Space>
      {d.errors.map((e) => <Alert key={e} type="error" showIcon style={{ marginBottom: 12 }} title={e} />)}
      {!d.item && <Alert type="info" showIcon title="품번을 고르면 기간 안 검사·부적합·처분·CAPA·4M·관리계획서·메모를 모읍니다. 기간은 기본 최근 90일입니다." />}
      {d.item && (
        <>
          <Typography.Paragraph type="secondary">기간 {d.from} ~ {d.to}</Typography.Paragraph>
          {d.truncated && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title={`기록이 ${d.limit}건을 넘어 앞 ${d.limit}건만 보여 줍니다. 기간을 줄이세요.`} />}

          <h2>1. 검사 요약</h2>
          {d.summary?.length ? (
            <Table rowKey="label" size="small" pagination={false} dataSource={d.summary} columns={[
              { title: '검사 구분', dataIndex: 'label' },
              { title: '건수', dataIndex: 'total', align: 'right' },
              { title: '합격', dataIndex: 'passed', align: 'right' },
              { title: '합격률(%)', dataIndex: 'rate', align: 'right', render: (v) => v ?? '—' },
            ]} />
          ) : <Empty>기간 안 검사 기록이 없습니다.</Empty>}

          <h2>2. 부적합 보고서</h2>
          {d.ncs?.length ? d.ncs.map((n) => (
            <section key={n.number} className="pack-nc">
              <h3>{n.number} · LOT {n.lot}</h3>
              <Typography.Paragraph type="secondary">{n.detected_at} · {n.defect_type} · {n.defect_qty}</Typography.Paragraph>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{n.description}</Typography.Paragraph>
              {n.photos.length > 0 && <Space wrap>{n.photos.map((p) => <Image key={p} src={p} width={160} alt={`${n.number} 사진`} />)}</Space>}
            </section>
          )) : <Empty>기간 안 부적합이 없습니다.</Empty>}

          <h2>3. 처분·승인</h2>
          {d.ncs?.length ? (
            <Table rowKey="number" size="small" pagination={false} dataSource={d.ncs} columns={[
              { title: '부적합', dataIndex: 'number' },
              { title: '처분', dataIndex: 'disposition' },
              { title: '승인', dataIndex: 'approved', render: (v) => v || '미승인' },
            ]} />
          ) : <Empty>없음</Empty>}

          {linked && (
            <>
              <h2>4. 연결 시정조치(CAPA)·8D·SCAR</h2>
              {refs('CAPA', d.capas!)}
              {refs('고객 클레임(8D)', d.claims!)}
              {refs('SCAR', d.scars!)}
            </>
          )}

          {d.changes != null && (
            <>
              <h2>5. 4M 변경</h2>
              {d.changes.length ? (
                <Table rowKey="number" size="small" pagination={false} dataSource={d.changes} columns={[
                  { title: '번호', dataIndex: 'number' }, { title: '구분', dataIndex: 'category' },
                  { title: '적용일', dataIndex: 'effective_at' }, { title: '내용', dataIndex: 'description' },
                ]} />
              ) : <Empty>기간 안 4M 변경이 없습니다.</Empty>}
            </>
          )}

          {d.can_plan && (
            <>
              <h2>6. 관리계획서·PFMEA</h2>
              {d.plan ? (
                <>
                  <Typography.Paragraph>{d.plan.label} (Rev {d.plan.revision}, {d.plan.approved_at} 승인)</Typography.Paragraph>
                  <Table rowKey={(r) => `${r.characteristic}-${r.process}-${r.failure_mode}`} size="small" pagination={false}
                    dataSource={d.plan_lines} scroll={{ x: true }} columns={[
                      { title: '특성', dataIndex: 'characteristic' }, { title: '공정', dataIndex: 'process' },
                      { title: '고장 모드', dataIndex: 'failure_mode' },
                      { title: 'S', dataIndex: 'severity', align: 'right' }, { title: 'O', dataIndex: 'occurrence', align: 'right' },
                      { title: 'D', dataIndex: 'detection', align: 'right' }, { title: '이상 시 조치', dataIndex: 'reaction' },
                    ]} />
                </>
              ) : <Empty>승인된 관리계획서가 없습니다.</Empty>}
            </>
          )}

          {d.memos != null && (
            <>
              <h2>7. 메모</h2>
              {d.memos.length ? d.memos.map((m, i) => (
                <section key={i} className="pack-nc">
                  <Typography.Paragraph type="secondary">{m.at} · {m.author}{m.speaker ? ` · ${m.speaker}` : ''}</Typography.Paragraph>
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{m.body}</Typography.Paragraph>
                  {m.photos.length > 0 && <Space wrap>{m.photos.map((p) => <Image key={p} src={p} width={160} alt="메모 사진" />)}</Space>}
                </section>
              )) : <Empty>기간 안 메모가 없습니다.</Empty>}
            </>
          )}
          <Typography.Paragraph type="secondary" style={{ marginTop: 24 }}>출력 일시 {dayjs().format('YYYY-MM-DD HH:mm')}</Typography.Paragraph>
        </>
      )}
    </div>
  )
}
