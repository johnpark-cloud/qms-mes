import { Alert, AutoComplete, Button, Form, Input, Modal, Select, Space, Tag, type InputRef } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { fetchQueue, lookupLot, receiveLot, type LotResult, type Opt, type QueueRow } from '../../api/inspect'
import DataList from '../../components/DataList'
import { useLotOptions } from '../../components/lotOptions'

const TABS = [
  { key: 'INCOMING', label: '수입' },
  { key: 'PROCESS', label: '공정' },
  { key: 'OUTGOING', label: '출하' },
]

const COLUMNS: ColumnsType<QueueRow> = [
  { title: 'LOT', dataIndex: 'number' },
  { title: '품번', dataIndex: 'item_code' },
  { title: '품명', dataIndex: 'item_name' },
  { title: '협력사', dataIndex: 'supplier' },
  { title: '수량', dataIndex: 'qty', align: 'right' },
  { title: '생성일', dataIndex: 'created_at', render: (v: string) => v.slice(0, 10) },
  { title: '보류', dataIndex: 'on_hold', render: (v: boolean) => (v ? <Tag color="red">보류</Tag> : null) },
]

const exportHref = (tab: string, q: string) => `/api/qms/inspect/queue/?tab=${tab}&q=${encodeURIComponent(q)}&export=xlsx`

interface Receive {
  number: string
  items: Opt[]
  suppliers: string[]
}

