import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Switch, Table, Typography, message } from 'antd'
import { useState } from 'react'
import { ApiError, api } from '../api/client'

// core/api/screens.py ModuleSettingsView
interface Row { key: string; name: string; enabled: boolean; requires: string[]; changed_by: string; changed_at: string | null }

/** 모듈 설정(시스템 관리자): 켜고 끄면 그 메뉴·화면·API가 닫힌다. 먼저 켤 모듈·열린 기록 규칙은 서버가 검사한다. */
export default function Modules() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['modules'], queryFn: () => api<{ rows: Row[] }>('/api/core/modules/') })
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const toggle = async (r: Row, enabled: boolean) => {
    setBusy(r.key)
    setErr('')
    try {
      await api('/api/core/modules/', { method: 'POST', body: JSON.stringify({ key: r.key, enabled }) })
      message.success(`${r.name} ${enabled ? '켰습니다' : '껐습니다'}.`)
      await qc.invalidateQueries()
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '바꾸지 못했습니다.')
    } finally {
      setBusy('')
    }
  }
  return (
    <div style={{ maxWidth: 960 }}>
      <h1 className="page-title">모듈 설정</h1>
      <Typography.Paragraph type="secondary">
        끈 모듈은 메뉴·화면이 닫힙니다. 기록은 지워지지 않고, 인터록 같은 업무 규칙은 그대로 동작합니다. 홈·LOT·부적합·기준정보는 끌 수 없습니다.
      </Typography.Paragraph>
      {(q.error || err) && <Alert type="error" showIcon style={{ marginBottom: 16 }} title={err || (q.error instanceof ApiError ? q.error.detail : '불러오지 못했습니다.')} />}
      <Table rowKey="key" size="small" pagination={false} loading={q.isLoading} dataSource={q.data?.rows} columns={[
        { title: '모듈', dataIndex: 'name' },
        { title: '켜짐', dataIndex: 'enabled', width: 80,
          render: (v: boolean, r) => <Switch aria-label={`${r.name} 켜짐`} checked={v} loading={busy === r.key} onChange={(on) => toggle(r, on)} /> },
        { title: '먼저 켜야 하는 모듈', dataIndex: 'requires', render: (v: string[]) => v.join(', ') || '—' },
        { title: '마지막 변경', key: 'changed', render: (_, r) => (r.changed_at ? `${r.changed_by} · ${r.changed_at.slice(0, 16).replace('T', ' ')}` : '—') },
      ]} />
    </div>
  )
}
