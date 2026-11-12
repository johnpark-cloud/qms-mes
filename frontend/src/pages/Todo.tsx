/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Grid, Select, Space, Spin, Typography, theme } from 'antd'
import dayjs from 'dayjs'
import { useState, type ReactNode } from 'react'
import { ApiError, api } from '../api/client'
import Tile, { RowList, type Row, type TileData } from '../components/Tile'

type Size = 'normal' | 'wide'
interface Layout {
  key: string
  size: Size
}
interface Widget extends Layout {
  title: string
  error: boolean
  // 숫자 타일이면 TileData, 전용 위젯이면 qms/widgets.py 의 *_data 가 주는 모양이다.
  data: any
}
interface Todo {
  widgets: Widget[]
  available: { key: string; title: string }[]
}

const md = (s: string) => dayjs(s).format('MM-DD HH:mm')

function Panel({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  const { token } = theme.useToken()
  return (
    <div style={{ background: token.colorBgContainer, border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadiusLG, padding: 16, height: '100%', boxSizing: 'border-box', minWidth: 0 }}>
      <Typography.Title level={5} style={{ marginTop: 0 }}>
        {title} {note && <Typography.Text type="secondary" style={{ fontWeight: 400, fontSize: 14 }}>{note}</Typography.Text>}
      </Typography.Title>
      {children}
    </div>
  )
}

// '처리할 일'의 종류별 목록.
const SECTIONS: { title: string; note: string; rows: (d: any) => Row[] }[] = [
  { title: '8D 기한 임박·초과', note: '2일 이내', rows: (d) => d.claims.map((c: any) => ({ label: c.label, href: c.href, meta: `${c.lot} · ${c.current_step} · ${c.due_label} ${md(c.due)} ${c.overdue ? '초과' : '임박'}`, tone: c.overdue ? 'negative' : 'critical' })) },
  { title: '열린 부적합', note: 'MRB 처분 대기', rows: (d) => d.open_ncs.map((n: any) => ({ label: n.label, href: n.href, meta: `${n.description.slice(0, 50)} · ${dayjs(n.detected_at).format('YYYY-MM-DD')}` })) },
  { title: 'CAPA', note: '지연·임박·유효성 확인 대기', rows: (d) => d.capas.map((c: any) => ({ label: c.label, href: c.href, meta: `${c.owner} · ${c.due_date} · ${c.status}`, tone: c.tone })) },
  { title: 'SCAR 회신 기한', note: '2일 이내·초과', rows: (d) => d.scars.map((s: any) => ({ label: s.label, href: s.href, meta: `${s.supplier} · ${s.response_due}${s.overdue ? ' 초과' : ''}`, tone: s.overdue ? 'negative' : null })) },
  { title: '부적합 보완 필요', note: '필수 항목 미입력', rows: (d) => d.nc_incomplete.map((n: any) => ({ label: n.label, href: n.href, meta: n.missing_fields.join(', ') })) },
  { title: '메일 발송 대기', note: '승인 후 미발송', rows: (d) => d.nc_mail_pending.map((n: any) => ({ label: n.label, href: n.href, meta: `${dayjs(n.approved_at).format('YYYY-MM-DD')} 승인` })) },
  { title: '고객 통보 미처리', note: '통보 필요', rows: (d) => d.nc_notify_pending.map((n: any) => ({ label: n.label, href: n.href, meta: '통보 전', tone: 'critical' })) },
  { title: '삭제·수정 요청 대기', note: '관리자 처리', rows: (d) => d.edit_requests.map((r: any) => ({ label: r.label, href: r.href, meta: `${r.requested_by} · ${md(r.requested_at)}` })) },
  { title: '거절된 내 요청', note: '최근 7일', rows: (d) => d.my_rejected.map((r: any) => ({ label: r.label, meta: r.reject_reason })) },
  { title: '미분류 메모', note: '', rows: (d) => (d.memos_unsorted ? [{ label: '미분류 메모 분류하기', href: '/app/memos', meta: `${d.memos_unsorted}건` }] : []) },
  { title: '4M 변경 초품 미확인', note: '출하 차단 중', rows: (d) => d.first_articles.map((c: any) => ({ label: c.label, href: c.href, meta: `적용 ${dayjs(c.effective_at).format('YYYY-MM-DD HH:mm')}`, tone: 'negative' })) },
  { title: '계측기 교정', note: '14일 이내·초과', rows: (d) => d.gauges.map((g: any) => ({ label: g.label, href: g.href, meta: `${g.next_due} ${g.overdue ? '초과' : '임박'}`, tone: g.overdue ? 'negative' : 'critical' })) },
  { title: '협력사 인증 만료', note: '30일 이내·만료', rows: (d) => (d.partner_certs ?? []).map((c: any) => ({ label: c.label, href: c.href, meta: `${c.valid_until} ${c.overdue ? '만료' : '임박'}`, tone: c.overdue ? 'negative' : 'critical' })) },
  { title: 'PPAP 제출 기한', note: '14일 이내', rows: (d) => d.ppaps.map((p: any) => ({ label: p.label, href: p.href, meta: p.overdue ? `${p.due_date} 초과` : p.due_date, tone: p.overdue ? 'negative' : null })) },
  { title: '승인 대기', note: '품질팀장 서명', rows: (d) => d.approvals.map((a: any) => ({ label: a.label, href: a.href, meta: a.kind })) },
]

const SHOWN = 5 // 목록 하나에 먼저 보이는 줄 수. 넘치면 '더 보기'로 편다(안쪽 스크롤 없음).

function ListCard({ title, note, rows }: { title: string; note: string; rows: Row[] }) {
  const [open, setOpen] = useState(false)
  const more = rows.length - SHOWN
  return (
    <Panel title={title} note={note}>
      <RowList rows={open ? rows : rows.slice(0, SHOWN)} />
      {more > 0 && <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setOpen(!open)}>{open ? '접기' : `${more}건 더 보기`}</Button>}
    </Panel>
  )
}

