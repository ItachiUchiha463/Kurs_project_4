import { clearToken, getToken } from '@/lib/auth'

/** Помилка в одному полі форми (приходить із сервера в деталях помилки валідації). */
export interface FieldError {
  field?: string
  message: string
}

/** Помилка API в єдиному форматі {"error": {code, message, details}} (ТЗ розд. 3.3). */
export class ApiError extends Error {
  status: number         // HTTP-код (0 – немає зв'язку)
  code: string           // машинний код помилки, наприклад «email_not_verified»
  details: FieldError[]  // помилки окремих полів: компоненти форм показують їх біля відповідних полів

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

/**
 * Єдина точка виклику REST API для всього застосунку: `api<Тип>('/targets')`.
 *
 * Що вона робить за вас:
 *   – додає шлях `/api` і параметри запиту (без порожніх);
 *   – додає заголовок Authorization з токеном, якщо користувач увійшов;
 *   – перетворює помилки сервера на ApiError з повідомленням для людини;
 *   – при 401 (токен недійсний) очищає токен і веде на сторінку входу.
 */
export async function api<T>(path: string, { method = 'GET', body, params }: Options = {}): Promise<T> {
  // Параметри у рядок запиту; значення undefined пропускаються (наприклад, необов'язкові фільтри).
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
    // fetch кидає виняток лише при проблемах мережі (сервер недоступний), а не при кодах 4xx/5xx.
    throw new ApiError(0, 'network', 'Немає зв’язку із сервером')
  }
  // 204/202: відповідь без тіла (видалення, прийнято до обробки): повертаємо порожній результат.
  if (res.status === 204 || res.status === 202) return undefined as T
  const data = await res.json().catch(() => null)
  if (res.ok) return data as T
  // Сторінки /auth/* самі показують «неправильний пароль» з 401, тому для них на вхід не перенаправляємо.
  if (res.status === 401 && !path.startsWith('/auth/')) {
    clearToken()  // токен недійсний чи відкликаний (token_version): повертаємо на вхід
    window.location.assign('/login')
  }
  const err = data?.error
  throw new ApiError(res.status, err?.code ?? 'error', err?.message ?? 'Сталася помилка', err?.details ?? [])
}