function ReceiveModal({ init, onClose, onDone }: { init: Receive | null; onClose: () => void; onDone: (r: LotResult) => void }) {
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  useEffect(() => {
    setErr('')
    setSaving(false)
  }, [init])

  const submit = async (v: { number: string; item: number; qty: string; supplier?: string }) => {
    setErr('')
    setSaving(true)
    try {
      onDone(await receiveLot({ number: v.number.trim(), item: v.item, qty: v.qty.trim(), supplier: (v.supplier ?? '').trim() }))
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : '입고 등록에 실패했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={init !== null} onCancel={onClose} closable={!saving} maskClosable={!saving} keyboard={!saving} title="입고 등록" footer={null} destroyOnHidden>
      <Form key={init?.number} form={form} layout="vertical" initialValues={{ number: init?.number, qty: '', supplier: '' }} onFinish={submit}>
        <Form.Item label="LOT 번호" name="number" rules={[{ required: true, whitespace: true, message: 'LOT 번호를 입력하세요.' }]}>
          <Input />
        </Form.Item>
        <Form.Item label="품목" name="item" rules={[{ required: true, message: '품목을 고르세요.' }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={init?.items ?? []}
            placeholder="품목 검색"
            notFoundContent="승인된 검사기준이 있는 품목이 없습니다"
          />
        </Form.Item>
        <Form.Item label="입고수량" name="qty" rules={[{ required: true, whitespace: true, message: '입고수량을 입력하세요.' }]}>
          <Input inputMode="decimal" />
        </Form.Item>
        <Form.Item label="협력사" name="supplier">
          <AutoComplete options={(init?.suppliers ?? []).map((s) => ({ value: s }))} filterOption />
        </Form.Item>
        {err && <Alert style={{ marginBottom: 12 }} type="error" message={err} />}
        <Space>
          <Button type="primary" htmlType="submit" loading={saving}>
            저장
          </Button>
          <Button onClick={onClose} disabled={saving}>취소</Button>
        </Space>
      </Form>
    </Modal>
  )
}

export default function InspectPage() {
  const nav = useNavigate()
  const scan = useRef<InputRef>(null)
  const busy = useRef(false)
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<LotResult | null>(null)
  const [notice, setNotice] = useState('')
  const [err, setErr] = useState('')
  const [receive, setReceive] = useState<Receive | null>(null)
  const [open, setOpen] = useState(false) // 조회 뒤 다시 포커스해도 목록이 저절로 열려 입고 창을 가리지 않게 직접 연다

  useEffect(() => scan.current?.focus(), [])

  const lotOptions = useLotOptions(text)

  const find = async (number = text.trim()) => {
    if (!number || busy.current) return
    setOpen(false)
    busy.current = true
    setLoading(true)
    setErr('')
    setNotice('')
    setResult(null)
    try {
      setResult(await lookupLot(number))
    } catch (e) {
      if (e instanceof ApiError && e.status === 404 && e.body.can_receive === true) {
        setReceive({ number, items: e.body.items ?? [], suppliers: e.body.suppliers ?? [] })
      } else if (e instanceof ApiError && e.status === 404) {
        setErr('등록되지 않은 LOT입니다. 입고 등록 권한이 있는 사람에게 요청하세요.')
      } else {
        setErr(e instanceof ApiError ? e.detail : 'LOT을 조회하지 못했습니다.')
      }
    } finally {
      busy.current = false
      setLoading(false)
      setText('')
      scan.current?.focus()
    }
  }

  const received = (r: LotResult) => {
    setReceive(null)
    setResult(r)
    setNotice(r.created === false ? '이미 등록된 LOT입니다. 기존 LOT으로 검사합니다.' : '')
  }

  return (
    <div>
      <h1 className="page-title">검사 입력</h1>
      {/* 스캐너는 그대로 번호 + Enter. 손으로 찾을 때는 번호·품번·품명·협력사 일부를 치고 목록에서 고른다. */}
      <AutoComplete
        style={{ width: '100%', maxWidth: 480 }}
        options={lotOptions}
        value={text}
        open={open && !receive}
        onOpenChange={setOpen}
        onChange={(v) => {
          setText(v)
          setOpen(true)
        }}
        onSelect={(v) => void find(v)}
        defaultActiveFirstOption={false}
      >
        <Input
          ref={scan}
          size="large"
          placeholder="LOT 번호를 스캔하거나 입력하고 Enter"
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || e.nativeEvent.isComposing || e.keyCode === 229) return
            e.preventDefault()
            // 목록에서 화살표로 고른 뒤 Enter 면 고른 LOT(onSelect)이 먼저 조회되게 한 박자 늦춘다.
            setTimeout(() => void find(), 0)
          }}
        />
      </AutoComplete>
      <div className="palette-sub" style={{ marginTop: 4 }}>번호를 몰라도 품번·품명·협력사 일부를 치면 목록에서 고를 수 있습니다.</div>
      {err && <Alert style={{ marginTop: 12 }} type="error" message={err} role="alert" />}
      {notice && <Alert style={{ marginTop: 12 }} type="info" message={notice} />}
      {result && (
        <div style={{ margin: '12px 0 20px' }}>
          <p>
            <b>{result.lot.number}</b> · {result.lot.item_code} {result.lot.item_name} · {result.lot.supplier || '협력사 없음'} · 수량 {result.lot.qty}
            {result.lot.on_hold && <Tag color="red" style={{ marginLeft: 8 }}>보류</Tag>}
          </p>
          {result.specs.length ? (
            <Space wrap>
              {result.specs.map((s) => (
                <Button key={s.id} type="primary" onClick={() => nav(`/inspect/${result.lot.id}/${s.id}`)}>
                  {s.inspection_type_display}
                  {s.done && ' (재검사)'}
                </Button>
              ))}
            </Space>
          ) : (
            <Alert type="warning" message="이 품번에는 승인된 검사기준이 없습니다." />
          )}
        </div>
      )}
      <h2 style={{ marginTop: 24 }}>검사 대기</h2>
      <DataList<QueueRow>
        columns={COLUMNS}
        tabs={TABS}
        fetchPage={fetchQueue}
        exportHref={exportHref}
        onOpen={(r) => nav(`/inspect/${r.id}/${r.spec_id}`)}
        rowKey={(r) => r.id}
        emptyText="검사 대기 중인 LOT이 없습니다."
      />
      <ReceiveModal init={receive} onClose={() => setReceive(null)} onDone={received} />
    </div>
  )
}
