import { Space, Tabs, Tag } from 'antd'
import type { ReactNode } from 'react'

interface Props {
  title: string
  status?: '초안' | '승인됨' | '잠김' | '합격' | '불합격' | '미판정'
  actions: ReactNode
  props: { label: string; node: ReactNode }[]
  children: ReactNode
  side: { key: string; label: string; node: ReactNode }[]
}

const COLOR = { 초안: 'orange', 승인됨: 'green', 잠김: 'default', 합격: 'green', 불합격: 'red', 미판정: 'orange' } as const

export default function RecordPage({ title, status, actions, props, children, side }: Props) {
  return (
    <div style={{ paddingBottom: 72 }}>
      <h1 className="page-title">
        {title} {status && <Tag color={COLOR[status]}>{status}</Tag>}
      </h1>
      <Space wrap style={{ marginBottom: 16 }}>
        {actions}
      </Space>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '3 1 480px', minWidth: 0 }}>
          <dl className="prop-cards">
            {props.map((p) => (
              <div key={p.label}>
                <dt>{p.label}</dt>
                <dd>{p.node}</dd>
              </div>
            ))}
          </dl>
          {children}
        </div>
        <div style={{ flex: '1 1 260px', minWidth: 0 }}>
          <Tabs items={side.map((s) => ({ key: s.key, label: s.label, children: s.node }))} />
        </div>
      </div>
    </div>
  )
}
