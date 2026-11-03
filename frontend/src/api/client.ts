export class ApiError extends Error {
  status: number
  detail: string
  fields: Record<string, string[]>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  constructor(status: number, detail: string, fields: Record<string, string[]> = {}, body: any = {}) {
    super(detail)
    this.status = status
    this.detail = detail
    this.fields = fields
    this.body = body
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
  // DRF 직렬화 오류는 {필드: ['메시지']} 모양이라 detail 이 없다. 그 키들을 fields 로 풀고 detail 은 첫 메시지로 쓴다.
  let fields: Record<string, string[]> = body.fields ?? {}
  let detail: string | undefined = body.detail
  if (detail === undefined && body && typeof body === 'object') {
    const shaped = Object.entries(body).filter(([, v]) => Array.isArray(v) && v.every((m) => typeof m === 'string'))
    if (shaped.length) {
      fields = Object.fromEntries(shaped) as Record<string, string[]>
      detail = (shaped[0][1] as string[])[0]
    }
  }
  throw new ApiError(r.status, detail ?? `요청에 실패했습니다 (${r.status}).`, fields, body)
}
