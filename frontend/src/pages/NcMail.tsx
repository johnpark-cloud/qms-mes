import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Input, Space, Spin, message } from 'antd'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'

// core/api/screens.py NcMailView
interface Mail {
  number: string; subject: string; body: string; smtp: boolean; can_send: boolean; can_mark: boolean
  mailed_at: string | null; photos: string[]; photos_zip: string; nc_url: string
}

/** 승인된 부적합 보고 메일: 본문을 복사해 웹메일에 붙여넣고 「보냈음 표시」, 메일 서버가 있으면 바로 보내기. */
export default function NcMail() {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const url = `/api/core/nc-mail/${id}/`
  const q = useQuery({ queryKey: ['nc-mail', id], queryFn: () => api<Mail>(url) })
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (q.isLoading) return <Spin />
  const d = q.data
  if (!d) return <Alert type="error" showIcon title={q.error instanceof ApiError ? q.error.detail : '승인된 부적합만 메일을 보낼 수 있습니다.'} />

  const run = async (action: 'send' | 'mark_sent') => {
    setBusy(true)
    setErr('')
    try {
      await api(url, { method: 'POST', body: JSON.stringify({ action, to }) })
      message.success(action === 'send' ? '보냈습니다.' : '보냈음으로 표시했습니다.')
      await qc.invalidateQueries()
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '처리하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }
  const copy = async () => {
    try {  // 웹메일에 표 모양 그대로 붙도록 HTML과 글자를 함께 넣는다
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([d.body], { type: 'text/html' }),
        'text/plain': new Blob([document.getElementById('mail-body')?.innerText ?? d.subject], { type: 'text/plain' }),
      })])
      message.success('본문을 복사했습니다. 메일에 붙여넣고 보낸 뒤 「보냈음 표시」를 누르세요.')
    } catch {
      message.error('복사하지 못했습니다. 본문을 직접 선택해 복사하세요.')
    }
  }
  return (
    <div style={{ maxWidth: 960 }}>
      <h1 className="page-title">{d.number} 메일 보내기</h1>
      <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="부적합"><Link to={d.nc_url.slice(4)}>{d.number}</Link></Descriptions.Item>
        <Descriptions.Item label="제목">{d.subject}</Descriptions.Item>
        <Descriptions.Item label="마지막 발송 표시">{d.mailed_at ? d.mailed_at.slice(0, 16).replace('T', ' ') : '아직 없음'}</Descriptions.Item>
        <Descriptions.Item label={`사진 (${d.photos.length}장)`}>{d.photos.join(', ') || '등록된 사진이 없습니다.'}</Descriptions.Item>
      </Descriptions>
      {/* 서버 템플릿(core/_nc_mail_body.html)이 값을 이스케이프한 HTML */}
      <div id="mail-body" className="mail-body" style={{ marginBottom: 16, overflowX: 'auto' }} dangerouslySetInnerHTML={{ __html: d.body }} />
      {err && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={err} />}
      <Space wrap style={{ marginBottom: 12 }}>
        <Button type="primary" onClick={copy}>본문 복사</Button>
        {d.photos.length > 0 && <Button href={d.photos_zip}>사진 ZIP</Button>}
        {d.can_mark && <Button loading={busy} onClick={() => run('mark_sent')}>보냈음 표시</Button>}
      </Space>
      {d.can_send && (
        <Space.Compact style={{ display: 'flex', maxWidth: 640 }}>
          <Input aria-label="수신자" placeholder="수신자 메일 (쉼표로 구분)" value={to} onChange={(e) => setTo(e.target.value)} />
          <Button type="primary" loading={busy} disabled={!to.trim()} onClick={() => run('send')}>바로 보내기</Button>
        </Space.Compact>
      )}
    </div>
  )
}
