import { Alert, Button, Checkbox, Drawer, Input, InputNumber, Popconfirm, Space, Spin, Upload } from 'antd'
import { useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import EditGrid, { isBlank, newKey, withTail, type GridColumn, type GridRow } from '../components/EditGrid'

// personal/api.py PayslipView 응답
interface Detail { id: number; month: string; base_pay: string; lines: { kind: string; name: string; amount: string }[]; file_name: string | null; file_url: string | null }

const COLS: GridColumn[] = [
  { key: 'kind', label: '구분', kind: 'select', width: 110, options: [{ value: 'PLUS', label: '수당' }, { value: 'MINUS', label: '공제' }] },
  { key: 'name', label: '항목', kind: 'text' },
  { key: 'amount', label: '금액 (원)', kind: 'number', width: 160 },
]
// 붙여넣은 줄의 구분이 비어 있으면 이름으로 정한다(4대 보험·세금은 공제)
const DEDUCT = /국민연금|건강보험|장기요양|고용보험|소득세|주민세|공제|가불|상조|조합비/
const won = (n: number) => n.toLocaleString('ko-KR')
const num = (v: unknown) => Number(String(v ?? '').replace(/,/g, '')) || 0
const nextMonth = (ym: string) => {
  const [y, m] = ym.split('-').map(Number)
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`
}
const toRows = (d: Detail | null) => withTail((d?.lines ?? []).map((l) => ({ _key: newKey(), id: null, ...l })), COLS)

interface Props { target: number | 'new' | null; latestId: number | null; onClose: () => void; onSaved: () => void }

export default function PayslipDrawer({ target, latestId, onClose, onSaved }: Props) {
  const [month, setMonth] = useState('')
  const [base, setBase] = useState<number | null>(null)
  const [rows, setRows] = useState<GridRow[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [old, setOld] = useState<Detail | null>(null) // 수정 중인 명세
  const [copied, setCopied] = useState('') // 새 명세를 채운 지난 명세의 월
  const [clear, setClear] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

  const fill = (d: Detail | null, isNew: boolean) => {
    setOld(isNew ? null : d)
    setCopied(isNew && d ? d.month : '')
    setMonth(d ? (isNew ? nextMonth(d.month) : d.month) : new Date().toISOString().slice(0, 7))
    setBase(d ? Number(d.base_pay) : null)
    setRows(toRows(d))
    setFile(null)
    setClear(false)
    setErrors([])
  }

  useEffect(() => {
    if (target === null) return
    const id = target === 'new' ? latestId : target
    if (id === null) return fill(null, true)
    setLoading(true)
    api<Detail>(`/api/personal/payslip/${id}/`)
      .then((d) => fill(d, target === 'new'))
      .catch(() => fill(null, true))
      .finally(() => setLoading(false))
  }, [target, latestId])

  // 붙여넣기 뒤: 구분 빈 줄은 이름으로 정하고, '기본급' 줄은 기본급 칸으로 옮긴다
  const change = (next: GridRow[]) => {
    let b = base
    const out = next.flatMap((r) => {
      const name = String(r.name ?? '').trim()
      if (name === '기본급' && String(r.amount ?? '').trim()) {
        b = num(r.amount)
        return []
      }
      return [!r.kind && name ? { ...r, kind: DEDUCT.test(name) ? 'MINUS' : 'PLUS' } : r]
    })
    setBase(b)
    setRows(withTail(out, COLS))
  }

  const lines = rows.filter((r) => !r.delete && !isBlank(r, COLS))
  const plus = (base ?? 0) + lines.filter((r) => r.kind === 'PLUS').reduce((s, r) => s + num(r.amount), 0)
  const minus = lines.filter((r) => r.kind === 'MINUS').reduce((s, r) => s + num(r.amount), 0)

  const save = async () => {
    setBusy(true)
    setErrors([])
    const body = new FormData()
    body.append('month', month ? `${month}-01` : '')
    body.append('base_pay', base === null ? '' : String(base))
    body.append('lines', JSON.stringify(lines.map((r) => ({ kind: r.kind ?? '', name: r.name ?? '', amount: String(r.amount ?? '').replace(/,/g, '') }))))
    if (file) body.append('file', file)
    if (clear) body.append('file_clear', '1')
    try {
      await api(old ? `/api/personal/payslip/${old.id}/` : '/api/personal/payslip/', { method: 'POST', body })
      onSaved()
    } catch (e) {
      const msgs = e instanceof ApiError ? Object.values(e.fields).flat() : []
      setErrors(msgs.length ? msgs : [e instanceof ApiError ? e.detail : '저장하지 못했습니다.'])
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!old) return
    setBusy(true)
    try {
      await api(`/api/personal/payslip/${old.id}/`, { method: 'DELETE' })
      onSaved()
    } catch (e) {
      setErrors([e instanceof ApiError ? e.detail : '지우지 못했습니다.'])
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer open={target !== null} onClose={onClose} size="large" destroyOnHidden title={old ? `${old.month} 급여명세` : '급여명세 등록'}
      extra={
        <Space>
          {old && (
            <Popconfirm title="이 급여명세를 지울까요?" okText="지우기" cancelText="취소" onConfirm={remove}>
              <Button danger disabled={busy}>지우기</Button>
            </Popconfirm>
          )}
          <Button type="primary" loading={busy} onClick={save}>저장</Button>
        </Space>
      }>
      {loading ? <Spin /> : (
        <>
          {copied && (
            <Alert type="info" style={{ marginBottom: 12 }}
              message={`${copied} 명세의 항목을 복사했습니다. 바뀐 금액만 고치세요.`}
              action={<Button size="small" onClick={() => fill(null, true)}>빈 양식</Button>} />
          )}
          {errors.length > 0 && <Alert type="error" role="alert" style={{ marginBottom: 12 }} message={errors.join(' ')} />}
          <Space wrap style={{ marginBottom: 12 }}>
            <label>급여월 <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} style={{ width: 160 }} /></label>
            <label>기본급 <InputNumber<number> value={base} onChange={(v) => setBase(v)} min={0} style={{ width: 180 }}
              formatter={(v) => `${v ?? ''}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')} parser={(v) => num(v)} /></label>
          </Space>
          <p className="help">명세서·엑셀에서 「항목 ⇥ 금액」 줄들을 복사해 항목 칸에 붙여넣으면 한 번에 들어갑니다. 4대 보험·세금은 공제로, 「기본급」 줄은 기본급 칸으로 갑니다.</p>
          <EditGrid columns={COLS} rows={rows} onChange={change} readOnly={false} errors={{}} errorPrefix="lines" />
          <p style={{ marginTop: 12 }}>
            지급 합계 {won(plus)} · 공제 합계 {won(minus)} · <b>실수령 {won(plus - minus)}원</b>
          </p>
          <Space direction="vertical" style={{ marginTop: 8 }}>
            {old?.file_url && !file && (
              <Space>
                <a href={old.file_url}>{old.file_name}</a>
                <Checkbox checked={clear} onChange={(e) => setClear(e.target.checked)}>파일 지우기</Checkbox>
              </Space>
            )}
            <Upload maxCount={1} beforeUpload={(f) => { setFile(f); return false }} onRemove={() => setFile(null)}>
              <Button>{old?.file_url ? '명세서 파일 바꾸기' : '명세서 파일 첨부'}</Button>
            </Upload>
          </Space>
        </>
      )}
    </Drawer>
  )
}
