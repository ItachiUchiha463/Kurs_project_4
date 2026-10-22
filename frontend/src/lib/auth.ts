// JWT у localStorage (ТЗ 11.1): переживає перезавантаження вкладки; ризик XSS знижує суворий CSP.
// Сховище може бути недоступне (приватне вікно, заблоковані дані сайту) – тоді сесія живе лише до перезавантаження.
const KEY = 'vigil.token'
let memory: string | null = null

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY) ?? memory
  } catch {
    return memory
  }
}

export function setToken(token: string): void {
  memory = token
  try {
    localStorage.setItem(KEY, token)
  } catch {
    /* лишається в пам'яті */
  }
}

export function clearToken(): void {
  memory = null
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* нічого */
  }
}
