import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input } from 'antd'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { login } from '../api/auth'
import { ApiError } from '../api/client'

export default function Login() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // next 는 앱 안 경로(/app/...)만 받는다. 다른 곳으로 보내는 주소는 무시한다.
  const next = params.get('next') ?? ''
  const target = next.startsWith('/app/') && !next.startsWith('/app//') ? next.slice(4) : '/todo'

  async function submit(v: { username: string; password: string }) {
    setBusy(true)
    setError('')
    try {
      queryClient.setQueryData(['me'], await login(v.username, v.password))
      navigate(target, { replace: true })
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : '로그인하지 못했습니다.')
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', boxSizing: 'border-box', padding: 16 }}>
      <Card title="QMS+MES 로그인" style={{ width: '100%', maxWidth: 360 }}>
        {error && <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={submit}>
          <Form.Item label="아이디" name="username" rules={[{ required: true, message: '아이디를 입력하세요.' }]}>
            <Input autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item label="비밀번호" name="password" rules={[{ required: true, message: '비밀번호를 입력하세요.' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy} block>
            로그인
          </Button>
        </Form>
      </Card>
    </div>
  )
}
