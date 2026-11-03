import { Alert, Button, Checkbox, Form, Input, Modal, Space } from 'antd'
import { useEffect, useState } from 'react'

interface Props {
  open: boolean
  onClose: () => void
  title: string
  withLog?: { prefill: string }
  onSubmit: (password: string, log?: { changes: string; reason: string }) => Promise<void>
}

// 비밀번호를 다시 입력하는 승인 서명 창. 서버 오류는 창 안에 보인다.
export default function SignModal({ open, onClose, title, withLog, onSubmit }: Props) {
  const [useLog, setUseLog] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setUseLog(false)
      setErr('')
    }
  }, [open])

  const submit = async (v: { password: string; changes: string; reason: string }) => {
    setErr('')
    setBusy(true)
    try {
      await onSubmit(v.password, withLog && useLog ? { changes: v.changes, reason: v.reason } : undefined)
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '서명하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onCancel={onClose} title={title} footer={null} destroyOnHidden>
      <Form key={withLog?.prefill} initialValues={{ changes: withLog?.prefill ?? '' }} layout="vertical" onFinish={submit}>
        <Form.Item label="비밀번호" name="password" rules={[{ required: true, message: '비밀번호를 입력하세요.' }]}>
          <Input.Password autoComplete="current-password" autoFocus />
        </Form.Item>
        {withLog && (
          <>
            <Checkbox checked={useLog} onChange={(e) => setUseLog(e.target.checked)} style={{ marginBottom: 12 }}>
              승인하며 이력 남기기
            </Checkbox>
            {useLog && (
              <>
                <Form.Item label="변경 내용" name="changes">
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} />
                </Form.Item>
                <Form.Item label="사유" name="reason">
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
                </Form.Item>
              </>
            )}
          </>
        )}
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Space>
          <Button type="primary" htmlType="submit" loading={busy}>
            서명
          </Button>
          <Button onClick={onClose}>취소</Button>
        </Space>
      </Form>
    </Modal>
  )
}
