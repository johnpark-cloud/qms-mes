export type Recent = { label: string; href: string }

const KEY = 'qms.recent'

export function getRecent(): Recent[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    // 저장값은 사용자가 바꿀 수 있어서, 같은 사이트 안 주소(/ 로 시작, // 아님)만 쓴다.
    return Array.isArray(v)
      ? v.filter((r) => r && typeof r.label === 'string' && typeof r.href === 'string' && r.href.startsWith('/') && !r.href.startsWith('//'))
      : []
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
