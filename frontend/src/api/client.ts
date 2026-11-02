export class ApiError extends Error {
  status: number
  detail: string
  fields: Record<string, string[]>

  constructor(status: number, detail: string, fields: Record<string, string[]> = {}) {
    super(detail)
    this.status = status
    this.detail = detail
    this.fields = fields
  }
}

const WRITE = ['POST', 'PUT', 'PATCH', 'DELETE']

function cookie(name: string): string {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : ''
}

// 로그인 상태인지 싼 호출로 확인한다. 권한이 없어서 난 403과 세션 만료를 구분하는 데만 쓴다.
async function loggedIn(): Promise<boolean> {
  const r = await fetch('/api/auth/me/', { credentials: 'same-origin' })
  return r.ok
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (WRITE.includes(method)) {
    if (!cookie('csrftoken')) await fetch('/api/auth/csrf/', { credentials: 'same-origin' })
    headers.set('X-CSRFToken', cookie('csrftoken'))
  }
  if (typeof init.body === 'string' && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const r = await fetch(path, { ...init, method, headers, credentials: 'same-origin' })
  if (r.ok) return r.status === 204 ? (undefined as T) : ((await r.json()) as T)

  const body = await r.json().catch(() => ({}))
  if (r.status === 403 && !path.startsWith('/api/auth/') && !(await loggedIn())) {
    const here = location.pathname + location.search
    location.href = '/app/login?next=' + encodeURIComponent(here)
    return new Promise<T>(() => {}) // 이동 중이라 이 호출은 끝내지 않는다
  }
  throw new ApiError(r.status, body.detail ?? `요청에 실패했습니다 (${r.status}).`, body.fields ?? {})
}
