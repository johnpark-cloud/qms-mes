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
  code_parts: string
}

export interface ItemDetail {
  id: number
  title: string
  code: string
  code_parts: string
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

// core/api/numbering.py item-options 응답. 규칙 기반 자동 품번 등록 창이 쓴다.
export interface NumberOption {
  id?: number
  code: string
  name: string
  item_type?: string
  parent_id?: number | null
}
export interface NumberField {
  kind: 'code' | 'ref'
  label: string
  parent: number | null
  options: NumberOption[]
}
export interface NumberRuleOptions {
  id: number
  name: string
  pattern: string
  fields: NumberField[]
}
export interface ItemNumberOptions {
  rules: NumberRuleOptions[]
}
