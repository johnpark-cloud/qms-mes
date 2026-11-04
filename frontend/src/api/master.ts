import type { Option } from './specs'

// 품번·표 화면 API 응답 모양. core/api/master.py 의 _row·_detail·TableView._out 와 같다.
export interface ItemRow {
  id: number
  code: string
  name: string
  item_type: string
  item_type_display: string
  bom_count: number
  routing_count: number
}

export interface ItemDetail {
  id: number
  title: string
  code: string
  name: string
  item_type: string
  version: string | number
  editable: boolean
  can_delete_rows: { bom: boolean; routing: boolean }
  bom: { id: number; component: number; qty: string }[]
  routing: { id: number; seq: number; process: number }[]
  item_options: Option[]
  process_options: Option[]
  type_options: Option[]
}

export interface TableData {
  version: string | number
  editable: boolean
  can_delete: boolean
  rows: ({ id: number } & Record<string, string | number | null>)[]
}
