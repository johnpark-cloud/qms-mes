// 관리계획서 API 응답 모양. qms/api/plans.py 의 _row·_detail·_line 과 같다.
import type { DiffRow, Option } from './specs'

export interface PlanRow {
  id: number
  item_code: string
  item_name: string
  stage: string
  stage_display: string
  revision: number
  status: string
  is_current: boolean
  line_count: number
  approved_by: string
  approved_at: string | null
}

export interface PlanLine {
  id: number
  process: number | null
  characteristic: string
  special: string
  lsl: string
  usl: string
  unit: string
  method: string
  sampling: string
  inspection_type: string
  reaction: string
  failure_mode: string
  severity: number | null
  occurrence: number | null
  detection: number | null
}

export interface PlanDetail {
  id: number
  title: string
  item: { id: number; code: string; name: string }
  stage: string
  stage_display: string
  revision: number
  status: string
  approved_by: string
  approved_at: string | null
  version: number
  editable: boolean
  can_approve: boolean
  can_delete_rows: boolean
  can_make_specs: boolean
  prev_id: number | null
  lines: PlanLine[]
  process_options: Option[]
  special_options: Option[]
  type_options: Option[]
  stage_options: Option[]
  diff: { fields: Record<string, [string, string]>; rows: DiffRow[] } | null
  edit_request_url: string
}

// qms/models.py ControlPlan.STAGES 와 같은 값이다.
export const PLAN_STAGES = [
  { value: 'PROTO', label: '시작품' },
  { value: 'PRELAUNCH', label: '양산 전' },
  { value: 'PRODUCTION', label: '양산' },
]
