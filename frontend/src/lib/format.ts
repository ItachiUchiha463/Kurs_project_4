const TZ = 'Europe/Kyiv'  // у БД і API час UTC, київський – лише тут

const numberFmt = new Intl.NumberFormat('uk-UA', { maximumFractionDigits: 1 })
const timeFmt = new Intl.DateTimeFormat('uk-UA', { hour: '2-digit', minute: '2-digit', timeZone: TZ })
const dateTimeFmt = new Intl.DateTimeFormat('uk-UA', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: TZ })

export const num = (v: number) => numberFmt.format(v)
export const time = (iso: string) => timeFmt.format(new Date(iso))
export const dateTime = (iso: string) => dateTimeFmt.format(new Date(iso))

/** 1 інцидент, 2 інциденти, 5 інцидентів (11–14 – завжди «інцидентів»). */
export function plural(n: number, one: string, few: string, many: string): string {
  const a = n % 10
  const b = n % 100
  return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many
}

export function duration(fromIso: string, toIso?: string | null): string {
  const s = Math.max(0, Math.round(((toIso ? new Date(toIso) : new Date()).getTime() - new Date(fromIso).getTime()) / 1000))
  if (s < 60) return `${s} с`
  if (s < 3600) return `${Math.floor(s / 60)} хв`
  const h = Math.floor(s / 3600)
  return `${h} год${s % 3600 >= 60 ? ` ${Math.floor((s % 3600) / 60)} хв` : ''}`
}

export function ago(iso: string | null): string {
  if (!iso) return 'ще не було даних'
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  return s < 10 ? 'щойно' : `${duration(iso)} тому`
}
