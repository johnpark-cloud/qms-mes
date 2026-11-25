import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Modal, Space, Spin } from 'antd'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { createRecord, type NewForm } from './records/RecordNew'
import { Due, Editor } from './records/RecordView'

interface Tab { key: string; label: string; count: number }
interface Mod {
  label: string; href: string; ct: string; count: number; tabs: Tab[]
  overdue: { tab: string; count: number } | null; soon: number; can_add: boolean; new_url: string | null
}
interface Att { module: string; title: string; url: string; days: number | null }
interface HubData { group: string; modules: Mod[]; others: { label: string; href: string }[]; attention: Att[] }

const to = (href: string) => href.slice(4) // /app/… → 라우터 주소
const withTab = (href: string, tab: string) => `${to(href)}${href.includes('?') ? '&' : '?'}tab=${tab}`

/** 메뉴 묶음 한눈에 보기(/app/hub/<묶음 이름>): 처리할 것(지연·7일 안 기한·승인 전) → 상태 보드(모듈 × 탭 건수) + 주의 필요 목록(P3) */
export default function Hub() {
  const { group = '' } = useParams()
  const q = useQuery({ queryKey: ['hub', group], queryFn: () => api<HubData>(`/api/hub/?group=${encodeURIComponent(group)}`) })
  const [adding, setAdding] = useState<string | null>(null)
  if (q.isLoading) return <Spin />
  if (q.error || !q.data) return <Alert type="info" showIcon title="볼 수 있는 메뉴가 없습니다." />
  const d = q.data
  const sum = (pick: (m: Mod) => number) => d.modules.map((m) => ({ m, n: pick(m) })).filter((x) => x.n > 0)
  const late = sum((m) => m.overdue?.count ?? 0)
  const soon = sum((m) => m.soon)
  const draft = sum((m) => m.tabs.find((t) => t.key === 'draft')?.count ?? 0)
  return (
    <div>
      <h1 className="page-title">{d.group}</h1>
      {d.others.length > 0 && (
        <Space wrap style={{ marginBottom: 16 }}>
          {d.others.map((i) => (i.href.startsWith('/app/') ? <Link key={i.href} to={to(i.href)}><Button>{i.label}</Button></Link>
            : <Button key={i.href} href={i.href}>{i.label}</Button>))}
        </Space>
      )}
      <section className="hub-todo" aria-label="처리할 것">
        <Tile label="지연" tone="late" parts={late.map(({ m, n }) => ({ m, n, href: withTab(m.href, m.overdue!.tab) }))} />
        <Tile label="7일 안 기한" tone="soon" parts={soon.map(({ m, n }) => ({ m, n, href: to(m.href) }))} />
        <Tile label="승인 전" parts={draft.map(({ m, n }) => ({ m, n, href: withTab(m.href, 'draft') }))} />
      </section>
      <div className="hub-body">
        <section className="record-card hub-board">
          <h2>상태 보드</h2>
          {d.modules.map((m) => (
            <div key={m.href} className="hub-row">
              <Link className="hub-name" to={to(m.href)}>{m.label}</Link>
              <span className="hub-tabs">
                {m.tabs.map((t) => (
                  <Link key={t.key} to={withTab(m.href, t.key)}
                    className={t.key === m.overdue?.tab && t.count ? 'hub-chip hub-chip-late' : t.count ? 'hub-chip' : 'hub-chip hub-chip-zero'}>
                    {t.label} <b>{t.count}</b>
                  </Link>
                ))}
              </span>
              {m.can_add && m.new_url && <AddButton url={m.new_url} onQuick={() => setAdding(m.ct)} />}
            </div>
          ))}
        </section>
        <section className="record-card hub-attention">
          <h2>주의 필요</h2>
          {d.attention.length ? (
            <ul>
              {d.attention.map((a) => (
                <li key={a.url}>
                  <Link to={to(a.url)}>{a.title}</Link>
                  {a.days !== null && <Due days={a.days} />}
                  <div className="flow-sub">{a.module}</div>
                </li>
              ))}
            </ul>
          ) : <p className="flow-sub">기한 지났거나 7일 안에 오는 건이 없습니다.</p>}
        </section>
      </div>
      {adding && <QuickNew ct={adding} onClose={() => setAdding(null)} />}
    </div>
  )
}

/** 「처리할 것」 칸: 큰 숫자 + 모듈별 건수(누르면 그 목록 탭) */
function Tile({ label, tone, parts }: { label: string; tone?: 'late' | 'soon'; parts: { m: Mod; n: number; href: string }[] }) {
  const total = parts.reduce((s, p) => s + p.n, 0)
  return (
    <div className={`hub-tile${total && tone ? ` hub-tile-${tone}` : ''}`}>
      <div className="hub-tile-label">{label}</div>
      <div className="hub-tile-num">{total}</div>
      <div className="hub-tile-parts">
        {parts.map((p) => <Link key={p.m.href} to={p.href}>{p.m.label} {p.n}</Link>)}
      </div>
    </div>
  )
}

function AddButton({ url, onQuick }: { url: string; onQuick: () => void }): ReactNode {
  if (url.startsWith('/app/r/')) return <Button size="small" onClick={onQuick}>추가</Button>
  return url.startsWith('/app/') ? <Link to={to(url)}><Button size="small">추가</Button></Link> : <Button size="small" href={url}>추가</Button>
}

/** 「추가」 창: 새 기록 화면과 같은 칸·저장(서버 모델 규칙). 저장하면 허브를 다시 불러온다 */
function QuickNew({ ct, onClose }: { ct: string; onClose: () => void }) {
  const [form] = Form.useForm()
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const q = useQuery({ queryKey: ['record-new', ct, ''], queryFn: () => api<NewForm>(`/api/records/${ct}/new/`) })
  const shown = q.data?.fields.filter((e) => !e.hidden) ?? []
  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    setErr('')
    const id = await createRecord(ct, values, form, setErr)
    setSaving(false)
    if (id == null) return
    qc.invalidateQueries({ queryKey: ['hub'] })
    qc.invalidateQueries({ queryKey: ['record-list-head', ct] })
    onClose()
  }
  return (
    <Modal open title={q.data ? `새 ${q.data.title}` : '추가'} onCancel={onClose} onOk={save} okText="저장" cancelText="취소"
      confirmLoading={saving} destroyOnHidden>
      {q.isLoading ? <Spin /> : (
        <Form form={form} layout="vertical" initialValues={Object.fromEntries(shown.map((e) => [e.key, e.value]))}>
          {err && <Alert type="error" title={err} showIcon style={{ marginBottom: 12 }} />}
          {shown.map((e) => (
            <Form.Item key={e.key} name={e.key} label={e.label} valuePropName={e.type === 'bool' ? 'checked' : 'value'}
              rules={e.required && e.type !== 'bool' ? [{ required: true, message: `${e.label}을(를) 입력하세요.` }] : []}>
              <Editor e={e} />
            </Form.Item>
          ))}
        </Form>
      )}
    </Modal>
  )
}
