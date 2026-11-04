import { DeleteOutlined } from '@ant-design/icons'
import { Button, Select, Tooltip } from 'antd'
import type { ClipboardEvent, KeyboardEvent } from 'react'
import type { DiffRow, Option } from '../api/specs'
import { parseTsv } from '../lib/tsv'

export interface GridColumn {
  key: string
  label: string
  kind: 'text' | 'number' | 'select' | 'link'
  options?: Option[]
  width?: number | string
}
export interface GridRow {
  _key: string
  id: number | null
  delete?: boolean
  [k: string]: string | number | boolean | null | undefined
}

interface Props {
  columns: GridColumn[]
  rows: GridRow[]
  onChange: (rows: GridRow[]) => void
  readOnly: boolean
  errors: Record<string, string[]>
  diff?: { rows: DiffRow[] } | null
  canDelete?: boolean
  errorPrefix?: string // 오류 키 앞부분(characteristics·bom·routing·rows)
}

let seq = 0
export const newKey = () => `n${++seq}`

export const isBlank = (r: GridRow, cols: GridColumn[]) =>
  r.id === null && cols.filter((c) => c.kind !== 'link').every((c) => String(r[c.key] ?? '').trim() === '')

// 맨 아래에 입력용 빈 줄이 하나 있게 한다.
export function withTail(rows: GridRow[], cols: GridColumn[], readOnly = false): GridRow[] {
  if (readOnly || (rows.length && isBlank(rows[rows.length - 1], cols))) return rows
  return [...rows, { _key: newKey(), id: null }]
}

export default function EditGrid({ columns, rows, onChange, readOnly, errors, diff, canDelete = true, errorPrefix = 'characteristics' }: Props) {
  const change = (next: GridRow[]) => onChange(withTail(next, columns, readOnly))
  const set = (i: number, key: string, v: string | number | null) => change(rows.map((r, j) => (j === i ? { ...r, [key]: v } : r)))

  const toValue = (c: GridColumn, text: string) => {
    if (c.kind !== 'select') return text
    const o = c.options?.find((x) => x.label === text || String(x.value) === text)
    return o ? o.value : text
  }

  const paste = (e: ClipboardEvent<HTMLElement>, i: number, key: string) => {
    if (readOnly || rows[i]?.delete) return // 읽기 전용 칸에도 붙여넣기 이벤트는 오므로 직접 막는다
    const text = e.clipboardData.getData('text/plain')
    if (!/[\t\r\n]/.test(text)) return // 한 칸 붙여넣기는 기본 동작에 맡긴다
    e.preventDefault()
    const cols = columns.filter((c) => c.kind !== 'link')
    const start = cols.findIndex((c) => c.key === key)
    const next = [...rows]
    parseTsv(text).forEach((cells, dy) => {
      const at = i + dy
      if (!next[at]) next[at] = { _key: newKey(), id: null }
      const row = { ...next[at] }
      cells.forEach((t, dx) => {
        const c = cols[start + dx]
        if (c) row[c.key] = toValue(c, t)
      })
      next[at] = row
    })
    change(next)
  }

  const keys = (e: KeyboardEvent<HTMLElement>, key: string) => {
    if (e.key !== 'Enter' || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return
    const tr = (e.target as HTMLElement).closest('[data-grid-row]')
    const below = tr?.nextElementSibling?.querySelector<HTMLElement>(`[data-col="${key}"] input`)
    if (below) {
      e.preventDefault()
      below.focus()
    }
  }

  const diffRow = (r: GridRow) => (diff && r.id !== null ? diff.rows.find((d) => d.id === r.id) : undefined)
  const removed = diff?.rows.filter((d) => d.status === 'removed') ?? []

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="grid-table" data-grid>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{ width: c.width }}>
                {c.label}
              </th>
            ))}
            {!readOnly && <th style={{ width: 48 }} aria-label="삭제" />}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const d = diffRow(r)
            return (
              <tr key={r._key} data-grid-row style={r.delete ? { textDecoration: 'line-through', opacity: 0.6 } : undefined} className={d?.status === 'added' ? 'diff-added' : undefined}>
                {columns.map((c) => {
                  const err = errors[`${errorPrefix}.${i}.${c.key}`]
                  const cls = [d?.cells.includes(c.key) ? 'diff-changed' : '', err ? 'cell-error' : ''].join(' ').trim()
                  const old = d?.values[c.key]?.[0]
                  let body
                  if (c.kind === 'link') {
                    body = r.id !== null && r[c.key] ? <a href={String(r[c.key])}>관리도</a> : null
                  } else if (c.kind === 'select') {
                    body = (
                      <Select
                        showSearch
                        optionFilterProp="label"
                        placeholder="선택"
                        notFoundContent="찾는 항목이 없습니다"
                        variant="borderless"
                        style={{ width: '100%' }}
                        disabled={readOnly || r.delete}
                        options={c.options}
                        value={(r[c.key] as string | number | null) ?? undefined}
                        onChange={(v) => set(i, c.key, v ?? null)}
                      />
                    )
                  } else {
                    body = (
                      <input
                        aria-label={c.label}
                        style={{ width: '100%', border: 'none', background: 'transparent', color: 'inherit', font: 'inherit', padding: 0 }}
                        inputMode={c.kind === 'number' ? 'decimal' : undefined}
                        readOnly={readOnly || r.delete}
                        value={String(r[c.key] ?? '')}
                        onChange={(e) => set(i, c.key, e.target.value)}
                        onKeyDown={(e) => keys(e, c.key)}
                      />
                    )
                  }
                  return (
                    <td key={c.key} data-col={c.key} className={cls || undefined}>
                      <Tooltip title={err?.join(' ')} open={err ? undefined : false}>
                        <div onPaste={(e) => paste(e, i, c.key)}>{body}</div>
                      </Tooltip>
                      {old !== undefined && <div className="palette-sub">이전: {old || '없음'}</div>}
                    </td>
                  )
                })}
                {!readOnly && (
                  <td>
                    {(r.id === null ? !isBlank(r, columns) : canDelete) && (
                      <Button
                        size="small"
                        type="text"
                        aria-label={r.delete ? '삭제 취소' : '줄 삭제'}
                        icon={<DeleteOutlined />}
                        // 새 줄은 저장 전이라 그냥 지우고, 저장된 줄은 취소선으로만 표시한다.
                        onClick={() => change(r.id === null ? rows.filter((_, j) => j !== i) : rows.map((x, j) => (j === i ? { ...x, delete: !x.delete } : x)))}
                      />
                    )}
                  </td>
                )}
              </tr>
            )
          })}
          {removed.map((d) => (
            <tr key={`rm${d.id}`}>
              <td colSpan={columns.length + (readOnly ? 0 : 1)} className="diff-removed">
                이전 개정에만 있던 항목: {d.name}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
