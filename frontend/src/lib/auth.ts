// JWT у localStorage (ТЗ 11.1): переживає перезавантаження вкладки; ризик XSS знижує суворий CSP.
// Сховище може бути недоступне (приватне вікно, заблоковані дані сайту) – тоді сесія живе лише до перезавантаження.
const KEY = 'vigil.token'
// Копія в пам'яті: якщо localStorage недоступний, токен усе одно працює, поки відкрита вкладка.
let memory: string | null = null

/** Токен входу або null, якщо користувач не увійшов. */
export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY) ?? memory
  } catch {
    return memory
  }
}

/** Зберігає токен після входу. */
export function setToken(token: string): void {
  memory = token
  try {
    localStorage.setItem(KEY, token)
  } catch {
    /* лишається в пам'яті */
  }
}

/** Видаляє токен (вихід, недійсний токен). */
export function clearToken(): void {
  memory = null
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* нічого */
  }
}
