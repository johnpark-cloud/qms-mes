import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Result, Spin } from 'antd'
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
    // 파일 칸(UploadFile)이 있으면 multipart: values는 JSON 글, 파일은 칸 이름으로 (core/api/records.py)
    const files = Object.entries(values).filter(([, v]) => v && typeof v === 'object' && 'originFileObj' in v)
    let body: BodyInit = JSON.stringify({ values })
    if (files.length) {
      const fd = new FormData()
      fd.append('values', JSON.stringify(Object.fromEntries(Object.entries(values).filter(([k]) => !files.some(([f]) => f === k)))))
      for (const [k, v] of files) fd.append(k, v.originFileObj)
      body = fd
    }
    const r = await api<{ id: number }>(`/api/records/${label}/`, { method: 'POST', body })
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
  if (q.error) {
    // 새로 만들기가 없는 종류(부적합·보류·PPAP 요소): 서버가 어디서 생기는지와 갈 곳을 준다
    const b = q.error instanceof ApiError ? (q.error.body as { list_url?: string; new_url?: string | null }) : {}
    return (
      <Result status="info" title="여기서는 새로 만들 수 없습니다" subTitle={(q.error as Error).message}
        extra={[
          b.new_url && <Button key="new" type="primary" onClick={() => nav(b.new_url!.slice(4))}>부적합 등록으로</Button>,
          b.list_url && <Button key="list" onClick={() => nav(b.list_url!.slice(4))}>목록으로</Button>,
        ]} />
    )
  }
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
          (e) => ['rows', 'text', 'json'].includes(e.type))}
        side={[]}
      >
        {null}
      </RecordPage>
    </Form>
  )
}
