import { useQuery } from '@tanstack/react-query'
import { Alert, AutoComplete, Button, Form, Input, InputNumber, Select, Space } from 'antd'
import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import { useLotOptions } from '../components/lotOptions'

interface Saved {
  id: number
  number: string
  lot: string
  url: string
  trace: string
}
interface Values {
  lot: string
  origin: string
  description: string
  defect_qty: number
}

const Go = ({ url, children }: { url: string; children: React.ReactNode }) =>
  url.startsWith('/app/') ? <Link to={url.slice(4)}>{children}</Link> : <a href={url}>{children}</a>

// 현장 간편 등록: 필수 칸만 받고 나머지는 부적합 상세에서 보완한다. 저장하면 서버가 LOT과 하위 계보를 보류한다.
export default function NcNew() {
  const [params] = useSearchParams()
  const [form] = Form.useForm<Values>()
  const photos = useRef<HTMLInputElement>(null)
  const [lotText, setLotText] = useState(params.get('lot') ?? '')
  const lotOptions = useLotOptions(lotText)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState<Saved | null>(null)
  const meta = useQuery({ queryKey: ['nc-quick'], queryFn: () => api<{ origins: { value: string; label: string }[] }>('/api/core/nc-quick/') })

  const submit = async (v: Values) => {
    setErr('')
    setSaved(null)
    setSaving(true)
    const body = new FormData()
    body.append('lot', v.lot)
    body.append('origin', v.origin)
    body.append('description', v.description)
    body.append('defect_qty', String(v.defect_qty))
    for (const f of Array.from(photos.current?.files ?? [])) body.append('photos', f)
    try {
      setSaved(await api<Saved>('/api/core/nc-quick/', { method: 'POST', body }))
      form.resetFields(['lot', 'description'])
      setLotText('')
      if (photos.current) photos.current.value = ''
    } catch (e) {
      if (e instanceof ApiError) {
        const names = ['lot', 'origin', 'description', 'defect_qty'] as const
        form.setFields(names.filter((n) => e.fields[n]).map((n) => ({ name: n, errors: e.fields[n] })))
        setErr(e.fields.photos?.[0] ?? e.detail)
      } else setErr('등록하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 560 }}>
      <h1 className="page-title">부적합 등록</h1>
      {saved && (
        <Alert
          style={{ marginBottom: 16 }}
          type="success"
          message={`${saved.number} 등록됨 — LOT ${saved.lot} 보류`}
          description={
            <Space wrap>
              나머지 항목(부적합 유형·공정·긴급 조치 등)은 부적합 상세에서 보완하세요.
              <Go url={saved.url}>부적합 상세 열기</Go>
              <Go url={saved.trace}>LOT 이력 보기</Go>
            </Space>
          }
        />
      )}
      {meta.error && <Alert style={{ marginBottom: 12 }} type="error" message={meta.error instanceof ApiError ? meta.error.detail : '불러오지 못했습니다.'} />}
      <Form form={form} layout="vertical" initialValues={{ lot: lotText, origin: params.get('origin') || 'PROCESS', description: params.get('description') ?? undefined, defect_qty: 1 }} onFinish={submit} autoComplete="off">
        <Form.Item label="LOT 번호" name="lot" rules={[{ required: true, whitespace: true, message: 'LOT 번호를 입력하세요.' }]}>
          <AutoComplete options={lotOptions} onChange={setLotText} defaultActiveFirstOption={false}>
            <Input size="large" placeholder="스캔하거나 번호·품번 일부 입력" />
          </AutoComplete>
        </Form.Item>
        <Form.Item label="발생 유형" name="origin" rules={[{ required: true, message: '발생 유형을 고르세요.' }]}>
          <Select options={meta.data?.origins ?? []} loading={meta.isLoading} />
        </Form.Item>
        <Form.Item label="부적합 내용" name="description" rules={[{ required: true, whitespace: true, message: '부적합 내용을 입력하세요.' }]}>
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item label="부적합 수량" name="defect_qty" rules={[{ required: true, message: '부적합 수량을 입력하세요.' }]}>
          <InputNumber min={0} inputMode="decimal" style={{ width: 160 }} />
        </Form.Item>
        <Form.Item label="사진" extra="휴대폰에서는 카메라가 열립니다. 여러 장, 한 장 10MB까지.">
          <input ref={photos} aria-label="사진" type="file" accept="image/*" capture="environment" multiple />
        </Form.Item>
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} role="alert" />}
        <Button type="primary" htmlType="submit" size="large" loading={saving}>
          등록
        </Button>
      </Form>
    </div>
  )
}