// '처리할 일': 종류마다 따로 선 카드다. 건수가 없는 종류는 보이지 않는다.
function TodoLists({ data }: { data: any }) {
  const lists = SECTIONS.map((s) => ({ s, rows: s.rows(data) })).filter(({ rows }) => rows.length)
  if (!lists.length) return <Typography.Text type="secondary">처리할 일이 없습니다.</Typography.Text>
  return (
    <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fill, minmax(min(320px, 100%), 1fr))', alignItems: 'start' }}>
      {lists.map(({ s, rows }) => <ListCard key={s.title} title={s.title} note={[s.title === '미분류 메모' ? '' : `${rows.length}건`, s.note].filter(Boolean).join(' · ')} rows={rows} />)}
    </div>
  )
}

// 전용 위젯 3종은 widget_data 의 키로 그린다('할 일 목록'은 타일 격자 밖 '처리할 일' 구역이다). 그 밖의 위젯은 숫자 타일(TileData)이다.
function Body({ w }: { w: Widget }) {
  const d = w.data
  if (w.error) return <Panel title={w.title}><Alert type="error" title="불러오지 못했습니다." showIcon /></Panel>
  const wide = w.size === 'wide'
  switch (w.key) {
    case 'spc_alarms': {
      const alarms: { label: string; href: string; lot: string; alarms: string[] }[] = d.spc_alarms
      const rows = (wide ? alarms : alarms.slice(0, 2)).map((a) => ({ label: a.label, href: a.href, meta: wide ? `${a.lot} · ${a.alarms.join(', ')}` : `${a.lot} · ${a.alarms[0]}`, tone: wide ? 'critical' : null }))
      return <Panel title="SPC 경보" note={`최근 7일${wide ? '' : ` · ${alarms.length}건`}`}><RowList rows={rows} empty="최근 경보가 없습니다." /></Panel>
    }
    case 'audits': {
      const audits: { label: string; href: string; planned_date: string }[] = d.audits
      const findings: { label: string; href: string }[] = d.findings
      const rows: Row[] = wide
        ? [...audits.map((a) => ({ label: a.label, href: a.href, meta: `${a.planned_date} 예정`, tone: 'info' })), ...findings.map((f) => ({ label: f.label, href: f.href, meta: 'CAPA 필요', tone: 'negative' }))]
        : [
            { label: audits[0]?.label ?? '다음 심사 없음', href: audits[0]?.href, meta: audits[0]?.planned_date.slice(5) },
            { label: 'CAPA 필요 지적', meta: `${findings.length}건`, tone: findings.length ? 'negative' : null },
          ]
      return <Panel title="내부심사" note={wide ? '14일 내 예정 · CAPA 미연결 지적' : '14일 내'}><RowList rows={rows} empty="예정된 심사가 없습니다." /></Panel>
    }
    case 'kpi_yield': {
      const pct = (v: number | null) => (v === null ? '-' : `${v.toFixed(1)}%`)
      const ys: { process: string; yield: number | null }[] = d.yields
      const rows: Row[] = wide
        ? ys.map((y) => ({ label: y.process, meta: pct(y.yield) }))
        : d.overall === null ? [] : [{ label: '전체', meta: pct(d.overall) }, { label: `최저 · ${d.lowest.process}`, meta: pct(d.lowest.yield) }]
      return (
        <Panel title="공정 수율" note="최근 6개월 · 양품 ÷ 투입">
          <RowList rows={rows} empty="작업 실적이 없습니다." />
          <a href={d.href}>품질 KPI 전체 보기</a>
        </Panel>
      )
    }
    default:
      return <Tile title={w.title} tile={d as TileData} details={wide} />
  }
}

