// 측정값 표의 숫자 표시. 판정은 서버 passed 값을 쓰고 여기서 다시 계산하지 않는다.

type Num = string | null | undefined

const digits = (v: string) => (v.split('.')[1] ?? '').length

/** 숫자 글을 decimals 자리로 맞춘다. 원래 자릿수가 더 많으면 줄이지 않는다(판정 근거를 숨기지 않게). 빈 값은 「—」. */
export function fmtNum(v: Num, decimals: number | null | undefined): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return v
  return n.toFixed(Math.max(decimals ?? 0, digits(v)))
}

/** 서버가 자릿수를 주지 않으면 하한·상한 중 소수 자릿수가 큰 쪽. */
export const decimalsOf = (lsl: Num, usl: Num) => Math.max(digits(lsl ?? ''), digits(usl ?? ''))

/** 기준(중앙): 양쪽 한계가 있을 때만. 중앙값이 자릿수에서 잘리면 한 자리 더 보인다. */
export function center(lsl: Num, usl: Num, decimals: number): string {
  if (lsl == null || usl == null) return '—'
  const c = (Number(lsl) + Number(usl)) / 2
  const s = c.toFixed(decimals)
  return Number(s) === c ? s : c.toFixed(decimals + 1)
}

/** 하한~상한 사이 위치(0~100%)와 색 단계. 양 끝 10% 안이면 warn, 한계 밖이면 bad. 한쪽 규격·숫자 아님이면 null. */
export function specPosition(lsl: Num, usl: Num, v: Num): { pct: number; tone: 'ok' | 'warn' | 'bad' } | null {
  if (lsl == null || usl == null || v == null || v === '') return null
  const lo = Number(lsl)
  const hi = Number(usl)
  const x = Number(v)
  if (![lo, hi, x].every(Number.isFinite) || hi <= lo) return null
  const p = (x - lo) / (hi - lo)
  return { pct: Math.min(100, Math.max(0, p * 100)), tone: p < 0 || p > 1 ? 'bad' : p < 0.1 || p > 0.9 ? 'warn' : 'ok' }
}
