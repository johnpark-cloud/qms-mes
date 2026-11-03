export type Recent = { label: string; href: string }

const KEY = 'qms.recent'

export function getRecent(): Recent[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

export function addRecent(r: Recent): void {
  try {
    const list = [r, ...getRecent().filter((x) => x.href !== r.href)].slice(0, 5)
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    // 저장소를 쓸 수 없으면 최근 기록만 남기지 않는다.
  }
}
