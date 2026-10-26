import { z } from 'zod'

// Правила повторюють ТЗ розд. 6; бекенд перевіряє все ще раз – тут лише зручність користувача
const email = z.email('Введіть email у форматі name@example.ua')
const password = z
  .string()
  .min(8, 'Щонайменше 8 символів')
  .regex(/[A-Za-zА-Яа-яІіЇїЄєҐґ]/, 'Потрібна хоча б одна літера')
  .regex(/\d/, 'Потрібна хоча б одна цифра')
  .refine((v) => new TextEncoder().encode(v).length <= 72, 'Пароль задовгий (не більше 72 байтів; кирилична літера – 2 байти)')

export const loginSchema = z.object({ email, password: z.string().min(1, 'Введіть пароль') })

export const registerSchema = z
  .object({
    full_name: z.string().trim().min(2, 'Щонайменше 2 символи').max(100, 'Не більше 100 символів'),
    email,
    password,
    repeat: z.string(),
  })
  .refine((v) => v.password === v.repeat, { path: ['repeat'], message: 'Паролі не збігаються' })

export const targetSchema = z
  .object({
    name: z.string().trim().min(1, 'Вкажіть назву: вона показується на дашборді').max(100),
    type: z.enum(['server', 'service']),
    address: z.string().trim().optional(),
    host_id: z.string().optional(),
    check_type: z.enum(['http', 'tcp', 'ping']).optional(),
    ping_enabled: z.boolean().optional(),
  })
  .superRefine((v, ctx) => {
    const a = v.address ?? ''
    const kind = v.check_type ?? 'http'
    const fail = (message: string) => ctx.addIssue({ code: 'custom', path: ['address'], message })
    if (v.type === 'server') return void (v.ping_enabled && !a && fail('Для ping вкажіть адресу сервера'))
    if (kind === 'http' && !/^https?:\/\/\S+$/.test(a)) fail('Адреса має починатися з http:// або https://')
    if (kind === 'tcp' && !/^[^\s:/]+:\d{1,5}$/.test(a)) fail('Адреса має вигляд хост:порт, наприклад db.example.ua:5432')
    if (kind === 'ping' && !/^[^\s:/]+$/.test(a)) fail('Вкажіть лише ім’я хоста або IP, без http:// і порту')
  })

export const forgotSchema = z.object({ email })

export const resetSchema = z
  .object({ password, repeat: z.string() })
  .refine((v) => v.password === v.repeat, { path: ['repeat'], message: 'Паролі не збігаються' })

export const resolveSchema = z.object({
  comment: z.string().trim().min(1, 'Напишіть, чому закриваєте інцидент – це побачать колеги').max(1000),
})
