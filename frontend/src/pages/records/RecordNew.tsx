import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Spin } from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import RecordPage from '../../components/RecordPage'
import { Editor } from './RecordView'
import type { Edit } from './RecordView'

// core/api/records.py RecordNewView 응답
interface NewForm { title: string; list_url: string; fields: Edit[] }

/** 새로 만들기(/app/r/<app>/<model>/new): 설명서 create 칸만 입력, 서버가 모델 규칙대로 저장한다 */
export default function RecordNew() {
  const { app, model } = useParams()
  const label = `${app}.${model}`
  const nav = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const q = useQuery({ queryKey: ['record-new', label], queryFn: () => api<NewForm>(`/api/records/${label}/new/`) })
  if (q.isLoading) return <Spin />
  if (q.error) return <Alert type="error" title={(q.error as Error).message} showIcon />
  const d = q.data!

  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    setErr('')
    try {
      const r = await api<{ id: number; url: string }>(`/api/records/${label}/`, { method: 'POST', body: JSON.stringify({ values }) })
      queryClient.invalidateQueries({ queryKey: ['record-list-head', label] })
      nav(`/r/${app}/${model}/${r.id}`, { replace: true })
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fields).length) {
        form.setFields(Object.entries(e.fields).filter(([k]) => k !== '__all__').map(([name, errors]) => ({ name, errors })))
        setErr(e.fields.__all__?.join(' ') ?? '')
      } else setErr(e instanceof Error ? e.message : '저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Form form={form} initialValues={Object.fromEntries(d.fields.map((e) => [e.key, e.value]))}>
      {err && <Alert type="error" title={err} showIcon style={{ marginBottom: 16 }} />}
      <RecordPage
        title={`새 ${d.title}`}
        actions={
          <>
            <Button onClick={() => nav(d.list_url.slice(4))}>취소</Button>
            <Button type="primary" loading={saving} onClick={save}>저장</Button>
          </>
        }
        props={d.fields.map((e) => ({
          label: e.label,
          node: (
            <Form.Item name={e.key} valuePropName={e.type === 'bool' ? 'checked' : 'value'} style={{ margin: 0 }}
              rules={e.required && e.type !== 'bool' ? [{ required: true, message: `${e.label}을(를) 입력하세요.` }] : []}>
              <Editor e={e} />
            </Form.Item>
          ),
        }))}
        side={[]}
      >
        {null}
      </RecordPage>
    </Form>
  )
}
