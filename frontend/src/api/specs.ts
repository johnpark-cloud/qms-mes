// 검사기준 API 응답 모양. qms/api/specs.py 의 _row·_detail·_log 와 InspectionSpec.document() 와 같다.
export interface SpecRow {
  id: number
  item_code: string
  item_name: string
  inspection_type: string
  inspection_type_display: string
  revision: number
  status: string
  is_current: boolean
  char_count: number
  approved_by: string
  approved_at: string | null
}

export interface CharRow {
  id: number
  name: string
  lsl: string
  usl: string
  unit: string
  special: string
  plan_line: number | null
  spc_url: string
}

export interface Option {
  value: string | number
  label: string
}

export interface DiffRow {
  id: number
  name: string
  status: 'added' | 'removed' | 'changed'
  cells: string[]
  values: Record<string, [string, string]>
}

export interface SpecDetail {
  id: number
  title: string
  item: { id: number; code: string; name: string }
  inspection_type: string
  inspection_type_display: string
  revision: number
  sampling: string
  note: string
  status: string
  approved_by: string
  approved_at: string | null
  version: number
  editable: boolean
  can_approve: boolean
  can_delete_rows: boolean
  prev_id: number | null
  characteristics: CharRow[]
  plan_line_options: Option[]
  special_options: Option[]
  diff: { fields: Record<string, [string, string]>; rows: DiffRow[] } | null
  templates: { id: number; name: string; url: string }[]
  edit_request_url: string
}

export interface RevLog {
  id: number
  label: string
  changes: string
  reason: string
  status: string
  status_display: string
  requested_by: string
  requested_at: string | null
  approved_by: string
  approved_at: string | null
  spec_id: number
}

export interface DocStruct {
  title: string
  number: string | null
  revision: string
  draft: boolean
  landscape?: boolean
  head: [string, string][]
  tables: { title: string; columns: string[]; rows: string[][] }[]
  revisions: ({ label: string; changes: string; reason: string; requested_by: string; approved_by: string; approved_at: string }[]) | null
  signoff: { written_by: string; written_at: string; approved_by: string; approved_at: string }
}

export interface Page<T> {
  count: number
  page: number
  has_more: boolean
  results: T[]
}

// qms/models.py InspectionSpec.TYPES 와 같은 값이다.
export const INSPECTION_TYPES = [
  { value: 'INCOMING', label: '수입검사' },
  { value: 'PROCESS', label: '공정검사' },
  { value: 'OUTGOING', label: '출하검사' },
]
