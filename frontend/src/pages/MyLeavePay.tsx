import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, Popconfirm, Select, Space, Spin, Table } from 'antd'
import { useState } from 'react'
import { ApiError, api } from '../api/client'

// personal/api.py MeView 응답. 언제나 본인 것만 온다
interface Use { id: number; used_on: string; days: string; reason: string }
interface Slip { id: number; month: string; gross: string; deduction: string; net: string; file_url: string | null; edit_url: string }
interface Me {
  year: number
  hired_on: string | null
  leave: { accrued: number; used: string; remaining: string; period_start: string; period_end: string } | null
  uses: Use[]
  days_choices: { value: string; label: string }[]
  slips: Slip[]
  total: { gross: string; deduction: string; net: string } | null
  payslip_add_url: string
}

const won = (v: string) => Number(v).toLocaleString('ko-KR')
const KEY = ['personal-me']

export default function MyLeavePay() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: KEY, queryFn: () => api<Me>('/api/personal/me/') })
  const [useForm] = Form.useForm()
  const [hireForm] = Form.useForm()
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  // 저장 오류는 칸 아래에, 그 밖의 오류는 위 알림에 둔다
  const send = async (form: ReturnType<typeof Form.useForm>[0] | null, path: string, method: string, body?: object) => {
    setBusy(true)
    setErr('')
    try {
      await api(path, { method, body: body && JSON.stringify(body) })
      form?.resetFields()
      await qc.invalidateQueries({ queryKey: KEY })
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fields).length && form)
        form.setFields(Object.entries(e.fields).map(([name, errors]) => ({ name, errors })))
      else setErr(e instanceof ApiError ? e.detail : '저장하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  if (me.isError) return <Alert type="error" message={me.error instanceof ApiError ? me.error.detail : '불러오지 못했습니다.'} />
  if (!me.data) return <Spin />
  const d = me.data
  return (
    <div>
      <h1 className="page-title">연차·급여</h1>
      {err && <Alert type="error" message={err} role="alert" style={{ marginBottom: 12 }} />}
      <Card title="연차" style={{ marginBottom: 16 }}>
        {d.leave ? (
          <p>
            {d.leave.period_start} ~ {d.leave.period_end}: 발생 {d.leave.accrued}일 · 사용 {d.leave.used}일 · <b>잔여 {d.leave.remaining}일</b>
          </p>
        ) : (
          <Alert type="info" style={{ marginBottom: 12 }} message="입사일을 먼저 설정하세요." />
        )}
        <Form form={hireForm} layout="inline" style={{ marginBottom: 12 }} key={d.hired_on ?? ''} initialValues={{ hired_on: d.hired_on ?? '' }}
          onFinish={(v) => send(hireForm, '/api/personal/me/', 'PUT', v)}>
          <Form.Item name="hired_on" label="입사일"><Input type="date" /></Form.Item>
          <Button htmlType="submit" loading={busy}>입사일 저장</Button>
        </Form>
        <Form form={useForm} layout="inline" style={{ marginBottom: 12 }} initialValues={{ days: d.days_choices[0]?.value, reason: '' }}
          onFinish={(v) => send(useForm, '/api/personal/me/', 'POST', v)}>
          <Form.Item name="used_on" label="사용일"><Input type="date" /></Form.Item>
          <Form.Item name="days" label="일수"><Select style={{ width: 150 }} options={d.days_choices} /></Form.Item>
          <Form.Item name="reason" label="사유"><Input style={{ width: 200 }} maxLength={100} /></Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>연차 사용 등록</Button>
        </Form>
        <Table<Use>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={d.uses}
          locale={{ emptyText: '사용 내역이 없습니다.' }}
          columns={[
            { title: d.leave ? '사용일' : `${d.year}년 사용일`, dataIndex: 'used_on' },
            { title: '일수', dataIndex: 'days', align: 'right' },
            { title: '사유', dataIndex: 'reason' },
            {
              title: '',
              render: (_, u) => (
                <Popconfirm title="이 연차 사용을 지울까요?" okText="지우기" cancelText="취소"
                  onConfirm={() => send(null, `/api/personal/leave/${u.id}/`, 'DELETE')}>
                  <Button size="small" danger>지우기</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>
      <Card title={`${d.year}년 급여`} extra={<a href={d.payslip_add_url}>급여명세 등록</a>}>
        <Table<Slip>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={d.slips}
          locale={{ emptyText: '등록된 급여명세가 없습니다.' }}
          columns={[
            { title: '월', dataIndex: 'month', render: (v: string, s) => <a href={s.edit_url}>{v}</a> },
            { title: '지급 합계', dataIndex: 'gross', align: 'right', render: won },
            { title: '공제 합계', dataIndex: 'deduction', align: 'right', render: won },
            { title: '실수령', dataIndex: 'net', align: 'right', render: won },
            { title: '파일', render: (_, s) => s.file_url && <a href={s.file_url}>받기</a> },
          ]}
          summary={() =>
            d.total && (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0}><b>연간 합계</b></Table.Summary.Cell>
                <Table.Summary.Cell index={1} align="right">{won(d.total.gross)}</Table.Summary.Cell>
                <Table.Summary.Cell index={2} align="right">{won(d.total.deduction)}</Table.Summary.Cell>
                <Table.Summary.Cell index={3} align="right">{won(d.total.net)}</Table.Summary.Cell>
                <Table.Summary.Cell index={4} />
              </Table.Summary.Row>
            )
          }
        />
        <Space style={{ marginTop: 8 }}>
          <span className="help">이 화면의 내용은 본인만 볼 수 있습니다 (관리자 포함). 단, 서버 DB 백업에는 포함됩니다.</span>
        </Space>
      </Card>
    </div>
  )
}
