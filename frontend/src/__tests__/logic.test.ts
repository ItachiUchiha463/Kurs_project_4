import { describe, expect, it } from 'vitest'

import { forgotSchema, loginSchema, registerSchema, resetSchema, resolveSchema, targetSchema } from '@/forms/schemas'
import { duration, num, plural } from '@/lib/format'

describe('plural', () => {
  const p = (n: number) => plural(n, 'інцидент', 'інциденти', 'інцидентів')
  it.each([[1, 'інцидент'], [2, 'інциденти'], [4, 'інциденти'], [5, 'інцидентів'], [11, 'інцидентів'], [12, 'інцидентів'],
    [14, 'інцидентів'], [21, 'інцидент'], [22, 'інциденти'], [25, 'інцидентів'], [101, 'інцидент'], [111, 'інцидентів']])('%i → %s', (n, word) => {
    expect(p(n)).toBe(word)
  })
})

describe('format', () => {
  it('використовує десяткову кому', () => {
    expect(num(96.4)).toBe('96,4')
    expect(num(50)).toBe('50')
  })
  it('рахує тривалість', () => {
    const t0 = '2026-10-22T12:00:00Z'
    expect(duration(t0, '2026-10-22T12:00:30Z')).toBe('30 с')
    expect(duration(t0, '2026-10-22T12:12:00Z')).toBe('12 хв')
    expect(duration(t0, '2026-10-22T14:05:00Z')).toBe('2 год 5 хв')
  })
})

describe('схеми форм повторюють правила бекенда', () => {
  it('вхід: email і пароль обов’язкові', () => {
    expect(loginSchema.safeParse({ email: 'x', password: '' }).success).toBe(false)
    expect(loginSchema.safeParse({ email: 'a@example.ua', password: 'x' }).success).toBe(true)
  })
  it('реєстрація: пароль із літерою й цифрою, повтор збігається', () => {
    const ok = { full_name: 'Ада', email: 'a@example.ua', password: 'Passw0rd1', repeat: 'Passw0rd1' }
    expect(registerSchema.safeParse(ok).success).toBe(true)
    expect(registerSchema.safeParse({ ...ok, password: 'short1', repeat: 'short1' }).success).toBe(false)
    const long = 'Привіт'.repeat(10) + '1'
    expect(registerSchema.safeParse({ ...ok, password: long, repeat: long }).success).toBe(false)
    expect(registerSchema.safeParse({ ...ok, password: 'onlyletters', repeat: 'onlyletters' }).success).toBe(false)
    expect(registerSchema.safeParse({ ...ok, password: '12345678', repeat: '12345678' }).success).toBe(false)
    const mismatch = registerSchema.safeParse({ ...ok, repeat: 'Other0000' })
    expect(mismatch.success).toBe(false)
    expect(!mismatch.success && mismatch.error.issues[0].path).toEqual(['repeat'])
  })
  it('об’єкт: сервіс потребує http-адреси, сервер – ні', () => {
    expect(targetSchema.safeParse({ name: 'web-01', type: 'server' }).success).toBe(true)
    expect(targetSchema.safeParse({ name: 'shop', type: 'service', address: 'shop.example.ua' }).success).toBe(false)
    expect(targetSchema.safeParse({ name: 'shop', type: 'service', address: 'https://shop.example.ua' }).success).toBe(true)
    expect(targetSchema.safeParse({ name: '', type: 'server' }).success).toBe(false)
    const svc = (check_type: 'tcp' | 'ping', address: string) => targetSchema.safeParse({ name: 's', type: 'service', check_type, address }).success
    expect(svc('tcp', 'db.example.ua:5432')).toBe(true)
    expect(svc('tcp', 'db.example.ua')).toBe(false)
    expect(svc('ping', 'gw.example.ua')).toBe(true)
    expect(svc('ping', 'https://gw.example.ua')).toBe(false)
    expect(targetSchema.safeParse({ name: 'web', type: 'server', ping_enabled: true }).success).toBe(false)
    expect(targetSchema.safeParse({ name: 'web', type: 'server', ping_enabled: true, address: 'web.example.ua' }).success).toBe(true)
  })
  it('закриття інциденту без коментаря заборонено', () => {
    expect(resolveSchema.safeParse({ comment: '   ' }).success).toBe(false)
    expect(resolveSchema.safeParse({ comment: 'Перезапустив сервіс' }).success).toBe(true)
  })
})

describe('скидання пароля', () => {
  it('новий пароль підпорядковується тим самим правилам і має збігатися з повтором', () => {
    expect(resetSchema.safeParse({ password: 'N3wPassword', repeat: 'N3wPassword' }).success).toBe(true)
    expect(resetSchema.safeParse({ password: 'N3wPassword', repeat: 'other' }).success).toBe(false)
    expect(resetSchema.safeParse({ password: 'short1', repeat: 'short1' }).success).toBe(false)
    expect(forgotSchema.safeParse({ email: 'a@example.ua' }).success).toBe(true)
    expect(forgotSchema.safeParse({ email: 'nope' }).success).toBe(false)
  })
})
