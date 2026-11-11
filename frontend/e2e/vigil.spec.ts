import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const stamp = Date.now()
const PASSWORD = 'Passw0rd1'
const HOST = 'web-01'

async function register(page: Page, email: string) {
  await page.goto('/register')
  await page.locator('#full_name').fill('Ада Лавлейс')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill(PASSWORD)
  await page.locator('#repeat').fill(PASSWORD)
  await page.getByRole('button', { name: 'Зареєструватися' }).click()
  await expect(page).toHaveURL(/\/targets\/new/)
}

const jwt = (page: Page) => page.evaluate(() => localStorage.getItem('vigil.token'))

async function sendMetrics(request: APIRequestContext, agentToken: string, records: { metric: string; value: number; instance?: string }[]) {
  const r = await request.post('/api/ingest', {
    headers: { Authorization: `Bearer ${agentToken}` },
    data: records.map((x) => ({ host: HOST, instance: '', ...x, timestamp: new Date().toISOString() })),
  })
  expect(r.status()).toBe(200)
}

// Сценарії залежать один від одного (користувач, сервер, токен агента), тому йдуть послідовно.
test.describe.serial('Vigil, наскрізні сценарії', () => {
  const email = `e2e-${stamp}@example.com`
  let agentToken = ''
  let targetId = 0

  test('неправильний пароль показує помилку, а не впускає', async ({ page }) => {
    await page.goto('/login')
    await page.locator('#email').fill('nobody@example.com')
    await page.locator('#password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Увійти' }).click()
    await expect(page.getByRole('alert')).toContainText('Неправильний email або пароль')
    await expect(page).toHaveURL(/\/login/)
  })

  test('реєстрація й підключення першого сервера: майстер видає токен агента', async ({ page }) => {
    await register(page, email)
    await page.locator('#name').fill(HOST)
    await page.getByRole('button', { name: 'Далі' }).click()
    const command = await page.getByText(/--token 'vgl_[\w-]+'/).first().innerText()
    agentToken = command.match(/vgl_[\w-]+/)![0]
    await page.getByRole('button', { name: 'Я виконав команди' }).click()
    const targets = await page.request.get('/api/targets', { headers: { Authorization: `Bearer ${await jwt(page)}` } })
    targetId = (await targets.json())[0].id
    expect(targetId).toBeGreaterThan(0)
  })

  test('метрика від агента відкриває інцидент із причиною, його можна підтвердити', async ({ page }) => {
    await page.goto('/login')
    await page.locator('#email').fill(email)
    await page.locator('#password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Увійти' }).click()
    await expect(page).toHaveURL(/\/$/)
    // поріг без очікування, щоб тест не чекав хвилину; налаштування – справжній маршрут API
    const put = await page.request.put('/api/thresholds', {
      headers: { Authorization: `Bearer ${await jwt(page)}` },
      data: { metric: 'disk_usage', target_id: null, warn: 85, crit: 95, duration_s: 0 },
    })
    expect(put.status()).toBe(204)

    await sendMetrics(page.request, agentToken, [{ metric: 'disk_usage', instance: '/', value: 97 }])
    // сторінку не перезавантажуємо: інцидент має з'явитися через WebSocket
    await expect(page.getByText(/Критично/).first()).toBeVisible({ timeout: 15_000 })

    await page.goto('/incidents')
    await page.getByRole('link', { name: HOST }).first().click()  // у таблиці посилання – назва об’єкта
    const diagnosis = page.getByLabel('Діагностика')
    await expect(diagnosis).toContainText('Ймовірна причина')
    await expect(diagnosis).toContainText('Заповнення диска')
    await page.getByRole('button', { name: /Підтвердити/ }).click()
    await expect(page.getByRole('button', { name: 'Підтверджено' })).toBeVisible()
  })

  test('інший користувач не бачить чужий сервер', async ({ browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await register(page, `e2e-other-${stamp}@example.com`)
    const r = await page.request.get(`/api/targets/${targetId}`, { headers: { Authorization: `Bearer ${await jwt(page)}` } })
    expect(r.status()).toBe(404)
    await page.goto(`/targets/${targetId}`)
    await expect(page.getByText(HOST)).toHaveCount(0)
    await ctx.close()
  })
})
