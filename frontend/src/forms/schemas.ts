import { z } from 'zod'

// Правила повторюють ТЗ розд. 6; бекенд перевіряє все ще раз – тут лише зручність користувача
const email = z.email('Введіть email у форматі name@example.ua')
const password = z
  .string()
  .min(8, 'Щонайменше 8 символів')
  .regex(/[A-Za-zА-Яа-яІіЇїЄєҐґ]/, 'Потрібна хоча б одна літера')
  .regex(/\d/, 'Потрібна хоча б одна цифра')

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
  })
  .refine((v) => v.type === 'server' || /^https?:\/\/\S+$/.test(v.address ?? ''), {
    path: ['address'],
    message: 'Адреса має починатися з http:// або https://',
  })

export const resolveSchema = z.object({
  comment: z.string().trim().min(1, 'Напишіть, чому закриваєте інцидент – це побачать колеги').max(1000),
})
