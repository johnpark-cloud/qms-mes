// 검사 입력 API 응답 모양. qms/api/inspections.py 와 같다.
import { api } from './client'
import type { Page } from './specs'

export interface LotInfo {
  id: number
  number: string
  item_code: string
  item_name: string
  supplier: string
  qty: string
  on_hold: boolean
}

export interface QueueRow extends LotInfo {
  created_at: string
  spec_id: number
}

export interface LotSpec {
  id: number
  title: string
  inspection_type: string
  inspection_type_display: string
  done: boolean
}

export interface LotResult {
  lot: LotInfo
  specs: LotSpec[]
  created?: boolean
}

export interface Opt {
  value: number
  label: string
}

export interface FormData {
  lot: LotInfo
  spec: { id: number; title: string; sampling: string }
  characteristics: { id: number; name: string; spec_text: string; unit: string; is_variable: boolean; special: string }[]
  gauges: Opt[]
  defect_types: string[]
}

export interface SubmitResult {
  id: number
  result: string
  result_display: string
  nonconformance: { id: number; number: string } | null
}

const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const fetchQueue = (tab: string, q: string, page: number) =>
  api<Page<QueueRow>>(`/api/qms/inspect/queue/?tab=${tab}&q=${encodeURIComponent(q)}&page=${page}`)

export const lookupLot = (number: string) => api<LotResult>(`/api/qms/inspect/lot/?number=${encodeURIComponent(number)}`)

export const receiveLot = (body: { number: string; item: number; qty: string; supplier: string }) =>
  post<LotResult>('/api/qms/inspect/receive/', body)

export const fetchForm = (lotId: number, specId: number) => api<FormData>(`/api/qms/inspect/form/${lotId}/${specId}/`)

export const checkValues = (spec: number, values: Record<string, string>) =>
  post<{ results: Record<string, boolean | null> }>('/api/qms/inspect/check/', { spec, values })

export const submitInspection = (body: {
  lot: number
  spec: number
  gauge: number | null
  values: Record<string, string>
  defect_type?: string
  defect_qty?: string
}) => post<SubmitResult>('/api/qms/inspect/submit/', body)

export interface InspectionRow {
  id: number
  inspected_at: string
  lot_number: string
  item_code: string
  item_name: string
  supplier: string
  spec_title: string
  inspector: string
  result: string
  result_display: '합격' | '불합격' | '미판정'
  nc_number: string
}

export interface InspectionDetail {
  id: number
  title: string
  status: '합격' | '불합격' | '미판정'
  lot: { id: number; number: string; trace_url: string }
  item: { code: string; name: string }
  spec: { id: number; title: string }
  inspector: string
  inspected_at: string
  nonconformance: { id: number; number: string; url: string } | null
  measurements: { name: string; spec_text: string; value: string | null; gauge: string; passed: boolean | null }[]
  templates: { id: number; name: string; url: string }[]
}
