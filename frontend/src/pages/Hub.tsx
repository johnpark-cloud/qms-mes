import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Modal, Space, Spin, Table, Tag } from 'antd'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { fetchMe } from '../api/auth'
import { api } from '../api/client'
import type { ListPage, Row } from './records/RecordList'
import { createRecord, type NewForm } from './records/RecordNew'
import { Editor } from './records/RecordView'

const SHOW = 5 // 위젯에 보이는 줄 수. 나머지는 「전체 보기」

/** 메뉴 묶음 한눈에 보기(/app/hub/<묶음 이름>): 묶음 안 기록 목록을 위젯처럼 몇 줄씩, 바로 추가. 기록 목록이 아닌 메뉴는 위 단추로 */
export default function Hub() {
  const { group = '' } = useParams()
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: Infinity }).data
  const g = me?.nav.find((x) => x.group === group)
  if (!me) return <Spin />
  if (!g) return <Alert type="info" showIcon title="볼 수 있는 메뉴가 없습니다." />
  const lists = g.items.filter((i) => i.href.startsWith('/app/r/'))
  const others = g.items.filter((i) => !i.href.startsWith('/app/r/'))
  return (
    <div>
      <h1 className="page-title">{g.group}</h1>
      {others.length > 0 && (
        <Space wrap style={{ marginBottom: 16 }}>
          {others.map((i) => (i.href.startsWith('/app/') ? <Link key={i.href} to={i.href.slice(4)}><Button>{i.label}</Button></Link>
            : <Button key={i.href} href={i.href}>{i.label}</Button>))}
        </Space>
      )}
      <div className="hub-grid">
        {lists.map((i) => <Widget key={i.href} label={i.label} href={i.href} />)}
      </div>
    </div>
  )
}

function Widget({ label, href }: { label: string; href: string }) {
  const [path, query = ''] = href.slice(4).split('?')
  const ct = path.split('/').slice(2, 4).join('.')
  const nav = useNavigate()
  const [adding, setAdding] = useState(false)
  const q = useQuery({ queryKey: ['hub', href], queryFn: () => api<ListPage>(`/api/records/${ct}/${query ? '?' + query : ''}`) })
  const d = q.data
  const late = d?.overdue?.count ? d.overdue : null // 관리자가 먼저 볼 것: 기한 지난 건수를 제목 앞에 빨갛게, 누르면 지연 탭
  return (
    <Card size="small" title={<Space size={6}>
      {late && <Link to={`${path}?tab=${late.tab}`}><Tag color="red" style={{ margin: 0 }}>지연 {late.count}</Tag></Link>}
      <span>{`${label}${d ? ` (${d.count})` : ''}`}</span>
    </Space>}
      extra={<Space>
        {d?.can_add && d.new_url?.startsWith('/app/r/') && <Button size="small" type="primary" onClick={() => setAdding(true)}>추가</Button>}
        {d?.can_add && d.new_url && !d.new_url.startsWith('/app/r/') && (d.new_url.startsWith('/app/')
          ? <Link to={d.new_url.slice(4)}><Button size="small" type="primary">추가</Button></Link>
          : <Button size="small" href={d.new_url}>추가</Button>)}
        <Link to={path + (query ? '?' + query : '')}>전체 보기</Link>
      </Space>}>
      {q.error ? <Alert type="error" title={(q.error as Error).message} /> : (
        <Table<Row> size="small" pagination={false} rowKey="id" loading={q.isLoading}
          dataSource={d?.results.slice(0, SHOW)}
          columns={(d?.columns ?? []).slice(0, 3).map((c) => ({ title: c.label, key: c.key, ellipsis: true, render: (_: unknown, r: Row) => r.cells[c.key] }))}
          onRow={(r) => ({ onClick: () => nav(`${path}/${r.id}`), style: { cursor: 'pointer' } })}
          locale={{ emptyText: '없음' }} />
      )}
      {adding && <QuickNew ct={ct} onClose={() => setAdding(false)} />}
    </Card>
  )
}

/** 「추가」 창: 새 기록 화면과 같은 칸·저장(서버 모델 규칙). 저장하면 위젯 목록을 다시 불러온다 */
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
