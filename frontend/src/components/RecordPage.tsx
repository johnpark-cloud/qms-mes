import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Dropdown, Tabs, Tag, message } from 'antd'
import type { MenuProps } from 'antd'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchMe } from '../api/auth'
import { api } from '../api/client'
import EditRequestModal from './EditRequestModal'

interface Props {
  title: string
  /** 정해진 상태는 색을 붙이고, 그 밖은 회색 */
  status?: string
  /** 주요 버튼 1개. 나머지 동작은 menu(「⋯」)로 보낸다. */
  actions: ReactNode
  /** wide: 한 줄 전체를 쓴다(담당자 표처럼 여러 칸 입력) */
  props: { label: string; node: ReactNode; wide?: boolean }[]
  children: ReactNode
  side: { key: string; label: string; node: ReactNode }[]
  /** 기록 종류(app.model)와 번호. 있으면 「이력」 버튼과 「⋯」 맨 아래 삭제(요청)를 붙인다. */
  record?: { ct: string; id: number }
  /** 있으면 삭제(요청)를 이 함수로 한다. 없으면 여기서 사유·비밀번호 창을 띄워 요청 API로 보낸다 */
  onDelete?: () => void
  /** 승인돼 잠긴 기록: 「⋯」에 수정 요청을 붙인다 */
  editRequest?: boolean
  /** 삭제한 뒤 갈 목록(라우터 주소) */
  listPath?: string
  /** 「⋯」 메뉴 항목(엑셀 받기·양식 등) */
  menu?: MenuProps['items']
  /** 제목 옆 큰 글자(검사 판정 띠) */
  lead?: ReactNode
}

const COLOR = { 초안: 'orange', 승인됨: 'green', 잠김: 'default', 합격: 'green', 불합격: 'red', 미판정: 'orange' } as const

export default function RecordPage({ title, status, actions, props, children, side, record, menu = [], lead, onDelete, editRequest, listPath = '/todo' }: Props) {
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: Infinity }).data
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [asking, setAsking] = useState<'EDIT' | 'DELETE' | null>(null)
  // 삭제·수정은 사유·비밀번호 창으로 요청한다(core.rules.submit_edit_request). 시스템 관리자는 바로 실행된다.
  const send = async (v: { reason: string; password: string }) => {
    const r = await api<{ status: string; deleted: boolean; decide_url: string | null }>(`/api/records/${record!.ct}/${record!.id}/request/`,
      { method: 'POST', body: JSON.stringify({ kind: asking, ...v }) })
    if (r.decide_url) return navigate(r.decide_url.slice(4)) // 막는 기록 안내는 요청 처리 화면에서
    if (r.deleted) {
      message.success(`${title} 삭제 완료`)
      return navigate(listPath)
    }
    message.success(r.status === 'APPROVED' ? '승인됐습니다. 이제 한 번 고칠 수 있습니다.'
      : asking === 'EDIT' ? '요청했습니다. 시스템 관리자가 승인하면 수정할 수 있습니다.' : '삭제를 요청했습니다. 시스템 관리자가 승인하면 삭제됩니다.')
    await qc.invalidateQueries()
  }
  const deleteLabel = me?.is_superuser ? '삭제' : '삭제 요청'
  const items: MenuProps['items'] = record
    ? [...menu, ...(editRequest ? [{ key: 'edit-request', label: '수정 요청', onClick: () => setAsking('EDIT') }] : []),
      ...(menu.length || editRequest ? [{ type: 'divider' as const }] : []),
      { key: 'delete', danger: true, label: deleteLabel, onClick: onDelete ?? (() => setAsking('DELETE')) }]
    : menu
  return (
    <div className="record">
      {record && !onDelete && (
        <EditRequestModal open={asking !== null} title={asking === 'EDIT' ? '수정 요청' : deleteLabel} onClose={() => setAsking(null)} onSubmit={send} />
      )}
      <div className="record-head">
        <h1 className="page-title">{title}</h1>
        {lead}
        {status && !lead && <Tag color={COLOR[status as keyof typeof COLOR] ?? 'default'}>{status}</Tag>}
        <div className="record-actions">
          {actions}
          {record && (
            <Link to={`/audit?model=${record.ct}&id=${record.id}`}>
              <Button>이력</Button>
            </Link>
          )}
          {items.length > 0 && (
            <Dropdown menu={{ items }} trigger={['click']}>
              <Button aria-label="더보기">⋯</Button>
            </Dropdown>
          )}
        </div>
      </div>
      <div className="record-body">
        <div className="record-main">
          <dl className="record-props">
            {props.map((p) => (
              <div key={p.label} className={p.wide ? 'wide' : undefined}>
                <dt>{p.label}</dt>
                <dd>{p.node}</dd>
              </div>
            ))}
          </dl>
          {children}
        </div>
        <aside className="record-side">
          <Tabs items={side.map((s) => ({ key: s.key, label: s.label, children: s.node }))} />
        </aside>
      </div>
    </div>
  )
}
