import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Spin } from 'antd'
import { useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import RecordPage from '../../components/RecordPage'
import { CheckGroup, Editor, groupProps } from './RecordView'
import type { Edit, Group } from './RecordView'
import type { FormInstance } from 'antd'

/** 저장 POST. 칸별 오류는 폼에, 나머지는 onErr로. 성공하면 새 번호, 실패하면 null */
export async function createRecord(label: string, values: object, form: FormInstance, onErr: (m: string) => void) {
  try {
    const r = await api<{ id: number }>(`/api/records/${label}/`, { method: 'POST', body: JSON.stringify({ values }) })
    return r.id
  } catch (e) {
    if (e instanceof ApiError && Object.keys(e.fields).length) {
      form.setFields(Object.entries(e.fields).filter(([k]) => k !== '__all__').map(([name, errors]) => ({ name, errors })))
      onErr(e.fields.__all__?.join(' ') ?? '')
    } else onErr(e instanceof Error ? e.message : '저장하지 못했습니다.')
    return null
  }
}

// core/api/records.py RecordNewView 응답
export interface NewForm { title: string; list_url: string; fields: Edit[]; groups: Group[] }

/** 새로 만들기(/app/r/<app>/<model>/new): 설명서 create 칸만 입력, 서버가 모델 규칙대로 저장한다 */
export default function RecordNew() {
  const { app, model } = useParams()
  const label = `${app}.${model}`
  const nav = useNavigate()
  const { search } = useLocation() // ?칸=값 → 서버가 처음 값으로 채운다(CAPA 만들기 등)
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const q = useQuery({ queryKey: ['record-new', label, search], queryFn: () => api<NewForm>(`/api/records/${label}/new/${search}`) })
  if (q.isLoading) return <Spin />
  if (q.error) return <Alert type="error" title={(q.error as Error).message} showIcon />
  const d = q.data!
  const shown = d.fields.filter((e) => !e.hidden)
  const hidden = Object.fromEntries(d.fields.filter((e) => e.hidden && e.value != null).map((e) => [e.key, e.value]))

  const save = async () => {
    const values = { ...hidden, ...(await form.validateFields()) }
    setSaving(true)
    setErr('')
    const id = await createRecord(label, values, form, setErr)
    setSaving(false)
    if (id == null) return
    queryClient.invalidateQueries({ queryKey: ['record-list-head', label] })
    nav(`/r/${app}/${model}/${id}`, { replace: true })
  }

  return (
    <Form form={form} initialValues={Object.fromEntries(shown.map((e) => [e.key, e.value]))}>
      {err && <Alert type="error" title={err} showIcon style={{ marginBottom: 16 }} />}
      <RecordPage
        title={`새 ${d.title}`}
        actions={
          <>
            <Button onClick={() => nav(d.list_url.slice(4))}>취소</Button>
            <Button type="primary" loading={saving} onClick={save}>저장</Button>
          </>
        }
        props={groupProps(shown, d.groups ?? [],
          (e) => (
            <Form.Item name={e.key} valuePropName={e.type === 'bool' ? 'checked' : 'value'} style={{ margin: 0 }}
              rules={e.required && e.type !== 'bool' ? [{ required: true, message: `${e.label}을(를) 입력하세요.` }] : []}>
              <Editor e={e} />
            </Form.Item>
          ),
          (es) => <CheckGroup edits={es} />,
          (e) => e.type === 'rows')}
        side={[]}
      >
        {null}
      </RecordPage>
    </Form>
  )
}
