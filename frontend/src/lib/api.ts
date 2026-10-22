import { clearToken, getToken } from '@/lib/auth'

export interface FieldError {
  field?: string
  message: string
}

/** Помилка API в єдиному форматі {"error": {code, message, details}} (ТЗ розд. 3.3). */
export class ApiError extends Error {
  status: number
  code: string
  details: FieldError[]

  constructor(status: number, code: string, message: string, details: FieldError[] = []) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

interface Options {
  method?: string
  body?: unknown
  params?: Record<string, string | number | undefined>
}

export async function api<T>(path: string, { method = 'GET', body, params }: Options = {}): Promise<T> {
  const query = params
    ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))
    : ''
  const token = getToken()
  let res: Response
  try {
    res = await fetch('/api' + path + query, {
      method,
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network', 'Немає зв’язку із сервером')
  }
  if (res.status === 204 || res.status === 202) return undefined as T
  const data = await res.json().catch(() => null)
  if (res.ok) return data as T
  if (res.status === 401 && !path.startsWith('/auth/')) {
    clearToken()  // токен недійсний чи відкликаний (token_version): повертаємо на вхід
    window.location.assign('/login')
  }
  const err = data?.error
  throw new ApiError(res.status, err?.code ?? 'error', err?.message ?? 'Сталася помилка', err?.details ?? [])
}
