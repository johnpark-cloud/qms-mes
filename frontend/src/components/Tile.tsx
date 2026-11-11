import { Tag, theme } from 'antd'
import type { ReactNode } from 'react'

export interface Row {
  label: string
  href?: string | null
  meta?: ReactNode
  tone?: string | null
}

export interface TileData {
  value: string | number
  sub?: string
  tone?: string
  href?: string
  more?: string
  rows?: Row[]
}

const TAG: Record<string, string> = { positive: 'success', critical: 'warning', negative: 'error', info: 'processing' }

// 서버가 주는 tone(positive·critical·negative·info·''·neutral)을 antd 테마 색으로 바꾼다.
function useToneColor(tone?: string | null) {
  const { token } = theme.useToken()
  const colors: Record<string, string> = { positive: token.colorSuccess, critical: token.colorWarning, negative: token.colorError, info: token.colorInfo }
  return colors[tone ?? ''] ?? token.colorTextHeading
}

// 줄 오른쪽 값: tone 이 있으면 상태 배지로, 없으면 흐린 글씨로 보인다.
function Meta({ meta, tone }: Pick<Row, 'meta' | 'tone'>) {
  const { token } = theme.useToken()
  if (meta === undefined || meta === '' || meta === null) return null
  if (tone && TAG[tone]) return <Tag color={TAG[tone]} style={{ marginInlineEnd: 0 }}>{meta}</Tag>
  return <span style={{ color: token.colorTextSecondary }}>{meta}</span>
}

export function RowList({ rows, empty = '표시할 항목이 없습니다.' }: { rows: Row[]; empty?: string }) {
  const { token } = theme.useToken()
  if (!rows.length) return <p style={{ margin: 0, color: token.colorTextSecondary }}>{empty}</p>
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {rows.map((r, i) => (
        <li key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '6px 0', minWidth: 0 }}>
          {/* 둘 다 줄어들되 번호 쪽은 40% 아래로 줄지 않는다(긴 설명 옆에서 번호가 한 글자씩 꺾이지 않게). */}
          <span style={{ minWidth: '40%', overflowWrap: 'anywhere' }}>{r.href ? <a href={r.href}>{r.label}</a> : r.label}</span>
          <span style={{ minWidth: 0, textAlign: 'right', overflowWrap: 'anywhere' }}><Meta meta={r.meta} tone={r.tone} /></span>
        </li>
      ))}
    </ul>
  )
}

// 숫자 타일: 머리(제목·부제·큰 숫자)는 href 로 가는 링크이고, details 이면 아래에 줄 목록과 '전체 보기'가 붙는다.
// href 가 '#앵커'(옛 화면 안쪽 위치)이면 갈 곳이 없어 more 를 쓴다.
export default function Tile({ title, tile, details = false }: { title: string; tile: TileData; details?: boolean }) {
  const { token } = theme.useToken()
  const color = useToneColor(tile.tone)
  const go = tile.href?.startsWith('#') ? tile.more : (tile.href ?? tile.more)
  const head = (
    <>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', fontWeight: 500, color: token.colorText }}>{title}</span>
        <span style={{ display: 'block', color: token.colorTextSecondary, overflowWrap: 'anywhere' }}>{tile.sub}</span>
      </span>
      <span style={{ fontSize: 36, fontWeight: 500, lineHeight: 1.1, color, fontVariantNumeric: 'tabular-nums' }}>{tile.value}</span>
    </>
  )
  const headStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, textDecoration: 'none' }
  return (
    <div style={{ background: token.colorBgContainer, border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadiusLG, padding: 16, height: '100%', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
      {go ? <a href={go} style={headStyle}>{head}</a> : <div style={headStyle}>{head}</div>}
      {details && <RowList rows={tile.rows ?? []} />}
      {details && tile.more && <a href={tile.more} style={{ marginTop: 'auto' }}>전체 보기</a>}
    </div>
  )
}
