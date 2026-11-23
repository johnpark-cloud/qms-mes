import { Alert, Button, Form, Input, Modal } from 'antd'
import { useEffect, useState } from 'react'

// 수정·삭제 요청: 사유와 본인 비밀번호 (core.rules.submit_edit_request). 시스템 관리자는 요청과 동시에 실행된다.
export default function EditRequestModal({ open, title, onClose, onSubmit }: {
  open: boolean; title: string; onClose: () => void; onSubmit: (v: { reason: string; password: string }) => Promise<void>
}) {
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => setErr(''), [open])
  const submit = async (v: { reason: string; password: string }) => {
    setBusy(true)
    try {
      await onSubmit(v)
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '요청하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onCancel={onClose} title={title} footer={null} destroyOnHidden>
      <Form layout="vertical" onFinish={submit}>
        <Form.Item label="사유" name="reason" rules={[{ required: true, whitespace: true, message: '사유를 입력하세요.' }]}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} autoFocus />
        </Form.Item>
        <Form.Item label="비밀번호" name="password" rules={[{ required: true, message: '비밀번호를 입력하세요.' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Button type="primary" htmlType="submit" loading={busy} danger={title.startsWith('삭제')}>{title.startsWith('삭제') && !title.endsWith('요청') ? '삭제' : '요청'}</Button>
      </Form>
    </Modal>
  )
}