export default function TodoPage() {
  const { token } = theme.useToken()
  const queryClient = useQueryClient()
  const desktop = Grid.useBreakpoint().md !== false // 폭 390px 같은 좁은 화면은 1칸 세로 배치
  const [editing, setEditing] = useState(false)
  const [dragging, setDragging] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['todo'], queryFn: () => api<Todo>('/api/qms/todo/') })
  const save = useMutation({
    mutationFn: (layout: Layout[]) => api('/api/qms/dashboard/', { method: 'POST', body: JSON.stringify(layout) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['todo'] }),
  })

  if (q.isPending) return <Spin />
  if (!q.data) return <Alert type="error" title={q.error?.message} showIcon />

  const { widgets, available } = q.data  // 다시 불러오기가 실패해도 받아 둔 데이터는 그대로 보인다
  // 배치는 목록 순서다. 자리(x·y)는 보내지 않아 서버가 순서대로 채운다.
  const current: Layout[] = widgets.map(({ key, size }) => ({ key, size }))
  const tiles = widgets.filter((w) => w.key !== 'todo_lists')
  const lists = widgets.find((w) => w.key === 'todo_lists')
  const options = available.filter((a) => !widgets.some((w) => w.key === a.key)).map((a) => ({ value: a.key, label: a.title }))
  const error = save.error instanceof ApiError ? save.error.detail : save.error ? '저장하지 못했습니다.' : ''
  const busy = save.isPending
  // key 를 to 자리로 옮긴다: 뒤에서 앞으로 오면 to 앞에, 앞에서 뒤로 가면 to 뒤에 놓인다.
  const move = (key: string, to: string) => {
    const from = current.findIndex((c) => c.key === key)
    const at = current.findIndex((c) => c.key === to)
    if (from < 0 || at < 0 || from === at) return
    const next = current.filter((c) => c.key !== key)
    next.splice(at, 0, current[from])
    save.mutate(next)
  }

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
        <Typography.Title level={3} style={{ margin: 0, flex: 1 }}>내 할 일</Typography.Title>
        {editing && (
          <>
            <Select
              aria-label="위젯 추가"
              placeholder="위젯 추가"
              style={{ width: 200 }}
              value={null}
              options={options}
              disabled={busy || !options.length}
              onChange={(key: string) => save.mutate([...current, { key, size: 'normal' }])}
            />
            <Button disabled={busy} onClick={() => save.mutate([])}>기본 배치로</Button>
          </>
        )}
        <Button type={editing ? 'primary' : 'default'} onClick={() => setEditing(!editing)}>{editing ? '편집 끝내기' : '화면 편집'}</Button>
        <Button href="/overview/">공장 종합현황</Button>
      </div>
      {editing && <Alert type="info" showIcon title="타일을 끌어서 순서를 바꿉니다. 바꾼 내용은 바로 저장됩니다." />}
      {q.isError && <Alert type="error" title={q.error.message} showIcon />}
      {error && <Alert type="error" title={error} showIcon />}
      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: `repeat(${desktop ? 4 : 1}, minmax(0, 1fr))`, gridAutoRows: 'minmax(120px, auto)', gridAutoFlow: 'dense', opacity: busy ? 0.6 : 1 }}>
        {tiles.map((w, i) => {
          const span = desktop && w.size === 'wide' ? 2 : 1
          return (
            <div key={w.key} data-widget={w.key} draggable={editing && !busy}
              onDragStart={(e) => { setDragging(w.key); e.dataTransfer.effectAllowed = 'move' }}
              onDragEnd={() => setDragging(null)}
              onDragOver={(e) => { if (dragging && dragging !== w.key) e.preventDefault() }}
              onDrop={(e) => { e.preventDefault(); if (dragging) move(dragging, w.key); setDragging(null) }}
              style={{ gridColumnEnd: `span ${span}`, gridRowEnd: `span ${span}`, display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, cursor: editing ? 'grab' : undefined, opacity: dragging === w.key ? 0.4 : 1, outline: editing ? `1px dashed ${token.colorBorder}` : undefined, outlineOffset: 4, borderRadius: token.borderRadiusLG }}>
              {editing && (
                <Space size={0} wrap style={{ justifyContent: 'flex-end', color: token.colorTextSecondary }}>
                  <Button size="small" type="text" disabled={busy || i === 0} aria-label={`${w.title} 앞으로`} onClick={() => move(w.key, tiles[i - 1].key)}>◀</Button>
                  <Button size="small" type="text" disabled={busy || i === tiles.length - 1} aria-label={`${w.title} 뒤로`} onClick={() => move(w.key, tiles[i + 1].key)}>▶</Button>
                  <Button size="small" type="text" disabled={busy} aria-label={`${w.title} 크기 바꾸기`}
                    onClick={() => save.mutate(current.map((c) => (c.key === w.key ? { ...c, size: w.size === 'wide' ? 'normal' : 'wide' } : c)))}>
                    {w.size === 'wide' ? '작게' : '크게'}
                  </Button>
                  {/* 마지막 하나를 빼면 빈 배열이 저장되어 기본 배치로 돌아가므로 막는다 */}
                  <Button size="small" type="text" danger disabled={busy || widgets.length === 1} aria-label={`${w.title} 빼기`}
                    onClick={() => save.mutate(current.filter((c) => c.key !== w.key))}>
                    빼기
                  </Button>
                </Space>
              )}
              {/* 편집 중에는 타일 안 링크가 눌리지 않게 한다 */}
              <div style={{ flex: 1, minWidth: 0, pointerEvents: editing ? 'none' : undefined }}><Body w={w} /></div>
            </div>
          )
        })}
      </div>
      {lists && (
        <section data-widget="todo_lists" style={{ display: 'grid', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Typography.Title level={4} style={{ margin: 0, flex: 1 }}>처리할 일</Typography.Title>
            {editing && <Button size="small" type="text" danger disabled={busy || widgets.length === 1} aria-label="할 일 목록 빼기" onClick={() => save.mutate(current.filter((c) => c.key !== 'todo_lists'))}>빼기</Button>}
          </div>
          {lists.error ? <Alert type="error" title="불러오지 못했습니다." showIcon /> : <TodoLists data={lists.data} />}
        </section>
      )}
    </div>
  )
}
