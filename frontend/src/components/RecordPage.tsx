import { useQuery } from '@tanstack/react-query'
import { Button, Dropdown, Tabs, Tag } from 'antd'
import type { MenuProps } from 'antd'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { fetchMe } from '../api/auth'

interface Props {
  title: string
  /** 정해진 상태는 색을 붙이고, 그 밖은 회색 */
  status?: string
  /** 주요 버튼 1개. 나머지 동작은 menu(「⋯」)로 보낸다. */
  actions: ReactNode
  props: { label: string; node: ReactNode }[]
  children: ReactNode
  side: { key: string; label: string; node: ReactNode }[]
  /** 기록 종류(app.model)와 번호. 있으면 「이력」 버튼과 「⋯」 맨 아래 삭제(요청)를 붙인다. */
  record?: { ct: string; id: number }
  /** 「⋯」 메뉴 항목(엑셀 받기·양식 등) */
  menu?: MenuProps['items']
  /** 제목 옆 큰 글자(검사 판정 띠) */
  lead?: ReactNode
}

const COLOR = { 초안: 'orange', 승인됨: 'green', 잠김: 'default', 합격: 'green', 불합격: 'red', 미판정: 'orange' } as const

export default function RecordPage({ title, status, actions, props, children, side, record, menu = [], lead }: Props) {
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: Infinity }).data
  const [app, model] = record?.ct.split('.') ?? []
  // 삭제는 서버 요청 화면(사유·비밀번호)으로만 간다. 시스템 관리자는 거기서 바로 삭제, 그 밖은 삭제 요청이다.
  const items: MenuProps['items'] = record
    ? [...menu, ...(menu.length ? [{ type: 'divider' as const }] : []), { key: 'delete', danger: true, label: <a href={`/request/DELETE/${app}/${model}/${record.id}/`}>{me?.is_superuser ? '삭제' : '삭제 요청'}</a> }]
    : menu
  return (
    <div className="record">
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
              <div key={p.label}>
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
